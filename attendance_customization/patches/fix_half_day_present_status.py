import frappe


def execute():
    """
    One-time patch to fix Half Day attendance records where:
      - leave_application IS linked  (approved half-day leave exists)
      - in_time AND out_time are both set  (employee physically worked the other half)
      - half_day_status is NOT 'Present'  (NULL or 'Absent' — wrong)

    ROOT CAUSE:
        When mark_attendance (HRMS) runs BEFORE the manager approves the half-day
        leave, it creates a 'Present' attendance and links the Employee Checkins
        (sets checkin.attendance). Later, when the leave is approved, HRMS flips
        the attendance to 'Half Day' via db_set() — bypassing validate(), so
        half_day_status is never set.

        Our _link_checkins() in leave_application.py then queries for unlinked
        checkins, finds none (already linked by mark_attendance), and exits early
        without setting half_day_status.

        Result: attendance has leave_application + in_time + out_time but
        half_day_status = NULL/Absent → Monthly Sheet shows HD/A incorrectly.

    FIX:
        Set half_day_status = 'Present' for all such records.
        The code fix in leave_application._link_checkins() prevents recurrence
        for all future leave approvals.
    """
    affected = frappe.db.sql("""
        SELECT name, employee, attendance_date
        FROM `tabAttendance`
        WHERE status = 'Half Day'
          AND docstatus = 1
          AND leave_application IS NOT NULL
          AND leave_application != ''
          AND in_time IS NOT NULL
          AND out_time IS NOT NULL
          AND (half_day_status IS NULL OR half_day_status = '' OR half_day_status != 'Present')
    """, as_dict=True)

    if not affected:
        frappe.logger().info("fix_half_day_present_status: no records to fix.")
        return

    names = [r.name for r in affected]

    frappe.db.sql("""
        UPDATE `tabAttendance`
        SET half_day_status = 'Present', modified = NOW()
        WHERE name IN %(names)s
    """, {"names": names})

    frappe.db.commit()

    frappe.logger().info(
        "fix_half_day_present_status: fixed {} attendance record(s) → "
        "half_day_status set to 'Present'. Records: {}".format(
            len(names), ", ".join(names)
        )
    )
    print("✅ Fixed {} Half Day attendance records.".format(len(names)))
