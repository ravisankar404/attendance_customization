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

    Per-record cases:

    Case A — attendance exists, "Half Day", leave_application empty, employee
              had checkins → set leave_application (HD/A → HD/L).

    Case B — attendance exists, "Half Day", leave_application empty, employee
              had no checkins → leave as HD/A (correct: absent for working half).

    Case C — attendance exists, "Half Day", leave_application already correct
              → skip (idempotent).

    Case D — no attendance exists (e.g. all attendance deleted before patch)
              → create and submit new attendance, with or without
              leave_application based on checkins.

    Case E — attendance exists with wrong status (e.g. "Present" created by
              ProcessAttendance before this patch) → cancel wrong record,
              then fall through to Case D.

SAFE TO RUN:
    - Multiple times (fully idempotent).
    - Run BEFORE ProcessAttendance when rebuilding from scratch — ProcessAttendance
      will skip half-day dates that already have a submitted attendance.
"""

import frappe
from frappe.utils import getdate


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

        # Guard: skip if half_day_date is missing (data corruption).
        # getdate(None) returns today which would create wrong attendance.
        if not la.half_day_date:
            frappe.logger().warning(
                "fix_half_day_leave_attendance: skipping leave {} — half_day_date is empty".format(la.name)
            )
            skipped += 1
            continue

        half_day_date = getdate(la.half_day_date)

        # Determine whether the employee came for their working half.
        # This drives whether leave_application is linked (HD/L) or not (HD/A).
        has_checkins = bool(frappe.get_all(
            "Employee Checkin",
            filters=[
                ["employee", "=", employee],
                ["time", "between", [
                    "{} 00:00:00".format(half_day_date),
                    "{} 23:59:59".format(half_day_date),
                ]],
            ],
            fields=["name"],
            limit=1,
        ))

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
            # Case C: already correct — skip.
            if attendance.leave_application == la.name and has_checkins:
                skipped += 1
                continue

            # Case B: no checkins → employee missed working half → keep HD/A.
            if not has_checkins and not attendance.leave_application:
                skipped += 1
                continue

            # Case A: had checkins but leave_application not linked → set it.
            if has_checkins and not attendance.leave_application:
                frappe.db.set_value(
                    "Attendance", attendance.name, "leave_application", la.name
                )
                updated += 1
                continue

            # Already has leave_application set → skip (handles re-runs).
            if attendance.leave_application:
                skipped += 1
                continue

        elif attendance:
            # Case E: Wrong status (e.g. "Present"). Cancel and recreate.
            if attendance.docstatus == 1:
                try:
                    wrong_doc = frappe.get_doc("Attendance", attendance.name)
                    wrong_doc.flags.ignore_permissions = True
                    wrong_doc.cancel()
                except Exception:
                    frappe.log_error(
                        message=frappe.get_traceback(),
                        title="fix_half_day_leave_attendance: could not cancel "
                              "attendance {} for leave {}".format(attendance.name, la.name),
                    )
                    skipped += 1
                    continue

            elif attendance.docstatus == 0:
                # Draft with wrong status — delete it.
                try:
                    frappe.delete_doc(
                        "Attendance", attendance.name, ignore_permissions=True
                    )
                except Exception:
                    frappe.log_error(
                        message=frappe.get_traceback(),
                        title="fix_half_day_leave_attendance: could not delete "
                              "draft attendance {} for leave {}".format(attendance.name, la.name),
                    )
                    skipped += 1
                    continue

        # Case D (or after Case E cancel): no valid attendance exists.
        # Create a fresh Half Day attendance.
        # Only link leave_application if the employee had checkins (HD/L).
        # If no checkins, create without leave_application (HD/A).
        company = la.company or frappe.db.get_value("Employee", employee, "company")
        employee_name = frappe.db.get_value("Employee", employee, "employee_name") or ""

        doc = frappe.new_doc("Attendance")
        doc.employee = employee
        doc.employee_name = employee_name
        doc.attendance_date = half_day_date
        doc.status = "Half Day"
        doc.leave_type = la.leave_type
        doc.company = company
        doc.flags.ignore_permissions = True

        if has_checkins:
            doc.leave_application = la.name

        try:
            doc.insert()
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="fix_half_day_leave_attendance: could not insert attendance "
                      "for leave {} employee {} date {}".format(la.name, employee, half_day_date),
            )
            skipped += 1
            continue

        try:
            doc.submit()
            created += 1
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="fix_half_day_leave_attendance: could not submit attendance "
                      "{} for leave {}".format(doc.name, la.name),
            )
            # Clean up the orphan draft so it does not linger.
            try:
                frappe.delete_doc("Attendance", doc.name, ignore_permissions=True)
            except Exception:
                pass
            skipped += 1

    frappe.logger().info(
        "fix_half_day_leave_attendance complete: "
        "created={}, updated={}, skipped={}".format(created, updated, skipped)
    )
    print(
        "fix_half_day_leave_attendance: created={}, updated={}, skipped={}".format(
            created, updated, skipped
        )
    )
