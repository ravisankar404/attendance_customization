import frappe
from frappe.utils import getdate, get_first_day, get_last_day, add_days, today
import calendar


# ─────────────────────────────────────────────────────────────────
# Holiday helpers
# ─────────────────────────────────────────────────────────────────

def get_employee_holiday_dates(employee, month_start, month_end):
    """Return a set of holiday dates (datetime.date) for the employee in the range.

    Resolution order:
      1. Employee's own holiday_list
      2. Company's default_holiday_list
      3. Empty set (logs a warning so ops can fix missing config)
    """
    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")

    if not holiday_list:
        company = frappe.db.get_value("Employee", employee, "company")
        holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")

    if not holiday_list:
        frappe.logger().warning(
            f"Late Strike Processor: no holiday list found for employee {employee} "
            f"(and no company default). Holiday skipping is disabled for this employee."
        )
        return set()

    holidays = frappe.db.get_all(
        "Holiday",
        filters={
            "parent": holiday_list,
            "holiday_date": ["between", [month_start, month_end]],
        },
        pluck="holiday_date",
    )
    return {getdate(d) for d in holidays}


# ─────────────────────────────────────────────────────────────────
# Scheduled entry point
# ─────────────────────────────────────────────────────────────────

def daily_late_strike_processor():
    """Daily scheduled task (2 AM) to process late attendance penalties."""

    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return

    employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")

    for employee in employees:
        try:
            process_employee_penalties(employee, policy)
        except Exception:
            # Log and continue — one bad employee must not block the rest.
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Late Strike Processor: failed for employee {employee}",
            )

    frappe.db.commit()


# ─────────────────────────────────────────────────────────────────
# Per-employee orchestration
# ─────────────────────────────────────────────────────────────────

def process_employee_penalties(employee, policy):
    """Process late penalties for one employee, month by month."""

    if not policy.apply_from_date:
        frappe.log_error(
            message="apply_from_date is not set on Attendance Policy Settings.",
            title="Late Strike Processor: missing apply_from_date",
        )
        return

    policy_start = getdate(policy.apply_from_date)
    today_date   = getdate(today())

    current_date = policy_start
    while current_date <= today_date:
        month_start = get_first_day(current_date)
        month_end   = get_last_day(current_date)

        # Respect apply_from_date: never process attendance before that date,
        # even if it falls in the same calendar month.
        effective_start = max(month_start, policy_start)

        attendances = frappe.db.sql("""
            SELECT name, attendance_date, status, late_entry, custom_late_penalty_applied
            FROM `tabAttendance`
            WHERE employee = %s
              AND attendance_date BETWEEN %s AND %s
              AND docstatus = 1
              AND status IN ('Present', 'Half Day', 'Work From Home')
              AND NOT (
                  status = 'Half Day'
                  AND leave_application IS NOT NULL
                  AND leave_application != ''
              )
            ORDER BY attendance_date
        """, (employee, effective_start, month_end), as_dict=True)

        holiday_dates = get_employee_holiday_dates(employee, effective_start, month_end)

        if policy.counting_mode == "Cumulative":
            apply_cumulative_penalties(attendances, policy, holiday_dates)
        elif policy.counting_mode == "Strictly Consecutive":
            apply_consecutive_penalties(attendances, policy, holiday_dates)
        elif policy.counting_mode == "Cumulative with Reset":
            apply_cumulative_with_reset_penalties(attendances, policy, holiday_dates)

        current_date = add_days(month_end, 1)


# ─────────────────────────────────────────────────────────────────
# Counting modes
# ─────────────────────────────────────────────────────────────────

def apply_cumulative_penalties(attendances, policy, holiday_dates):
    """All lates in the month accumulate; every late beyond the threshold is penalized."""

    late_count = 0
    for att in attendances:
        att_date = getdate(att.attendance_date)

        if att_date in holiday_dates:
            continue

        # Already-penalized record: count it in the running total (the strike
        # that triggered this penalty DID consume a slot) but don't re-penalize.
        if att.get("custom_late_penalty_applied"):
            late_count += 1
            continue

        if att.late_entry:
            late_count += 1
            frappe.db.set_value("Attendance", att.name,
                                "late_strike_count", late_count, update_modified=False)

            if late_count > policy.strike_threshold:
                apply_penalty_to_attendance(att.name, policy, late_count, att_date)


