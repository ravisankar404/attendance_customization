import frappe
from frappe import _
from frappe.utils import getdate


def after_insert(doc, method):
    """
    Fires every time an Employee Checkin record is inserted.

    Problem this solves
    -------------------
    When a half-day leave is approved for a FUTURE date, Frappe's standard
    Leave Application.update_attendance() (and our AR submission) pre-creates
    an Attendance record with status="Half Day" and no in_time/out_time.

    When the actual day arrives and the employee punches in/out, the
    mark_attendance scheduled job sees the existing Attendance record and
    SKIPS that date entirely — so in_time/out_time are never recorded.

    Fix
    ---
    As soon as a Checkin arrives for a date that already has a submitted
    Half Day attendance, we immediately write the time onto the attendance
    record directly, bypassing the skip logic in mark_attendance.
    """
    if not doc.time:
        return

    checkin_date = getdate(doc.time)

    # Find a submitted Half Day attendance for this employee on this date.
    # Only target Half Day — Present/Absent already go through normal processing.
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
        # No pre-existing Half Day attendance — let mark_attendance handle it normally.
        return

    if not doc.log_type:
        # Can't determine IN vs OUT — skip to avoid writing wrong field.
        return

    update = {}

    if doc.log_type == "IN" and not attendance.in_time:
        update["in_time"] = doc.time

    elif doc.log_type == "OUT" and not attendance.out_time:
        update["out_time"] = doc.time

    if not update:
        # Field already populated (duplicate checkin) — nothing to do.
        return

    frappe.db.set_value("Attendance", attendance.name, update)

    # Also link the checkin to the attendance record so ProcessAttendance
    # knows this checkin is already handled and does not reprocess it.
    # Without this, ProcessAttendance sees an "unlinked" checkin and may
    # try to create/update attendance again — potentially overwriting our
    # Half Day status with "Present".
    frappe.db.set_value("Employee Checkin", doc.name, "attendance", attendance.name)

    frappe.logger().info(
        "Half Day attendance {0}: updated {1} from Employee Checkin {2}".format(
            attendance.name,
            list(update.keys()),
            doc.name,
        )
    )
