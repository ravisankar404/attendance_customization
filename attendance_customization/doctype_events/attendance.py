import frappe
from frappe import _
from frappe.utils import getdate, get_first_day, get_last_day, now_datetime

def validate(doc, method):
    """
    Validate attendance and update late strike count if applicable
    """
    if doc.status == "Present" and doc.late_entry == 1:
        update_late_strike_count(doc)

def on_submit(doc, method):
    """
    Handle attendance submission
    """
    if doc.status == "Present" and doc.late_entry == 1 and not doc.strike_processed:
        # Mark as processed to avoid duplicate processing
        frappe.db.set_value("Attendance", doc.name, "strike_processed", 1)
        frappe.db.commit()

def update_late_strike_count(doc):
    """
    Update the late strike count for the current month
    """
    # Get the first and last day of the current month
    attendance_date = getdate(doc.attendance_date)
    first_day = get_first_day(attendance_date)
    last_day = get_last_day(attendance_date)
    
    # Count late entries for this employee in the current month
    late_count = frappe.db.count("Attendance", filters={
        "employee": doc.employee,
        "attendance_date": ["between", [first_day, last_day]],
        "late_entry": 1,
        "status": "Present",
        "docstatus": 1
    })
    
    # Include current record if it's not yet submitted
    if doc.docstatus == 0:
        late_count += 1
    
    # Update the late strike count
    doc.late_strike_count = late_count
    
    # Add remark
    month_year = attendance_date.strftime("%B %Y")
    if late_count == 1:
        doc.late_incident_remark = f"1st late arrival in {month_year}"
    elif late_count == 2:
        doc.late_incident_remark = f"2nd late arrival in {month_year}"
    elif late_count == 3:
        doc.late_incident_remark = f"3rd late arrival in {month_year}"
    else:
        doc.late_incident_remark = f"{late_count}th late arrival in {month_year}"
    
    # Add warning if reaching threshold
    if late_count >= 3:
        doc.late_incident_remark += " - WARNING: Exceeded monthly late arrival limit!"

def get_monthly_late_summary(employee, month=None, year=None):
    """
    Get late arrival summary for an employee for a specific month
    """
    if not month or not year:
        today = getdate()
        month = today.month
        year = today.year
    
    first_day = getdate(f"{year}-{month:02d}-01")
    last_day = get_last_day(first_day)
    
    late_entries = frappe.db.get_all("Attendance",
        filters={
            "employee": employee,
            "attendance_date": ["between", [first_day, last_day]],
            "late_entry": 1,
            "status": "Present",
            "docstatus": 1
        },
        fields=["name", "attendance_date", "late_incident_remark"],
        order_by="attendance_date asc"
    )
    
    return {
        "employee": employee,
        "month": first_day.strftime("%B %Y"),
        "late_count": len(late_entries),
        "late_entries": late_entries
    }