def apply_consecutive_penalties(attendances, policy, holiday_dates):
    """Only back-to-back late days count; any on-time day resets the streak to zero."""

    consecutive_count = 0
    for att in attendances:
        att_date = getdate(att.attendance_date)

        # Holidays are neutral: they don't break the streak and don't count toward it.
        if att_date in holiday_dates:
            continue

        # Already-penalized record: treat as a late day for streak continuity
        # (it was late — that's why it was penalized) but don't re-penalize.
        if att.get("custom_late_penalty_applied"):
            consecutive_count += 1
            continue

        if att.late_entry:
            consecutive_count += 1
            frappe.db.set_value("Attendance", att.name,
                                "late_strike_count", consecutive_count, update_modified=False)

            if consecutive_count > policy.strike_threshold:
                apply_penalty_to_attendance(att.name, policy, consecutive_count, att_date)
        else:
            consecutive_count = 0


def apply_cumulative_with_reset_penalties(attendances, policy, holiday_dates):
    """Cumulative count, but resets to zero after each penalty is applied."""

    late_count = 0
    for att in attendances:
        att_date = getdate(att.attendance_date)

        # Holidays are neutral — skip without touching the running count.
        if att_date in holiday_dates:
            continue

        # Already-penalized record: this was the record that triggered a reset.
        # Reset our counter so we pick up where the penalty left off.
        if att.get("custom_late_penalty_applied"):
            late_count = 0
            continue

        if att.late_entry:
            late_count += 1
            frappe.db.set_value("Attendance", att.name,
                                "late_strike_count", late_count, update_modified=False)

            if late_count > policy.strike_threshold:
                apply_penalty_to_attendance(att.name, policy, late_count, att_date)
                late_count = 0


# ─────────────────────────────────────────────────────────────────
# Penalty application
# ─────────────────────────────────────────────────────────────────

def apply_penalty_to_attendance(attendance_name, policy, strike_count, attendance_date):
    """Cancel the existing attendance and replace it with a penalized copy.

    attendance_date must be a datetime.date object (not a string).
    Uses a savepoint so a failed insert does not leave a cancelled-but-orphaned record.
    """
    # Ensure we have a date object for calendar lookups.
    attendance_date = getdate(attendance_date)

    try:
        old_doc = frappe.get_doc("Attendance", attendance_name)

        if old_doc.custom_late_penalty_applied:
            return  # already penalized — nothing to do

        original_status = old_doc.status

        # Use a savepoint so we can roll back the cancel if insert fails.
        frappe.db.savepoint("penalty_apply")

        old_doc.cancel()

        new_doc = frappe.copy_doc(old_doc)

        # frappe.copy_doc clears: name, owner, creation, modified, modified_by,
        # docstatus, amended_from, amendment_date.
        # It does NOT clear no_copy fields when ignore_no_copy=True (default).
        # Attendance has no_copy on: naming_series, status, leave_application,
        # amended_from — so leave_application IS copied and must be cleared manually.
        # Also clear related fields that belong to the original context, not the penalty.
        new_doc.name                        = None
        new_doc.docstatus                   = 0
        new_doc.amended_from               = None

        # --- penalty status ---
        new_doc.status                      = "Half Day" if policy.penalty_action == "Half-day" else "Absent"

        # When penalty produces Half Day, half_day_status must be set explicitly.
        # Absent penalties don't use half_day_status — clear it to avoid confusion.
        new_doc.half_day_status             = "Absent" if policy.penalty_action == "Half-day" else None

        # --- clear leave / request linkage ---
        # leave_application has no_copy=1 but copy_doc copies it (ignore_no_copy=True).
        # Carrying the leave link forward would make payroll treat this penalty
        # attendance as a leave day instead of an absent/half-day deduction.
        new_doc.leave_application           = None
        new_doc.leave_type                  = None
        new_doc.attendance_request          = None

        # --- penalty flags ---
        new_doc.custom_late_penalty_applied = 1
        new_doc.custom_original_status      = original_status
        new_doc.late_strike_count           = strike_count
        new_doc.strike_processed            = 0   # reset so scheduler doesn't skip it

        month_name = calendar.month_name[attendance_date.month]
        year       = attendance_date.year
        reset_note = " (Count reset to 0)" if policy.counting_mode == "Cumulative with Reset" else ""
        new_doc.late_incident_remark = (
            f"Strike #{strike_count} in {month_name} {year} "
            f"- {policy.penalty_action} penalty applied{reset_note}"
        )

        new_doc.insert()
        new_doc.submit()

        frappe.db.release_savepoint("penalty_apply")

    except Exception:
        frappe.db.rollback(save_point="penalty_apply")
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"Late Strike Processor: failed to apply penalty on {attendance_name}",
        )


