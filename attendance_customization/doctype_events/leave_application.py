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
    checkins that exist for that date.
    """
    if not _is_half_day(doc):
        return
    if doc.status == "Approved":
        _link_checkins(doc)


def on_update_after_submit(doc, method):
    """
    Fires when a submitted Leave Application is updated (docstatus stays 1).

    ESS workflow: employee submits (status=Open) → manager approves or rejects.

    On Approved  → HRMS has just created the Half Day attendance; link checkins.
    On Rejected/Cancelled → HRMS has just cancelled the attendance; unlink
                            checkins so mark_attendance can reprocess them.
    """
    if not _is_half_day(doc):
        return

    if doc.status == "Approved":
        _link_checkins(doc)
    elif doc.status in ("Rejected", "Cancelled"):
        _unlink_checkins(doc)


def on_cancel(doc, method):
    """
    Fires when a Leave Application is cancelled (docstatus 1→2).
    HRMS has just cancelled the Half Day attendance; unlink checkins so
    mark_attendance can reprocess them and produce a correct Present/Absent.
    """
    if not _is_half_day(doc):
        return
    _unlink_checkins(doc)


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
    - No unlinked checkins: returns safely.
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
