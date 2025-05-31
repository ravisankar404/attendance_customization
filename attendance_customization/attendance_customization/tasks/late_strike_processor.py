# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import getdate, get_first_day, get_last_day, add_days, today
from datetime import datetime, timedelta
import calendar


def daily_late_strike_processor():
    """
    Daily scheduled task to process late attendance strikes and apply penalties.
    Runs daily to check attendance records and apply penalties based on policy settings.
    """
    # Get attendance policy settings
    try:
        policy = frappe.get_single("Attendance Policy Settings")
        if not policy.enable_late_penalty:
            frappe.log_error("Late penalty is disabled in Attendance Policy Settings", "Late Strike Processor")
            return
    except Exception as e:
        frappe.log_error(f"Error fetching Attendance Policy Settings: {str(e)}", "Late Strike Processor")
        return
    
    # Process for all active employees
    employees = frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
    
    for employee in employees:
        try:
            process_employee_late_strikes(employee, policy)
        except Exception as e:
            frappe.log_error(
                f"Error processing late strikes for employee {employee}: {str(e)}", 
                "Late Strike Processor"
            )
    
    frappe.db.commit()


def process_employee_late_strikes(employee, policy):
    """Process late strikes for a single employee based on the counting mode."""
    
    # Get current date info
    current_date = getdate(today())
    month_start = get_first_day(current_date)
    yesterday = add_days(current_date, -1)
    
    # Skip if we're on the first day of the month
    if current_date == month_start:
        return
    
    if policy.counting_mode == "Cumulative":
        process_cumulative_strikes(employee, policy, month_start, yesterday)
    elif policy.counting_mode == "Strictly Consecutive":
        process_consecutive_strikes(employee, policy, month_start, yesterday)


def process_cumulative_strikes(employee, policy, start_date, end_date):
    """Process cumulative late strikes - total count in the period."""
    
    # Get all late attendances in the period
    late_attendances = get_late_attendances(employee, start_date, end_date)
    
    # Count unique late days (multiple late punches on same day count as one)
    late_dates = list(set([att['attendance_date'] for att in late_attendances]))
    late_count = len(late_dates)
    
    # Check if penalty threshold is reached
    if late_count >= policy.strike_threshold:
        # Find the attendance record for the threshold day
        late_dates.sort()
        threshold_date = late_dates[policy.strike_threshold - 1]
        
        # Get the attendance record for that date
        attendance_name = frappe.db.get_value(
            "Attendance",
            {
                "employee": employee,
                "attendance_date": threshold_date,
                "docstatus": 1
            },
            "name"
        )
        
        if attendance_name:
            apply_penalty(attendance_name, policy, late_count, threshold_date)


def process_consecutive_strikes(employee, policy, start_date, end_date):
    """Process strictly consecutive late strikes."""
    
    # Get all attendance records in the period (including non-late)
    all_attendances = frappe.get_all(
        "Attendance",
        filters={
            "employee": employee,
            "attendance_date": ["between", [start_date, end_date]],
            "docstatus": 1,
            "status": ["in", ["Present", "Half Day"]]  # Only working days
        },
        fields=["name", "attendance_date", "late_entry", "status", "leave_type"],
        order_by="attendance_date"
    )
    
    consecutive_count = 0
    consecutive_dates = []
    
    for attendance in all_attendances:
        # Check if it's a late entry
        if attendance.get("late_entry"):
            consecutive_count += 1
            consecutive_dates.append(attendance.attendance_date)
            
            # Check if threshold reached
            if consecutive_count >= policy.strike_threshold:
                apply_penalty(attendance.name, policy, consecutive_count, attendance.attendance_date)
                # Reset count after applying penalty
                consecutive_count = 0
                consecutive_dates = []
        else:
            # Reset consecutive count if not late
            # But only if this is not a half-day for genuine shortage
            if not is_genuine_shortage_halfday(attendance):
                consecutive_count = 0
                consecutive_dates = []


