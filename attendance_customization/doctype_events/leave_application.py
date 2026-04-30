import frappe


# ─────────────────────────────────────────────
# Document event hooks
# ─────────────────────────────────────────────

def on_submit(doc, method):
    """
    Fires when a Leave Application is submitted (docstatus 0→1).

    If the leave is already Approved at submit time (e.g. manager creates and
    approves in one action), HRMS has just run update_attendance() which creates
    a submitted Half Day attendance with leave_application set. Link any
    checkins that exist for that date, then handle the dual-half-day scenario.
    """
    if not _is_half_day(doc):
        return
    if doc.status == "Approved":
        _link_checkins(doc)
        _handle_dual_half_day(doc.employee, doc.half_day_date)


def on_update_after_submit(doc, method):
    """
    Fires when a submitted Leave Application is updated (docstatus stays 1).

    ESS workflow: employee submits (status=Open) → manager approves or rejects.

    On Approved  → HRMS has just created the Half Day attendance; link checkins
                   and handle the dual-half-day scenario.
    On Rejected/Cancelled → HRMS has just cancelled the attendance; unlink
                            checkins so mark_attendance can reprocess them,
                            and restore Half Day if another leave still stands.
    """
    if not _is_half_day(doc):
        return

    if doc.status == "Approved":
        _link_checkins(doc)
        _handle_dual_half_day(doc.employee, doc.half_day_date)
    elif doc.status in ("Rejected", "Cancelled"):
        _unlink_checkins(doc)
        _handle_dual_half_day_cancel(doc)


def on_cancel(doc, method):
    """
    Fires when a Leave Application is cancelled (docstatus 1→2).

    HRMS has just run cancel_attendance() which cancels ANY submitted
    attendance for the employee in the date range with status 'Half Day' or
    'On Leave' — it does NOT filter by leave_application. This means:

      • After our dual-half-day upgrade, the attendance status is 'On Leave'.
        HRMS's cancel_attendance() will cancel it when EITHER leave is cancelled.
      • _unlink_checkins() below only releases checkins from cancelled 'Half Day'
        attendances; it will miss the cancelled 'On Leave' one — we handle that
        explicitly inside _handle_dual_half_day_cancel (Case B).

    Flow:
      1. _unlink_checkins  — release checkins from any cancelled Half Day
                             attendance (pre-upgrade records / edge cases).
      2. _handle_dual_half_day_cancel — if another approved half-day leave
                             still exists for the date, restore a Half Day
                             attendance for it (including the checkin re-link
                             that _unlink_checkins missed for On Leave status).
    """
    if not _is_half_day(doc):
        return
    _unlink_checkins(doc)
    _handle_dual_half_day_cancel(doc)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _is_half_day(doc):
    return bool(doc.half_day and doc.half_day_date)


