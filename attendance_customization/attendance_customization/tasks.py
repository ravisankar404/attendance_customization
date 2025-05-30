import frappe
from frappe.utils import getdate, get_first_day, get_last_day, add_days, now_datetime
from datetime import datetime

def daily_late_strike_processor():
    """
    Daily scheduled task to process attendance records and update late strikes
    """
    print(f"Running daily late strike processor at {now_datetime()}")
    
    # Get yesterday's date (to process completed attendance records)
    yesterday = add_days(getdate(), -1)
    
    # Get all unprocessed attendance records from yesterday
    unprocessed_records = frappe.db.get_all("Attendance",
        filters={
            "attendance_date": yesterday,
            "strike_processed": 0,
            "late_entry": 1,
            "status": "Present",
            "docstatus": 1
        },
        fields=["name", "employee"]
    )
    
    for record in unprocessed_records:
        try:
            # Get the attendance document
            doc = frappe.get_doc("Attendance", record.name)
            
            # Update late strike count for the month
            update_monthly_strike_count(doc)
            
            # Mark as processed
            frappe.db.set_value("Attendance", doc.name, "strike_processed", 1)
            
            # Check if employee has exceeded late limit
            check_and_notify_late_limit(doc.employee, yesterday)
            
        except Exception as e:
            frappe.log_error(f"Error processing attendance {record.name}: {str(e)}", 
                           "Late Strike Processor Error")
    
    frappe.db.commit()
    print(f"Processed {len(unprocessed_records)} attendance records")

def monthly_strike_reset():
    """
    Monthly scheduled task to reset strike counts (runs on 1st of each month)
    """
    print(f"Running monthly strike reset at {now_datetime()}")
    
    # This task can be used to:
    # 1. Generate monthly reports
    # 2. Reset any monthly counters if needed
    # 3. Send monthly summaries
    
    # Get last month's date
    today = getdate()
    if today.day == 1:
        last_month = add_days(today, -1)
        generate_monthly_late_report(last_month.month, last_month.year)

def update_monthly_strike_count(doc):
    """
    Update strike count for all attendance records of an employee in the current month
    """
    attendance_date = getdate(doc.attendance_date)
    first_day = get_first_day(attendance_date)
    last_day = get_last_day(attendance_date)
    
    # Get all attendance records for this employee in the current month
    monthly_records = frappe.db.get_all("Attendance",
        filters={
            "employee": doc.employee,
            "attendance_date": ["between", [first_day, last_day]],
            "late_entry": 1,
            "status": "Present",
            "docstatus": 1
        },
        fields=["name", "attendance_date"],
        order_by="attendance_date asc"
    )
    
    # Update strike count for each record
    for idx, record in enumerate(monthly_records, 1):
        month_year = attendance_date.strftime("%B %Y")
        
        if idx == 1:
            remark = f"1st late arrival in {month_year}"
        elif idx == 2:
            remark = f"2nd late arrival in {month_year}"
        elif idx == 3:
            remark = f"3rd late arrival in {month_year}"
        else:
            remark = f"{idx}th late arrival in {month_year}"
        
        if idx >= 3:
            remark += " - WARNING: Exceeded monthly late arrival limit!"
        
        frappe.db.set_value("Attendance", record.name, {
            "late_strike_count": idx,
            "late_incident_remark": remark
        })

def check_and_notify_late_limit(employee, date):
    """
    Check if employee has exceeded late limit and send notifications
    """
    first_day = get_first_day(date)
    last_day = get_last_day(date)
    
    late_count = frappe.db.count("Attendance", filters={
        "employee": employee,
        "attendance_date": ["between", [first_day, last_day]],
        "late_entry": 1,
        "status": "Present",
        "docstatus": 1
    })
    
    # Send notification if limit exceeded
    if late_count == 3:
        send_late_limit_notification(employee, late_count, date)
    elif late_count > 3:
        send_excessive_late_notification(employee, late_count, date)

def send_late_limit_notification(employee, late_count, date):
    """
    Send notification when employee reaches late limit
    """
    employee_doc = frappe.get_doc("Employee", employee)
    month_year = date.strftime("%B %Y")
    
    # Create notification
    notification = frappe.new_doc("Notification Log")
    notification.subject = f"Late Arrival Limit Reached - {employee_doc.employee_name}"
    notification.for_user = employee_doc.user_id if employee_doc.user_id else None
    notification.type = "Alert"
    notification.document_type = "Employee"
    notification.document_name = employee
    notification.from_user = "Administrator"
    notification.email_content = f"""
    <p>Dear {employee_doc.employee_name},</p>
    <p>You have reached the maximum allowed late arrivals ({late_count}) for {month_year}.</p>
    <p>Any additional late arrivals may result in disciplinary action.</p>
    <p>Please ensure timely attendance going forward.</p>
    """
    notification.insert(ignore_permissions=True)
    
    # Also notify HR
    notify_hr_about_late_limit(employee_doc, late_count, month_year)

