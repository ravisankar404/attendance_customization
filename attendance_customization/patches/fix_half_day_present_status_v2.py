"""
Patch: fix_half_day_present_status_v2

WHY THIS EXISTS:
    fix_half_day_present_status (v1) was a one-time patch that ran on an
    earlier deployment. Frappe never re-runs an already-executed patch.

    Records created AFTER v1 ran but BEFORE the _link_checkins() code fix
    was deployed (e.g. Indu Priya M, 29-04-2026) were left broken — they
    have leave_application + in_time + out_time set but half_day_status is
    still 'Absent' or NULL.

    This v2 runs the identical SQL again under a new patch name so Frappe
    treats it as a fresh patch and executes it on the next bench migrate.

ROOT CAUSE (same as v1):
    When mark_attendance (HRMS) runs BEFORE the manager approves the
    half-day leave, it creates a 'Present' attendance and links the
    Employee Checkins. Later, HRMS flips status to 'Half Day' via db_set()
    — bypassing validate() — so half_day_status is never set to 'Present'.

    The _link_checkins() code fix (deployed alongside this patch) now
    handles this at approval time for all future records. This patch cleans
    up any records that fell into the gap between v1 and the code fix.

SAFE TO RUN:
    Fully idempotent — already-correct records (half_day_status = 'Present')
    are excluded by the WHERE clause.
"""

import frappe


def execute():
    affected = frappe.db.sql("""
        SELECT name, employee, attendance_date
          FROM `tabAttendance`
         WHERE status            = 'Half Day'
           AND docstatus         = 1
           AND leave_application IS NOT NULL
           AND leave_application != ''
           AND in_time           IS NOT NULL
           AND out_time          IS NOT NULL
           AND (half_day_status IS NULL
                OR half_day_status = ''
                OR half_day_status != 'Present')
    """, as_dict=True)

    if not affected:
        frappe.logger().info("fix_half_day_present_status_v2: no records to fix.")
        return

    names = [r.name for r in affected]

    frappe.db.sql("""
        UPDATE `tabAttendance`
           SET half_day_status = 'Present',
               modified        = NOW()
         WHERE name IN %(names)s
    """, {"names": names})

    frappe.db.commit()

    frappe.logger().info(
        "fix_half_day_present_status_v2: fixed {} record(s) → "
        "half_day_status = 'Present'. Employees: {}".format(
            len(names),
            ", ".join(set(r.employee for r in affected))
        )
    )
    print("fix_half_day_present_status_v2: fixed {} record(s).".format(len(names)))