def _link_checkins(leave_doc):
    """
    After leave approval, HRMS update_attendance() has already created a
    submitted Half Day attendance record with leave_application set (which is
    what makes the Monthly Attendance Sheet show HD/L instead of HD/A).

    This function links any Employee Checkin records for the half_day_date
    that were inserted before the attendance existed (so they were skipped by
    employee_checkin.after_insert). Linking them prevents mark_attendance from
    reprocessing those checkins and overwriting the Half Day status.

    Edge cases handled:
    - No attendance exists yet (HRMS failed silently): returns safely.
    - No unlinked checkins found, but attendance already has in_time + out_time:
      mark_attendance ran before the leave was approved and linked the checkins
      itself. HRMS's db_set() changed status to Half Day without firing
      validate(), so half_day_status was never set. Sync it now so the Monthly
      Attendance Sheet shows HD/P instead of HD/A.
    - Checkins with no log_type: linked to attendance but in_time/out_time
      not set (prevents reprocessing without corrupting existing times).
    - in_time or out_time already populated on attendance: not overwritten.
    - Called more than once for the same leave: idempotent because the filter
      excludes already-linked checkins.
    """
    employee = leave_doc.employee
    half_day_date = leave_doc.half_day_date

    attendance = frappe.db.get_value(
        "Attendance",
        {
            "employee": employee,
            "attendance_date": half_day_date,
            "status": "Half Day",
            "docstatus": 1,
        },
        ["name", "in_time", "out_time"],
        as_dict=True,
    )

    if not attendance:
        return

    checkins = frappe.get_all(
        "Employee Checkin",
        filters=[
            ["employee", "=", employee],
            ["time", "between", [
                "{} 00:00:00".format(half_day_date),
                "{} 23:59:59".format(half_day_date),
            ]],
            ["attendance", "is", "not set"],
        ],
        fields=["name", "log_type", "time"],
        order_by="time asc",
    )

    if not checkins:
        # No unlinked checkins found — mark_attendance may have already run before
        # the leave was approved and linked them itself.  In that case the attendance
        # already has in_time + out_time, but half_day_status was never set (HRMS
        # used db_set to flip status→Half Day, bypassing validate).  Sync it now so
        # the Monthly Attendance Sheet shows HD/P instead of HD/A.
        if attendance.in_time and attendance.out_time:
            frappe.db.set_value("Attendance", attendance.name, "half_day_status", "Present")
        return

    in_time = attendance.in_time
    out_time = attendance.out_time

    for checkin in checkins:
        update = {}

        if checkin.log_type == "IN" and not in_time:
            update["in_time"] = checkin.time
            in_time = checkin.time

        elif checkin.log_type == "OUT" and not out_time:
            update["out_time"] = checkin.time
            out_time = checkin.time

        if update:
            frappe.db.set_value("Attendance", attendance.name, update)

        frappe.db.set_value("Employee Checkin", checkin.name, "attendance", attendance.name)

    # Set half_day_status based on pair completeness.
    # Untyped checkins (no log_type) count as valid — legacy device support.
    has_untyped = any(not c.log_type for c in checkins)
    if (in_time and out_time) or has_untyped:
        frappe.db.set_value("Attendance", attendance.name, "half_day_status", "Present")
    else:
        # Only one typed punch → incomplete → HD/A.
        # employee_checkin.after_insert will flip to HD/P when the second punch arrives.
        frappe.db.set_value("Attendance", attendance.name, "half_day_status", "Absent")

    frappe.logger().info(
        "Half Day attendance {}: linked {} checkin(s) after leave approval, "
        "half_day_status={}".format(
            attendance.name,
            len(checkins),
            "Present" if (in_time and out_time) else "Absent",
        )
    )


def _unlink_checkins(leave_doc):
    """
    When a half-day leave is cancelled or rejected, HRMS cancel_attendance()
    has already set the attendance to docstatus=2. Unlink all checkins from
    those cancelled attendance records so mark_attendance can pick them up
    and create a fresh Present/Absent from the actual checkin data.

    NOTE: This function only handles 'Half Day' status attendances. Cancelled
    'On Leave' attendances (produced by the dual-half-day upgrade) are handled
    separately in _handle_dual_half_day_cancel (Case B).

    Edge cases handled:
    - No cancelled attendance found: returns safely (leave was never approved,
      so no attendance or checkins were ever linked).
    - Multiple cancelled Half Day attendances for the same date (e.g. leave
      was approved, cancelled, re-approved, cancelled again): all are handled.
    - Checkins already unlinked: frappe.get_all returns an empty list, no-op.
    """
    employee = leave_doc.employee
    half_day_date = leave_doc.half_day_date

    cancelled_attendances = frappe.get_all(
        "Attendance",
        filters={
            "employee": employee,
            "attendance_date": half_day_date,
            "status": "Half Day",
            "docstatus": 2,
        },
        fields=["name"],
    )

    if not cancelled_attendances:
        return

    total_unlinked = 0
    for record in cancelled_attendances:
        linked_checkins = frappe.get_all(
            "Employee Checkin",
            filters={"attendance": record.name},
            fields=["name"],
        )
        for checkin in linked_checkins:
            frappe.db.set_value("Employee Checkin", checkin.name, "attendance", None)
        total_unlinked += len(linked_checkins)

    if total_unlinked:
        frappe.logger().info(
            "Unlinked {} checkin(s) from cancelled Half Day attendance(s) on {} "
            "so mark_attendance can reprocess them".format(total_unlinked, half_day_date)
        )


# ─────────────────────────────────────────────
# Dual half-day leave handlers
# ─────────────────────────────────────────────