def get_late_attendances(employee, start_date, end_date):
    """Get all late attendance records for an employee in the given period."""
    
    return frappe.get_all(
        "Attendance",
        filters={
            "employee": employee,
            "attendance_date": ["between", [start_date, end_date]],
            "late_entry": 1,
            "docstatus": 1,
            "status": ["!=", "Absent"]  # Exclude absences
        },
        fields=["name", "attendance_date", "status"],
        order_by="attendance_date"
    )


def is_genuine_shortage_halfday(attendance):
    """
    Check if a half-day is due to genuine shortage of working hours.
    This is determined by checking if there's a specific remark or leave type.
    """
    if attendance.status != "Half Day":
        return False
    
    # Check if it's already a penalty half-day
    doc = frappe.get_doc("Attendance", attendance.name)
    if doc.custom_remarks and "late arrival" in doc.custom_remarks.lower():
        return False
    
    # Check if it's a planned half-day leave
    if doc.leave_type:
        return True
    
    # Add any other business logic to identify genuine shortage
    return False


def apply_penalty(attendance_name, policy, strike_count, attendance_date):
    """Apply penalty to the attendance record."""
    
    try:
        # Cancel the existing attendance
        attendance_doc = frappe.get_doc("Attendance", attendance_name)
        attendance_doc.cancel()
        
        # Create a new attendance record with penalty
        new_attendance = frappe.copy_doc(attendance_doc)
        
        # Apply penalty based on policy
        if policy.penalty_action == "Half-day":
            new_attendance.status = "Half Day"
        elif policy.penalty_action == "Full-day":
            new_attendance.status = "Absent"
        
        # Add remark
        month_name = calendar.month_name[attendance_date.month]
        year = attendance_date.year
        
        remark = f"{strike_count}{'rd' if strike_count == 3 else 'th'} late arrival in {month_name} {year}"
        new_attendance.custom_remarks = remark
        
        # Set penalty flag (you'll need to add this field to Attendance DocType)
        if hasattr(new_attendance, 'custom_late_penalty_applied'):
            new_attendance.custom_late_penalty_applied = 1
        
        # Submit the new record
        new_attendance.insert()
        new_attendance.submit()
        
        # Log the penalty application
        frappe.log_error(
            f"Late penalty applied to {attendance_doc.employee_name} for {attendance_date}",
            "Late Strike Penalty Applied"
        )
        
        # Create a notification for HR
        create_penalty_notification(attendance_doc.employee, attendance_doc.employee_name, 
                                  attendance_date, strike_count, policy.penalty_action)
        
    except Exception as e:
        frappe.log_error(
            f"Error applying penalty to attendance {attendance_name}: {str(e)}",
            "Late Strike Processor Error"
        )


def create_penalty_notification(employee, employee_name, date, strike_count, penalty_type):
    """Create a notification for HR about the applied penalty."""
    
    notification = frappe.new_doc("Notification Log")
    notification.subject = f"Late Penalty Applied: {employee_name}"
    notification.email_content = f"""
    Late arrival penalty has been automatically applied:
    
    Employee: {employee_name} ({employee})
    Date: {date}
    Strike Count: {strike_count}
    Penalty Type: {penalty_type}
    
    Please review the attendance record.
    """
    notification.for_user = frappe.session.user
    notification.type = "Alert"
    notification.document_type = "Attendance"
    notification.insert(ignore_permissions=True)


# Monthly reset function (optional)
def monthly_late_strike_reset():
    """
    Optional: Reset late strike counts at the beginning of each month.
    This can be used if you track cumulative counts in a separate doctype.
    """
    # Implementation depends on whether you want to maintain historical data
    pass


# Utility function for testing
@frappe.whitelist()
def test_late_strike_processor(employee=None, date=None):
    """Test function to run the processor for a specific employee and date."""
    if not employee:
        frappe.throw("Please provide an employee")
    
    # Get policy
    policy = frappe.get_single("Attendance Policy Settings")
    if not policy.enable_late_penalty:
        return "Late penalty is disabled"
    
    # Process for the employee
    process_employee_late_strikes(employee, policy)
    
    return f"Processed late strikes for {employee}"