def send_excessive_late_notification(employee, late_count, date):
    """
    Send notification for excessive late arrivals
    """
    employee_doc = frappe.get_doc("Employee", employee)
    month_year = date.strftime("%B %Y")
    
    # Notify HR about excessive late arrivals
    notify_hr_about_excessive_late(employee_doc, late_count, month_year)

def notify_hr_about_late_limit(employee_doc, late_count, month_year):
    """
    Notify HR when employee reaches late limit
    """
    hr_users = frappe.get_all("Has Role", 
        filters={"role": "HR Manager"}, 
        fields=["parent as user"])
    
    for hr in hr_users:
        notification = frappe.new_doc("Notification Log")
        notification.subject = f"Employee Late Limit Reached - {employee_doc.employee_name}"
        notification.for_user = hr.user
        notification.type = "Alert"
        notification.document_type = "Employee"
        notification.document_name = employee_doc.name
        notification.from_user = "Administrator"
        notification.email_content = f"""
        <p>HR Alert: Employee {employee_doc.employee_name} ({employee_doc.name}) has reached the late arrival limit.</p>
        <p>Late arrivals in {month_year}: {late_count}</p>
        <p>Please take appropriate action as per company policy.</p>
        """
        notification.insert(ignore_permissions=True)

def notify_hr_about_excessive_late(employee_doc, late_count, month_year):
    """
    Notify HR about excessive late arrivals
    """
    hr_users = frappe.get_all("Has Role", 
        filters={"role": "HR Manager"}, 
        fields=["parent as user"])
    
    for hr in hr_users:
        notification = frappe.new_doc("Notification Log")
        notification.subject = f"URGENT: Excessive Late Arrivals - {employee_doc.employee_name}"
        notification.for_user = hr.user
        notification.type = "Alert"
        notification.document_type = "Employee"
        notification.document_name = employee_doc.name
        notification.from_user = "Administrator"
        notification.email_content = f"""
        <p><strong>URGENT HR Alert:</strong> Employee {employee_doc.employee_name} ({employee_doc.name}) has exceeded the late arrival limit.</p>
        <p>Late arrivals in {month_year}: <strong>{late_count}</strong></p>
        <p>Immediate action required as per company policy.</p>
        """
        notification.insert(ignore_permissions=True)

def generate_monthly_late_report(month, year):
    """
    Generate monthly late arrival report
    """
    first_day = getdate(f"{year}-{month:02d}-01")
    last_day = get_last_day(first_day)
    month_year = first_day.strftime("%B %Y")
    
    # Get all employees with late arrivals
    late_summary = frappe.db.sql("""
        SELECT 
            a.employee,
            e.employee_name,
            COUNT(*) as late_count,
            GROUP_CONCAT(DATE_FORMAT(a.attendance_date, '%d-%b') ORDER BY a.attendance_date) as late_dates
        FROM 
            `tabAttendance` a
        JOIN 
            `tabEmployee` e ON a.employee = e.name
        WHERE 
            a.attendance_date BETWEEN %s AND %s
            AND a.late_entry = 1
            AND a.status = 'Present'
            AND a.docstatus = 1
        GROUP BY 
            a.employee, e.employee_name
        HAVING 
            late_count >= 3
        ORDER BY 
            late_count DESC
    """, (first_day, last_day), as_dict=True)
    
    if late_summary:
        # Create a report document or send email
        report_content = f"<h3>Monthly Late Arrival Report - {month_year}</h3>"
        report_content += "<table border='1' style='border-collapse: collapse;'>"
        report_content += "<tr><th>Employee ID</th><th>Employee Name</th><th>Late Count</th><th>Late Dates</th></tr>"
        
        for row in late_summary:
            report_content += f"<tr><td>{row.employee}</td><td>{row.employee_name}</td><td>{row.late_count}</td><td>{row.late_dates}</td></tr>"
        
        report_content += "</table>"
        
        # Send to HR
        hr_users = frappe.get_all("Has Role", 
            filters={"role": "HR Manager"}, 
            fields=["parent as user"])
        
        for hr in hr_users:
            frappe.sendmail(
                recipients=[hr.user],
                subject=f"Monthly Late Arrival Report - {month_year}",
                message=report_content
            )