def _handle_dual_half_day(employee, date):
    """
    When two approved half-day leaves of different leave types cover the same
    date, the employee has no working half left — the full day is covered by
    leave. Upgrade attendance from "Half Day" → "On Leave" so payroll and the
    Monthly Attendance Sheet treat it correctly (full leave day; both leave
    balances consumed; no additional salary deduction).

    Called after every half-day leave approval so the upgrade fires as soon
    as the second leave lands — regardless of submission order.

    WHY HRMS DOESN'T HANDLE THIS:
        HRMS's create_or_update_attendance() sets status = "Half Day" whenever
        self.half_day_date == date. It never checks whether a second half-day
        leave already exists for the same date, so it always leaves the status
        as "Half Day" even when both halves are covered.

    WHAT WE DO:
        Count approved half-day leaves for the date. If >= 2, upgrade the
        submitted attendance to "On Leave" and clear half_day_status (it is
        not applicable for a full-day "On Leave" record).

    SAFE WITH EXISTING HOOKS:
        attendance.validate → _ensure_half_day_attendance has an early exit
        for status "On Leave", so it will never downgrade back.
        employee_checkin.after_insert queries status = "Half Day" only, so it
        will not touch the upgraded record.
        half_day_absent_checker queries status = "Half Day" only — same.
    """
    approved_half_day_leaves = frappe.get_all(
        "Leave Application",
        filters={
            "employee": employee,
            "half_day_date": date,
            "half_day": 1,
            "status": "Approved",
            "docstatus": 1,
        },
        fields=["name"],
        limit=2,  # we only need to know if there are >= 2
    )

    if len(approved_half_day_leaves) < 2:
        return  # Normal single half-day flow — nothing to do.

    attendance = frappe.db.get_value(
        "Attendance",
        {"employee": employee, "attendance_date": date, "docstatus": 1},
        ["name", "status"],
        as_dict=True,
    )

    if not attendance or attendance.status == "On Leave":
        return  # Already correct or no submitted attendance to upgrade.

    frappe.db.set_value("Attendance", attendance.name, {
        "status": "On Leave",
        "half_day_status": None,
    })

    frappe.logger().info(
        "dual_half_day [{} {}]: upgraded '{}' → 'On Leave' "
        "(two approved half-day leaves detected)".format(
            employee, date, attendance.status
        )
    )


def _handle_dual_half_day_cancel(leave_doc):
    """
    When one of two half-day leaves covering the same date is cancelled or
    rejected, restore the correct Half Day attendance for the surviving leave.

    BACKGROUND:
        After _handle_dual_half_day ran, the attendance for the date has
        status = "On Leave". HRMS's cancel_attendance() (HRMS 16) searches
        for attendances by date + status IN ('On Leave', 'Half Day') — NOT
        by leave_application. So it cancels the "On Leave" attendance when
        EITHER leave is cancelled, regardless of which leave's name is on it.

    TWO CASES at the time our hook fires (HRMS runs first):

    Case A — Attendance still submitted (docstatus=1):
        Occurs when the leave was Rejected (docstatus stayed 1) and HRMS did
        not call cancel_attendance(). The "On Leave" attendance still exists.
        → Downgrade attendance to "Half Day" and re-link to the surviving leave.

    Case B — Attendance already cancelled by HRMS (docstatus=2):
        The cancelled leave triggered cancel_attendance() which set docstatus=2
        on the "On Leave" attendance. No submitted attendance exists for the date.
        _unlink_checkins() above will have missed the checkins (it only looks
        for cancelled "Half Day" attendances, not "On Leave").
        → Release checkins still pointing to the cancelled "On Leave" attendance.
        → Create a fresh Half Day attendance for the surviving leave.
        → Re-link those checkins to the new attendance.

    If no other approved half-day leave exists for the date (not a dual-half-day
    situation, or both leaves are now cancelled), returns immediately and lets
    the normal unlink flow handle things.
    """
    employee = leave_doc.employee
    date = leave_doc.half_day_date
    cancelled_leave_name = leave_doc.name

    # Other approved half-day leaves still standing for this date.
    remaining_leaves = frappe.get_all(
        "Leave Application",
        filters={
            "employee": employee,
            "half_day_date": date,
            "half_day": 1,
            "status": "Approved",
            "docstatus": 1,
            "name": ("!=", cancelled_leave_name),
        },
        fields=["name", "leave_type"],
        limit=1,
    )

    if not remaining_leaves:
        return  # Not a dual-half-day situation — normal flow takes over.

    remaining_leave = remaining_leaves[0]

    # ── Case A: submitted attendance still exists ────────────────────────────
    # HRMS did not cancel it (Rejected status, docstatus stayed 1).
    attendance = frappe.db.get_value(
        "Attendance",
        {"employee": employee, "attendance_date": date, "docstatus": 1},
        ["name", "status", "in_time", "out_time"],
        as_dict=True,
    )

    if attendance:
        has_pair = bool(attendance.in_time and attendance.out_time)
        frappe.db.set_value("Attendance", attendance.name, {
            "status": "Half Day",
            "leave_application": remaining_leave.name,
            "leave_type": remaining_leave.leave_type,
            "half_day_status": "Present" if has_pair else "Absent",
        })
        frappe.logger().info(
            "dual_half_day_cancel [{} {}]: downgraded 'On Leave' → 'Half Day', "
            "re-linked to {} (leave {} cancelled/rejected)".format(
                employee, date, remaining_leave.name, cancelled_leave_name
            )
        )
        return

    # ── Case B: HRMS cancelled the attendance (docstatus=2) ──────────────────
    # _unlink_checkins() only looks for cancelled 'Half Day' attendances and
    # will have missed this one (status was 'On Leave'). Find the cancelled
    # attendance and release its checkins before creating a fresh record.
    cancelled_atts = frappe.get_all(
        "Attendance",
        filters={"employee": employee, "attendance_date": date, "docstatus": 2},
        fields=["name"],
        order_by="modified desc",
        limit=1,
    )
    cancelled_att_name = cancelled_atts[0].name if cancelled_atts else None

    if cancelled_att_name:
        # Release checkins that _unlink_checkins missed (status was 'On Leave').
        frappe.db.sql("""
            UPDATE `tabEmployee Checkin`
               SET attendance = NULL,
                   modified   = NOW()
             WHERE attendance = %(att)s
        """, {"att": cancelled_att_name})

    _restore_half_day_attendance(employee, date, remaining_leave)


