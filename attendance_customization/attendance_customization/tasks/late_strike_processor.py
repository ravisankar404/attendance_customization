import frappe
from frappe.utils import getdate, get_first_day, get_last_day, add_days, today
import calendar

def daily_late_strike_processor():
    """Daily scheduled task to process late attendance penalties."""
    
    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return
    
    # Get all employees
    employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
    
    for employee in employees:
        process_employee_penalties(employee, policy)
    
    frappe.db.commit()


def process_employee_penalties(employee, policy):
    """Process penalties for an employee based on policy."""
    
    # Get apply from date
    start_date = getdate(policy.apply_from_date) if hasattr(policy, 'apply_from_date') and policy.apply_from_date else get_first_day(today())
    
    # Process month by month
    current_date = start_date
    while current_date <= getdate(today()):
        month_start = get_first_day(current_date)
        month_end = get_last_day(current_date)
        
        # Get all attendance for this month
        attendances = frappe.db.sql("""
            SELECT name, attendance_date, status, late_entry, custom_late_penalty_applied
            FROM `tabAttendance`
            WHERE employee = %s
            AND attendance_date BETWEEN %s AND %s
            AND docstatus = 1
            AND status IN ('Present', 'Half Day', 'Work From Home')
            ORDER BY attendance_date
        """, (employee, month_start, month_end), as_dict=True)
        
        if policy.counting_mode == "Cumulative":
            apply_cumulative_penalties(employee, attendances, policy)
        elif policy.counting_mode == "Strictly Consecutive":
            apply_consecutive_penalties(employee, attendances, policy)
        elif policy.counting_mode == "Cumulative with Reset":
            apply_cumulative_with_reset_penalties(employee, attendances, policy)     
        
        # Move to next month
        current_date = add_days(month_end, 1)


def apply_cumulative_penalties(employee, attendances, policy):
    """Apply penalties based on cumulative late count."""
    
    late_count = 0
    for att in attendances:
        if att.late_entry and not att.get('custom_late_penalty_applied'):
            late_count += 1
            
            # Update strike count
            frappe.db.set_value("Attendance", att.name, 
                              "late_strike_count", late_count, update_modified=False)
            
            if late_count > policy.strike_threshold:
                apply_penalty_to_attendance(att.name, policy, late_count, att.attendance_date)


def apply_consecutive_penalties(employee, attendances, policy):
    """Apply penalties based on consecutive late days."""
    
    consecutive_count = 0
    
    for att in attendances:
        if att.get('custom_late_penalty_applied'):
            continue
            
        if att.late_entry:
            consecutive_count += 1
            
            # Update strike count
            frappe.db.set_value("Attendance", att.name, 
                              "late_strike_count", consecutive_count, update_modified=False)
            
            if consecutive_count > policy.strike_threshold:
                apply_penalty_to_attendance(att.name, policy, consecutive_count, att.attendance_date)
        else:
            # Reset count if not late (and not already a penalty)
            consecutive_count = 0


def apply_cumulative_with_reset_penalties(employee, attendances, policy):
    """Apply penalties based on cumulative count but reset to 0 after penalty."""
    
    late_count = 0
    
    for att in attendances:
        # If this already has a penalty applied, we need to reset our count
        if att.get('custom_late_penalty_applied'):
            late_count = 0
            continue
            
        if att.late_entry:
            late_count += 1
            
            # Update the current late count on this attendance
            frappe.db.set_value("Attendance", att.name, 
                              "late_strike_count", late_count, update_modified=False)
            
            if late_count > policy.strike_threshold:
                # Apply penalty
                apply_penalty_to_attendance(att.name, policy, late_count, 
                                          att.attendance_date)
                # Reset count to 0 after penalty
                late_count = 0


def apply_penalty_to_attendance(attendance_name, policy, strike_count, attendance_date):
    """Apply penalty to a specific attendance."""
    
    try:
        # Get existing attendance
        old_doc = frappe.get_doc("Attendance", attendance_name)
        
        # Skip if already has penalty
        if hasattr(old_doc, 'custom_late_penalty_applied') and old_doc.custom_late_penalty_applied:
            return
        
        # Cancel old attendance
        old_doc.cancel()
        
        # Create new attendance with penalty
        new_doc = frappe.copy_doc(old_doc)
        
        # Apply penalty
        original_status = new_doc.status
        if policy.penalty_action == "Half-day":
            new_doc.status = "Half Day"
        else:
            new_doc.status = "Absent"
        
        # Set custom fields
        if hasattr(new_doc, 'custom_late_penalty_applied'):
            new_doc.custom_late_penalty_applied = 1
        if hasattr(new_doc, 'custom_original_status'):
            new_doc.custom_original_status = original_status
        
        # Update the late_strike_count to the value that triggered the penalty
        new_doc.late_strike_count = strike_count
        
        # Add remark
        month_name = calendar.month_name[attendance_date.month]
        year = attendance_date.year
        
        if policy.counting_mode == "Cumulative with Reset":
            new_doc.late_incident_remark = f"Strike #{strike_count} in {month_name} {year} - {policy.penalty_action} penalty applied (Count reset to 0)"
        else:
            new_doc.late_incident_remark = f"Strike #{strike_count} in {month_name} {year} - {policy.penalty_action} penalty applied"
        
        # Save and submit
        new_doc.insert()
        new_doc.submit()
        
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(f"Error applying penalty: {str(e)}", "Penalty Error")


@frappe.whitelist()
def reprocess_attendance_from_date(from_date=None):
    """Manually reprocess attendance from a specific date."""
    
    if not from_date:
        return "Please provide a from_date"
    
    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return "Late penalty is disabled"
    
    # First, clear all penalties from the reprocess date onwards
    clear_penalties_from_date(from_date)
    
    # Update the apply_from_date
    policy.apply_from_date = from_date
    policy.save()
    
    # Run the processor
    daily_late_strike_processor()
    
    # Count how many penalties were applied
    penalty_count = frappe.db.count("Attendance", {
        "attendance_date": [">=", from_date],
        "custom_late_penalty_applied": 1,
        "docstatus": 1
    })
    
    return f"Reprocessing completed. {penalty_count} penalties applied."


def clear_penalties_from_date(from_date):
    """Clear all penalties from a specific date onwards."""
    
    # Get all attendance records with penalties from the date
    penalty_attendances = frappe.db.sql("""
        SELECT name, custom_original_status
        FROM `tabAttendance`
        WHERE attendance_date >= %s
        AND custom_late_penalty_applied = 1
        AND docstatus = 1
    """, from_date, as_dict=True)
    
    for att in penalty_attendances:
        try:
            # Get the document
            doc = frappe.get_doc("Attendance", att.name)
            
            # Cancel it
            doc.cancel()
            
            # Create new document without penalty
            new_doc = frappe.copy_doc(doc)
            
            # Restore original status
            if att.custom_original_status:
                new_doc.status = att.custom_original_status
            
            # Clear penalty fields
            new_doc.custom_late_penalty_applied = 0
            new_doc.custom_original_status = None
            new_doc.late_incident_remark = None
            
            # Insert and submit
            new_doc.insert()
            new_doc.submit()
            
        except Exception as e:
            frappe.log_error(f"Error clearing penalty for {att.name}: {str(e)}", 
                           "Clear Penalty Error")
    
    frappe.db.commit()