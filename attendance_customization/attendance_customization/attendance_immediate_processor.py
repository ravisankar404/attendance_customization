# Immediate processor for attendance late penalties

import frappe
from frappe.utils import getdate, get_first_day, today
import calendar


def on_attendance_validate(doc, method):
    """
    On validate: Set late strike count based on current late entries.
    This shows the running count of late entries.
    """
    # Debug log
    frappe.log_error(f"Validate called for {doc.name}, Late Entry: {doc.late_entry}", "Attendance Validate Debug")
    
    # Get policy settings
    try:
        policy = frappe.get_single("Attendance Policy Settings")
        if not policy.enable_late_penalty:
            # If policy is disabled, set count to 0
            doc.late_strike_count = 0
            return
    except Exception as e:
        frappe.log_error(f"Error getting policy: {str(e)}", "Policy Error")
        doc.late_strike_count = 0
        return
    
    # Only count if late entry is checked
    if not doc.late_entry:
        doc.late_strike_count = 0
        return
    
    # Get the count of late entries for this employee in current month
    month_start = get_first_day(doc.attendance_date)
    
    # Build filters for counting
    filters = {
        "employee": doc.employee,
        "attendance_date": ["between", [month_start, doc.attendance_date]],
        "late_entry": 1,
        "docstatus": ["!=", 2]  # Exclude cancelled
    }
    
    # If updating existing record, check if we need to exclude it
    if not doc.is_new() and doc.name and doc.name != "New Attendance":
        # Get the original document to see if late_entry changed
        try:
            original = frappe.db.get_value("Attendance", doc.name, "late_entry")
            if original and not doc.late_entry:
                # Late entry is being unchecked, exclude this record from count
                filters["name"] = ["!=", doc.name]
        except:
            pass
    
    # Count late entries
    late_count = 0
    try:
        late_count = frappe.db.count("Attendance", filters)
        
        # If this is a new late entry, add 1
        if doc.late_entry and (doc.is_new() or doc.name == "New Attendance"):
            late_count += 1
    except Exception as e:
        frappe.log_error(f"Error counting late entries: {str(e)}", "Count Error")
    
    # Set the count
    doc.late_strike_count = late_count
    
    
    # Debug log
    frappe.log_error(
        f"Employee: {doc.employee}, Date: {doc.attendance_date}, Late Count: {late_count}, Is Late: {doc.late_entry}, Doc Name: {doc.name}",
        "Late Strike Count Debug"
    )


def on_attendance_submit(doc, method):
    """
    On submit: Check if penalty should be applied based on policy.
    """
    # Only process if late entry
    if not doc.late_entry:
        return
    
    # Get policy settings
    try:
        policy = frappe.get_single("Attendance Policy Settings")
        if not policy.enable_late_penalty:
            return
    except Exception as e:
        frappe.log_error(f"Error fetching policy: {str(e)}", "Attendance Submit")
        return
    
    # Check based on counting mode
    if policy.counting_mode == "Cumulative":
        check_cumulative_penalty(doc, policy)
    elif policy.counting_mode == "Strictly Consecutive":
        check_consecutive_penalty(doc, policy)


def check_cumulative_penalty(doc, policy):
    """Check and apply penalty for cumulative mode."""
    
    month_start = get_first_day(doc.attendance_date)
    
    # Count total late entries including current
    late_count = frappe.db.count("Attendance", {
        "employee": doc.employee,
        "attendance_date": ["between", [month_start, doc.attendance_date]],
        "late_entry": 1,
        "docstatus": 1
    })
    
    frappe.log_error(
        f"Cumulative Check - Employee: {doc.employee}, Late Count: {late_count}, Threshold: {policy.strike_threshold}",
        "Cumulative Penalty Check"
    )
    
    # Apply penalty if count exceeds threshold
    if late_count > policy.strike_threshold:
        apply_penalty_to_doc(doc, policy, late_count)


def check_consecutive_penalty(doc, policy):
    """Check and apply penalty for consecutive mode."""
    
    month_start = get_first_day(doc.attendance_date)
    
    # Get all attendance records to check consecutive pattern
    all_attendances = frappe.get_all(
        "Attendance",
        filters={
            "employee": doc.employee,
            "attendance_date": ["between", [month_start, doc.attendance_date]],
            "docstatus": 1,
            "status": ["in", ["Present", "Half Day", "Work From Home"]]
        },
        fields=["name", "attendance_date", "late_entry"],
        order_by="attendance_date desc"
    )
    
    # Count consecutive late entries backwards from current date
    consecutive_count = 0
    for att in all_attendances:
        if att.late_entry:
            consecutive_count += 1
        else:
            break
    
    frappe.log_error(
        f"Consecutive Check - Employee: {doc.employee}, Consecutive Count: {consecutive_count}, Threshold: {policy.strike_threshold}",
        "Consecutive Penalty Check"
    )
    
    # Apply penalty if consecutive count exceeds threshold
    if consecutive_count > policy.strike_threshold:
        apply_penalty_to_doc(doc, policy, consecutive_count)


        