def _restore_half_day_attendance(employee, date, leave):
    """
    Create a fresh submitted Half Day attendance for `leave` and link any
    Employee Checkin records that are currently unlinked for that date.

    Used exclusively by _handle_dual_half_day_cancel (Case B) to rebuild the
    attendance after HRMS cancelled the 'On Leave' record.

    The checkins were just released (by the SQL UPDATE above) so the
    attendance IS NOT SET filter will find them.

    half_day_status defaults to "Absent" and is upgraded to "Present" only
    when a valid IN+OUT pair (or an untyped checkin) is found — same
    conservative logic used everywhere else in this app.
    """
    emp = frappe.db.get_value(
        "Employee", employee, ["employee_name", "company"], as_dict=True
    )

    new_doc = frappe.new_doc("Attendance")
    new_doc.employee       = employee
    new_doc.employee_name  = emp.employee_name
    new_doc.attendance_date = date
    new_doc.company        = emp.company
    new_doc.status         = "Half Day"
    new_doc.leave_type     = leave.leave_type
    new_doc.leave_application = leave.name
    new_doc.half_day_status   = "Absent"     # conservative; updated below if checkins found
    new_doc.flags.ignore_validate = True     # fields set manually; skip lifecycle hooks
    new_doc.insert(ignore_permissions=True)
    new_doc.submit()

    new_att_name = new_doc.name

    # Link unlinked checkins for the date (released by the SQL above).
    unlinked = frappe.get_all(
        "Employee Checkin",
        filters=[
            ["employee", "=", employee],
            ["time", "between", [
                "{} 00:00:00".format(date),
                "{} 23:59:59".format(date),
            ]],
            ["attendance", "is", "not set"],
        ],
        fields=["name", "log_type", "time"],
        order_by="time asc",
    )

    in_time  = None
    out_time = None

    for checkin in unlinked:
        if checkin.log_type == "IN" and not in_time:
            in_time = checkin.time
        elif checkin.log_type == "OUT" and not out_time:
            out_time = checkin.time
        frappe.db.set_value("Employee Checkin", checkin.name, "attendance", new_att_name)

    time_updates = {}
    if in_time:
        time_updates["in_time"]  = in_time
    if out_time:
        time_updates["out_time"] = out_time
    if time_updates:
        frappe.db.set_value("Attendance", new_att_name, time_updates)

    has_untyped = any(not c.log_type for c in unlinked)
    if (in_time and out_time) or has_untyped:
        frappe.db.set_value("Attendance", new_att_name, "half_day_status", "Present")

    frappe.logger().info(
        "dual_half_day_cancel [{} {}]: created new Half Day attendance {} "
        "linked to {} ({} checkin(s) re-linked)".format(
            employee, date, new_att_name, leave.name, len(unlinked)
        )
    )
