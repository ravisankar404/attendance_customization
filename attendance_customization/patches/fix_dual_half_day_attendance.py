"""
Patch: fix_dual_half_day_attendance

ROOT CAUSE:
    When an employee submits two approved half-day Leave Applications of
    different leave types on the same date (e.g. CL-0.5 + SL-0.5), HRMS's
    create_or_update_attendance() always sets status = "Half Day" for each
    leave individually. It never checks whether a second half-day already
    exists, so the attendance is left as "Half Day" instead of "On Leave".

    The result: only 0.5 leave consumed (the second leave overwrites the
    first's leave_application link), and payroll sees "Half Day" instead of
    "On Leave", causing incorrect deductions.

WHAT THIS PATCH DOES:
    1. Finds all (employee, date) pairs that have 2+ approved half-day leaves.
    2. For each pair, if the current submitted attendance is NOT already
       "On Leave", upgrades it to "On Leave" and clears half_day_status.

SAFE TO RUN:
    - Fully idempotent — re-running has no effect on already-fixed records.
    - Does not touch leave ledger entries, leave balances, or payroll records.
    - Only updates attendance status via frappe.db.set_value (no hooks fired).
"""

import frappe


def execute():
    # Find all employee-date pairs with 2+ approved half-day leaves.
    dual_cases = frappe.db.sql("""
        SELECT employee, half_day_date
          FROM `tabLeave Application`
         WHERE half_day      = 1
           AND status        = 'Approved'
           AND docstatus     = 1
           AND half_day_date IS NOT NULL
         GROUP BY employee, half_day_date
        HAVING COUNT(*) >= 2
    """, as_dict=True)

    if not dual_cases:
        frappe.logger().info("fix_dual_half_day_attendance: no dual half-day cases found.")
        return

    fixed   = 0
    skipped = 0

    for case in dual_cases:
        attendance = frappe.db.get_value(
            "Attendance",
            {
                "employee":        case.employee,
                "attendance_date": case.half_day_date,
                "docstatus":       1,
            },
            ["name", "status"],
            as_dict=True,
        )

        if not attendance:
            skipped += 1
            continue

        if attendance.status == "On Leave":
            skipped += 1   # already correct
            continue

        frappe.db.set_value("Attendance", attendance.name, {
            "status":          "On Leave",
            "half_day_status": None,
        })
        fixed += 1

    frappe.db.commit()

    frappe.logger().info(
        "fix_dual_half_day_attendance: upgraded {} record(s) to 'On Leave', "
        "skipped {} (already correct or no attendance found).".format(fixed, skipped)
    )
    print(
        "fix_dual_half_day_attendance: fixed={}, skipped={}".format(fixed, skipped)
    )
