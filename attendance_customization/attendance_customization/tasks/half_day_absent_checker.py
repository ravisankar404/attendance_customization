import frappe
from frappe.utils import add_days, getdate, nowdate


def check_half_day_no_show(date=None):
    """
    Runs daily at 6 AM and audits the previous day's Half Day leave attendance.

    PROBLEM:
        When an employee has an approved half-day leave, HRMS creates a submitted
        Attendance with status="Half Day" and leave_application set → shows HD/P
        in the Monthly Attendance Sheet → no salary deduction, 0.5 leave consumed.

        But if the employee ALSO doesn't come for the working half (no valid
        checkins), the system should reflect: leave for one half + absent for other.

    VALID PAIR REQUIREMENT:
        A valid attendance for the working half requires BOTH an IN checkin AND
        an OUT checkin. If the employee only has one punch (forgot to check out,
        or device missed one swipe), that is treated the same as not coming in:
          → leave_application removed, half_day_status = "Absent" → HD/A.

    FIX:
        If an employee has a Half Day leave attendance but no valid IN+OUT checkin
        pair for that date, we remove the leave_application link and set
        half_day_status="Absent" on the attendance record.

        Result:
          - Attendance stays "Half Day" but now shows HD/A in Monthly Sheet
            (absent/incomplete for the working half).
          - Leave Application stays approved → 0.5 leave balance consumed.
          - Payroll: 0.5 day salary deduction (for the absent working half).
          Net = L/A: leave covers one half, absent deduction for the other.

    WHY 6 AM NEXT MORNING:
        Gives the full working day (and any delayed biometric syncs) to record
        both check-in AND check-out before we declare the employee absent.

    EDGE CASE — biometric failure / device without log_type:
        If the device doesn't send log_type (IN/OUT), checkins with a blank
        log_type are treated as a valid signal that the employee was present —
        benefit of the doubt. HR can manually correct if needed.

    EDGE CASE — late biometric sync after this task runs:
        employee_checkin.after_insert will restore leave_application and set
        half_day_status="Present" when a late checkin arrives — but only if
        the new checkin completes a valid IN+OUT pair for that date.
    """
    yesterday = getdate(date) if date else getdate(add_days(nowdate(), -1))

    # Query 1: all submitted Half Day attendances with leave linked for yesterday.
    attendances = frappe.get_all(
        "Attendance",
        filters=[
            ["attendance_date", "=", yesterday],
            ["status", "=", "Half Day"],
            ["docstatus", "=", 1],
            ["leave_application", "is", "set"],
        ],
        fields=["name", "employee"],
    )

    if not attendances:
        return

    employees_on_leave = {a.employee: a.name for a in attendances}

    # Query 2: employees who have a valid IN+OUT pair for yesterday.
    # Also treat untyped checkins (log_type IS NULL) as valid — legacy device support.
    # Two separate sub-queries unioned to keep the SQL readable and indexed.
    employees_with_valid_pair = set(frappe.db.sql_list("""
        SELECT employee
        FROM `tabEmployee Checkin`
        WHERE employee IN %(employees)s
          AND DATE(time) = %(date)s
          AND log_type IN ('IN', 'OUT')
        GROUP BY employee
        HAVING COUNT(DISTINCT log_type) = 2

        UNION

        SELECT DISTINCT employee
        FROM `tabEmployee Checkin`
        WHERE employee IN %(employees)s
          AND DATE(time) = %(date)s
          AND (log_type IS NULL OR log_type = '')
    """, {"employees": list(employees_on_leave.keys()), "date": yesterday}))

    # Employees without a valid pair = absent/incomplete for working half → HD/A.
    no_show_employees = set(employees_on_leave.keys()) - employees_with_valid_pair

    if not no_show_employees:
        return

    no_show_att_names = [employees_on_leave[e] for e in no_show_employees]

    try:
        frappe.db.sql("""
            UPDATE `tabAttendance`
            SET leave_application = NULL, half_day_status = 'Absent', modified = NOW()
            WHERE name IN %(names)s
        """, {"names": no_show_att_names})

        frappe.logger().info(
            "half_day_absent_checker [{}]: {} employee(s) changed to HD/A "
            "(no valid IN+OUT pair for working half): {}".format(
                yesterday, len(no_show_employees), ", ".join(no_show_employees)
            )
        )
    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="half_day_absent_checker [{}]: bulk update failed".format(yesterday),
        )