# ─────────────────────────────────────────────────────────────────
# Manual reprocessing
# ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def reprocess_attendance_from_date(from_date=None, employee=None):
    """Manually reprocess late penalties from a given date.

    Args:
        from_date: ISO date string (required).
        employee:  Employee ID to reprocess only one person (optional).
                   When omitted, all active employees are reprocessed.

    The policy's apply_from_date is NOT mutated — reprocessing is a one-off
    operation and should not permanently alter global config.
    """
    if not from_date:
        frappe.throw("Please provide a from_date")

    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return "Late penalty is disabled in Attendance Policy Settings."

    clear_penalties_from_date(from_date, employee=employee)

    if employee:
        employees = [employee]
    else:
        employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")

    for emp in employees:
        try:
            process_employee_penalties(emp, policy)
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Late Strike Processor (reprocess): failed for employee {emp}",
            )

    frappe.db.commit()

    filters = {"attendance_date": [">=", from_date], "custom_late_penalty_applied": 1, "docstatus": 1}
    if employee:
        filters["employee"] = employee

    penalty_count = frappe.db.count("Attendance", filters)
    scope = f"employee {employee}" if employee else "all employees"
    return f"Reprocessing complete for {scope}. {penalty_count} penalized records now exist from {from_date}."


# ─────────────────────────────────────────────────────────────────
# Penalty clearing (used by reprocess)
# ─────────────────────────────────────────────────────────────────

def clear_penalties_from_date(from_date, employee=None):
    """Cancel all penalty attendances from from_date and restore original status.

    Args:
        from_date: ISO date string.
        employee:  When provided, only clears that employee's penalties.
    """
    conditions = "attendance_date >= %s AND custom_late_penalty_applied = 1 AND docstatus = 1"
    params     = [from_date]

    if employee:
        conditions += " AND employee = %s"
        params.append(employee)

    penalty_attendances = frappe.db.sql(
        f"SELECT name, custom_original_status FROM `tabAttendance` WHERE {conditions}",
        params,
        as_dict=True,
    )

    for att in penalty_attendances:
        try:
            frappe.db.savepoint("clear_penalty")

            doc = frappe.get_doc("Attendance", att.name)
            doc.cancel()

            new_doc                             = frappe.copy_doc(doc)
            new_doc.name                        = None
            new_doc.docstatus                   = 0
            new_doc.amended_from               = None
            new_doc.status                      = att.custom_original_status or "Present"
            # Clear penalty flags
            new_doc.custom_late_penalty_applied = 0
            new_doc.custom_original_status      = None
            new_doc.late_incident_remark        = None
            new_doc.late_strike_count           = 0
            new_doc.strike_processed            = 0
            # leave_application was cleared when penalty was applied, so the
            # cancelled penalty doc has it as None — copy_doc carries that None
            # forward correctly. No action needed here.

            new_doc.insert()
            new_doc.submit()

            frappe.db.release_savepoint("clear_penalty")

        except Exception:
            frappe.db.rollback(save_point="clear_penalty")
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Late Strike Processor: failed to clear penalty for {att.name}",
            )

    frappe.db.commit()
