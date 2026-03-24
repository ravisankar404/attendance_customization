import frappe
from frappe.utils import getdate


def after_insert(doc, method):
    """
    Fires every time an Employee Checkin record is inserted.

    When a half-day leave is approved, HRMS creates a submitted Attendance
    record with status="Half Day" and leave_application set. The Monthly
    Attendance Sheet reads leave_application to show HD/L (not HD/A), and
    payroll counts it as leave — not as an absent half-day.

    However, mark_attendance (ProcessAttendance) re-runs daily and skips
    any date that already has a submitted attendance. The problem: it checks
    whether a checkin is linked to an attendance to decide if it needs
    processing. An unlinked checkin on a Half Day date could cause
    mark_attendance to overwrite the status with Present/Absent.

    Fix: as soon as a checkin arrives for a date that already has a submitted
    Half Day attendance, write in_time/out_time and link the checkin.

    For checkins that arrive BEFORE leave approval (no attendance exists yet),
    leave_application.on_update_after_submit handles the retroactive link.

    Edge cases:
    - doc.time is None: return early.
    - No Half Day attendance for the date: return early (normal working day).
    - log_type is IN but in_time already set: skip time update, still link.
    - log_type is OUT but out_time already set: skip time update, still link.
    - log_type missing: link only (prevents reprocessing without setting times).
    """
    if not doc.time:
        return

    checkin_date = getdate(doc.time)

    attendance = frappe.db.get_value(
        "Attendance",
        {
            "employee": doc.employee,
            "attendance_date": checkin_date,
            "status": "Half Day",
            "docstatus": 1,
        },
        ["name", "in_time", "out_time"],
        as_dict=True,
    )

    if not attendance:
        return

    update = {}

    if doc.log_type == "IN" and not attendance.in_time:
        update["in_time"] = doc.time
    elif doc.log_type == "OUT" and not attendance.out_time:
        update["out_time"] = doc.time

    if update:
        frappe.db.set_value("Attendance", attendance.name, update)

    frappe.db.set_value("Employee Checkin", doc.name, "attendance", attendance.name)

    frappe.logger().info(
        "Half Day attendance {}: updated {} from Employee Checkin {}".format(
            attendance.name,
            list(update.keys()) if update else ["linked only"],
            doc.name,
        )
    )
