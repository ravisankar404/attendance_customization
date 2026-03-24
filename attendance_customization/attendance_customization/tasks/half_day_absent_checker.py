import frappe
from frappe.utils import add_days, getdate, nowdate


def check_half_day_no_show(date=None):
    """
    Runs daily at 6 AM and audits the previous day's Half Day leave attendance.

    PROBLEM:
        When an employee has an approved half-day leave, HRMS creates a submitted
        Attendance with status="Half Day" and leave_application set → shows HD/L
        in the Monthly Attendance Sheet → no salary deduction, 0.5 leave consumed.

        But if the employee ALSO doesn't come for the working half (no checkins),
        the system should reflect: leave for one half + absent for the other.

    FIX:
        If an employee has a Half Day leave attendance but zero checkins for that
        date, we remove the leave_application link from the attendance record.

        Result:
          - Attendance stays "Half Day" but now shows HD/A in Monthly Sheet
            (absent for the working half).
          - Leave Application stays approved → 0.5 leave balance consumed.
          - Payroll: 0.5 day salary deduction (for the absent working half).
          Net = L/A: leave covers one half, absent deduction for the other.

    WHY 6 AM NEXT MORNING:
        Gives the full working day (and any delayed biometric syncs) to record
        checkins before we declare the employee absent. By 6 AM the next day
        the full previous day including any afternoon/evening shift is done.

    EDGE CASE — biometric failure:
        If the employee genuinely came in but the device didn't record the
        checkin, this task will incorrectly mark HD/A. HR can manually restore
        the leave_application link on the Attendance record if needed.

    EDGE CASE — leave approved for a future date (pre-approval):
        The task only checks yesterday. Pre-approved future leaves are handled
        correctly because the check runs the morning AFTER the leave date.

    EDGE CASE — leave rejected/cancelled on the same day:
        If the leave was cancelled before this task runs, the attendance is
        already docstatus=2 (cancelled by HRMS). The filter "docstatus=1"
        excludes it — the task does nothing. Correct. ✓
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

    # Query 2: single query for ALL checkins yesterday for all these employees.
    # No N+1 — one query regardless of how many employees.
    employees_with_checkins = set(frappe.db.sql_list("""
        SELECT DISTINCT employee
        FROM `tabEmployee Checkin`
        WHERE employee IN %(employees)s
        AND DATE(time) = %(date)s
    """, {"employees": list(employees_on_leave.keys()), "date": yesterday}))

    # Employees with no checkins = absent for working half → change to HD/A.
    no_show_employees = set(employees_on_leave.keys()) - employees_with_checkins

    if not no_show_employees:
        return

    no_show_att_names = [employees_on_leave[e] for e in no_show_employees]

    # Single bulk UPDATE instead of one set_value per record.
    try:
        frappe.db.sql("""
            UPDATE `tabAttendance`
            SET leave_application = NULL, modified = NOW()
            WHERE name IN %(names)s
        """, {"names": no_show_att_names})

        frappe.logger().info(
            "half_day_absent_checker [{}]: {} employee(s) changed to HD/A "
            "(no checkins for working half): {}".format(
                yesterday, len(no_show_employees), ", ".join(no_show_employees)
            )
        )
    except Exception:
        frappe.log_error(
            message=frappe.get_traceback(),
            title="half_day_absent_checker [{}]: bulk update failed".format(yesterday),
        )