def apply_penalty_to_doc(doc, policy, strike_count):
    """Apply penalty to the attendance document."""
    
    # First, ensure custom fields exist
    ensure_attendance_fields()
    
    # Skip if penalty already applied (check if field exists first)
    if hasattr(doc, 'custom_late_penalty_applied') and doc.custom_late_penalty_applied:
        return
    
    # Cancel the submitted doc
    doc.cancel()
    
    # Create new doc with penalty
    new_doc = frappe.copy_doc(doc)
    
    # Store original status
    original_status = new_doc.status
    
    # Apply penalty based on policy
    if policy.penalty_action == "Half-day":
        new_doc.status = "Half Day"
    elif policy.penalty_action == "Full-day":
        new_doc.status = "Absent"
    
    # Set penalty flag (check if field exists)
    if hasattr(new_doc, 'custom_late_penalty_applied'):
        new_doc.custom_late_penalty_applied = 1
    
    # Add remark
    attendance_date = getdate(new_doc.attendance_date)
    month_name = calendar.month_name[attendance_date.month]
    year = attendance_date.year
    
    def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"
    
    remark = f"{get_ordinal(strike_count)} late arrival in {month_name} {year} - "
    if policy.counting_mode == "Cumulative":
        remark += f"Cumulative penalty applied (Threshold: {policy.strike_threshold})"
    else:
        remark += f"Consecutive penalty applied (Threshold: {policy.strike_threshold})"
    
    # Set the remark field (check which field exists)
    if hasattr(new_doc, 'late_incident_remark'):
        new_doc.late_incident_remark = remark
    elif hasattr(new_doc, 'custom_remarks'):
        new_doc.custom_remarks = remark
    
    # Set original status if field exists
    if hasattr(new_doc, 'custom_original_status'):
        new_doc.custom_original_status = original_status
    
    # Insert and submit
    new_doc.insert()
    new_doc.submit()
    
    # Log the action
    frappe.log_error(
        f"Penalty applied to {doc.employee} for {doc.attendance_date}. Changed from {original_status} to {new_doc.status}",
        "Late Penalty Applied"
    )
    
    # Show message to user
    frappe.msgprint(
        f"""<b>Late Penalty Applied!</b><br><br>
        Employee: {doc.employee_name}<br>
        Date: {doc.attendance_date}<br>
        Late Strike #{strike_count}<br>
        Status changed from <b>{original_status}</b> to <b>{new_doc.status}</b><br><br>
        <i>{remark}</i>""",
        title="Automatic Late Penalty Applied",
        indicator="red"
    )


def ensure_attendance_fields():
    """Ensure required custom fields exist in Attendance."""
    try:
        from attendance_customization.attendance_customization.custom_fields.attendance_custom_fields import create_custom_fields
        create_custom_fields()
    except Exception as e:
        frappe.log_error(f"Error ensuring custom fields: {str(e)}", "Field Creation Error")

        
# Utility functions
@frappe.whitelist()
def get_employee_late_status(employee, date=None):
    """Get current late status for an employee."""
    if not date:
        date = today()
    
    # Get policy
    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return {
            "enabled": False,
            "message": "Late penalty is disabled"
        }
    
    month_start = get_first_day(getdate(date))
    
    # Get late count
    late_count = frappe.db.count("Attendance", {
        "employee": employee,
        "attendance_date": ["between", [month_start, date]],
        "late_entry": 1,
        "docstatus": 1
    })
    
    # For consecutive mode, get consecutive count
    consecutive_count = 0
    if policy.counting_mode == "Strictly Consecutive":
        attendances = frappe.get_all(
            "Attendance",
            filters={
                "employee": employee,
                "attendance_date": ["<=", date],
                "attendance_date": [">=", month_start],
                "docstatus": 1
            },
            fields=["late_entry"],
            order_by="attendance_date desc"
        )
        
        for att in attendances:
            if att.late_entry:
                consecutive_count += 1
            else:
                break
    
    return {
        "enabled": True,
        "late_count": late_count,
        "consecutive_count": consecutive_count,
        "threshold": policy.strike_threshold,
        "counting_mode": policy.counting_mode,
        "next_will_trigger": (
            consecutive_count == policy.strike_threshold if policy.counting_mode == "Strictly Consecutive"
            else late_count == policy.strike_threshold
        )
    }


@frappe.whitelist()
def check_and_fix_missing_penalties():
    """Utility to check and fix any missing penalties."""
    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return "Policy is disabled"
    
    # This would check all employees and apply missing penalties
    # Useful for fixing data after enabling the policy
    pass

@frappe.whitelist()
def get_employee_late_count(employee, date, exclude_current=None):
    """Get late count for an employee up to a specific date."""
    if not employee or not date:
        return {"count": 0}
    
    month_start = get_first_day(getdate(date))
    
    filters = {
        "employee": employee,
        "attendance_date": ["between", [month_start, date]],
        "late_entry": 1,
        "docstatus": ["!=", 2]
    }
    
    if exclude_current:
        filters["name"] = ["!=", exclude_current]
    
    count = frappe.db.count("Attendance", filters)
    
    return {"count": count}