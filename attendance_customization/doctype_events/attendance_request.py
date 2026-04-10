import frappe


# ─────────────────────────────────────────────
# Document event hooks (registered in hooks.py)
# ─────────────────────────────────────────────

def on_submit(doc, method):
    """
    Fires AFTER HRMS's own AttendanceRequest.on_submit() creates/updates the
    Half Day attendance for half_day_date.

    TWO PROBLEMS THIS FIXES:

    Problem 1 — db_set() bypass (most common, Jasmine-style case):
        When an employee already has a biometric-created attendance (mark_attendance
        ran and created "Present" with in_time/out_time), HRMS does:
            doc.db_set({"status": "Half Day", "attendance_request": self.name})
        db_set() bypasses Frappe's document lifecycle — validate() never fires,
        so half_day_status stays NULL (shown as "Absent" in Monthly Sheet) even
        though in_time and out_time are both set.

    Problem 2 — checkins not yet linked (race with mark_attendance):
        When the Attendance Request is approved before mark_attendance processes
        biometric data, HRMS creates a new attendance with no in_time/out_time.
        The checkins exist in Employee Checkin but are unlinked. Calling
        _sync_half_day_status alone would read both times as NULL → "Absent" ✗.

    FIX ORDER:
        1. _link_unlinked_checkins — populate in_time/out_time from any unlinked
           Employee Checkin records (handles Problem 2; no-op for Problem 1
           because in_time/out_time are already on the record).
        2. _sync_half_day_status — read the resulting in_time/out_time and write
           the correct half_day_status.
    """
    if not (doc.half_day and doc.half_day_date):
        return

    _link_unlinked_checkins(doc.employee, doc.half_day_date)
    _sync_half_day_status(doc.employee, doc.half_day_date)


def on_cancel(doc, method):
    """
    Fires AFTER HRMS's own AttendanceRequest.on_cancel() cancels the
    Half Day attendance record (docstatus → 2).

    PROBLEM this fixes:
        HRMS cancels the attendance but does NOT unlink the Employee Checkin
        records that point to it. Those checkins still have:
            attendance = <cancelled-attendance-name>
        When the Attendance Request is re-submitted, _link_unlinked_checkins()
        searches for checkins WHERE attendance IS NOT SET — it finds none —
        so the new attendance is created with no in_time/out_time → "Absent" ✗.

    FIX:
        After HRMS cancels the attendance, unlink all its Employee Checkins
        so they are available for re-linking on re-submission.
    """
    if not (doc.half_day and doc.half_day_date):
        return

    _unlink_checkins_from_cancelled_attendance(doc.employee, doc.half_day_date)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _link_unlinked_checkins(employee, half_day_date):
    """
    Find Employee Checkin records for half_day_date that are not yet linked to
    the Half Day attendance, and write in_time/out_time on the attendance.

    Mirrors leave_application._link_checkins() for the Attendance Request path
    (no Leave Application is involved so leave_application field stays NULL).

    SKIPS entirely if both in_time and out_time are already set — meaning
    mark_attendance ran before the Attendance Request was approved, in which
    case the times are already on the record and we just need to sync status.
    """
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

    # Both times already present — mark_attendance already ran. Nothing to link.
    if attendance.in_time and attendance.out_time:
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
    time_updates = {}

    for checkin in checkins:
        if checkin.log_type == "IN" and not in_time:
            time_updates["in_time"] = checkin.time
            in_time = checkin.time
        elif checkin.log_type == "OUT" and not out_time:
            time_updates["out_time"] = checkin.time
            out_time = checkin.time

        frappe.db.set_value("Employee Checkin", checkin.name, "attendance", attendance.name)

    if time_updates:
        frappe.db.set_value("Attendance", attendance.name, time_updates)

    frappe.logger().info(
        "attendance_request.on_submit: linked {} checkin(s) to {} "
        "(employee={}, date={})".format(
            len(checkins), attendance.name, employee, half_day_date
        )
    )


def _unlink_checkins_from_cancelled_attendance(employee, half_day_date):
    """
    After Attendance Request cancellation, HRMS has already cancelled the
    attendance (docstatus=2). Find that cancelled attendance and set
    attendance=NULL on all its linked Employee Checkin records so they are
    free to be re-linked when the Attendance Request is re-submitted.

    Mirrors leave_application._unlink_checkins() for the Attendance Request path.
    """
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
            "attendance_request.on_cancel: unlinked {} checkin(s) from cancelled "
            "Half Day attendance(s) on {} (employee={})".format(
                total_unlinked, half_day_date, employee
            )
        )


def _sync_half_day_status(employee, half_day_date):
    """
    Read the current in_time/out_time on the Half Day attendance and write
    half_day_status:
      - Both set → "Present"  (employee worked the other half)
      - One or neither → "Absent"
    """
    attendance = frappe.db.get_value(
        "Attendance",
        {
            "employee": employee,
            "attendance_date": half_day_date,
            "status": "Half Day",
            "docstatus": 1,
        },
        ["name", "in_time", "out_time", "half_day_status"],
        as_dict=True,
    )

    if not attendance:
        return

    expected = "Present" if (attendance.in_time and attendance.out_time) else "Absent"

    if attendance.half_day_status != expected:
        frappe.db.set_value("Attendance", attendance.name, "half_day_status", expected)
        frappe.logger().info(
            "attendance_request.on_submit: {} → half_day_status '{}' → '{}' "
            "(employee={}, date={})".format(
                attendance.name,
                attendance.half_day_status or "NULL",
                expected,
                employee,
                half_day_date,
            )
        )
