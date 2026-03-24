"""
Patch: fix_half_day_leave_attendance

Fixes attendance records for approved half-day leave applications so that
the Monthly Attendance Sheet shows HD/L or HD/A correctly, and payroll
calculates salary deductions accurately.

ROOT CAUSE:
    The old code created attendance via Attendance Request (not Leave
    Application). The attendance record had attendance_request set but NOT
    leave_application. The Monthly Attendance Sheet checks leave_application
    to decide HD/L vs HD/A — so those records showed HD/A, causing incorrect
    salary deductions even for employees who did come to work.

WHAT THIS PATCH DOES:
    For every approved half-day Leave Application it resolves the attendance
    for half_day_date into one of these outcomes:

    ┌──────────────────────────────────────────────────────────────────────┐
    │  Employee had checkins on that date (came for working half):         │
    │    → Attendance: Half Day + leave_application → HD/L                 │
    │    → Monthly Sheet: HD/L  Payroll: 0.5 leave consumed, full pay ✓   │
    ├──────────────────────────────────────────────────────────────────────┤
    │  Employee had NO checkins (missed the working half too):             │
    │    → Attendance: Half Day + NO leave_application → HD/A              │
    │    → Monthly Sheet: HD/A  Payroll: 0.5 deduction + 0.5 leave ✓      │
    └──────────────────────────────────────────────────────────────────────┘

PERFORMANCE:
    Uses direct frappe.db operations (set_value, sql INSERT) instead of
    full document lifecycle (insert+submit) to avoid triggering HRMS hooks,
    leave ledger recalculation, and validators on every record.
    This makes the patch run in seconds instead of minutes.

SAFE TO RUN:
    - Multiple times (fully idempotent).
"""

import frappe
from frappe.utils import getdate, now


def execute():
    leave_apps = frappe.get_all(
        "Leave Application",
        filters={
            "half_day": 1,
            "status": "Approved",
            "docstatus": 1,
        },
        fields=["name", "employee", "half_day_date", "leave_type", "company"],
    )

    if not leave_apps:
        frappe.logger().info("fix_half_day_leave_attendance: no approved half-day leaves found.")
        return

    created = 0
    updated = 0
    skipped = 0

    for la in leave_apps:
        employee = la.employee

        if not la.half_day_date:
            frappe.logger().warning(
                "fix_half_day_leave_attendance: skipping leave {} — half_day_date is empty".format(la.name)
            )
            skipped += 1
            continue

        half_day_date = getdate(la.half_day_date)

        # Check if employee came for their working half (determines HD/L vs HD/A).
        has_checkins = bool(frappe.db.sql("""
            SELECT name FROM `tabEmployee Checkin`
            WHERE employee = %s
            AND DATE(time) = %s
            LIMIT 1
        """, (employee, half_day_date)))

        # Look for a non-cancelled attendance on that date.
        attendance = frappe.db.get_value(
            "Attendance",
            {
                "employee": employee,
                "attendance_date": half_day_date,
                "docstatus": ("!=", 2),
            },
            ["name", "status", "leave_application", "docstatus"],
            as_dict=True,
        )

        if attendance and attendance.status == "Half Day":
            # Already correct — skip.
            if attendance.leave_application == la.name and has_checkins:
                skipped += 1
                continue

            # No checkins → keep HD/A.
            if not has_checkins and not attendance.leave_application:
                skipped += 1
                continue

            # Had checkins but leave_application not linked → set it (HD/A → HD/L).
            if has_checkins and not attendance.leave_application:
                frappe.db.set_value(
                    "Attendance", attendance.name, "leave_application", la.name
                )
                updated += 1
                continue

            # Already has leave_application set → skip.
            if attendance.leave_application:
                skipped += 1
                continue

        elif attendance:
            # Wrong status (e.g. "Present") → cancel via direct db (skip hooks).
            if attendance.docstatus == 1:
                try:
                    frappe.db.set_value(
                        "Attendance", attendance.name, "docstatus", 2,
                        update_modified=False
                    )
                except Exception:
                    frappe.log_error(
                        message=frappe.get_traceback(),
                        title="fix_half_day_leave_attendance: could not cancel "
                              "attendance {} for leave {}".format(attendance.name, la.name),
                    )
                    skipped += 1
                    continue

            elif attendance.docstatus == 0:
                try:
                    frappe.db.delete("Attendance", {"name": attendance.name})
                except Exception:
                    frappe.log_error(
                        message=frappe.get_traceback(),
                        title="fix_half_day_leave_attendance: could not delete "
                              "draft attendance {} for leave {}".format(attendance.name, la.name),
                    )
                    skipped += 1
                    continue

        # No valid attendance — create one directly via SQL (fast, no hooks).
        company = la.company or frappe.db.get_value("Employee", employee, "company")
        employee_name = frappe.db.get_value("Employee", employee, "employee_name") or ""
        leave_application_link = la.name if has_checkins else ""

        try:
            att_name = frappe.generate_hash(length=10)
            frappe.db.sql("""
                INSERT INTO `tabAttendance`
                    (name, employee, employee_name, attendance_date, status,
                     leave_type, leave_application, company,
                     docstatus, creation, modified, modified_by, owner)
                VALUES
                    (%s, %s, %s, %s, 'Half Day',
                     %s, %s, %s,
                     1, %s, %s, 'Administrator', 'Administrator')
            """, (
                att_name, employee, employee_name, half_day_date,
                la.leave_type, leave_application_link, company,
                now(), now(),
            ))
            created += 1
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="fix_half_day_leave_attendance: could not create attendance "
                      "for leave {} employee {} date {}".format(la.name, employee, half_day_date),
            )
            skipped += 1

    frappe.db.commit()

    frappe.logger().info(
        "fix_half_day_leave_attendance complete: "
        "created={}, updated={}, skipped={}".format(created, updated, skipped)
    )
    print(
        "fix_half_day_leave_attendance: created={}, updated={}, skipped={}".format(
            created, updated, skipped
        )
    )
