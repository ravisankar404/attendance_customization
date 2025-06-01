import frappe

def execute():
    """Hide late strike count and strike processed fields"""
    
    # Update late_strike_count
    if frappe.db.exists("Custom Field", {"dt": "Attendance", "fieldname": "late_strike_count"}):
        frappe.db.set_value("Custom Field", 
            {"dt": "Attendance", "fieldname": "late_strike_count"}, 
            {
                "hidden": 1,
                "in_list_view": 0
            }
        )
    
    # Update strike_processed
    if frappe.db.exists("Custom Field", {"dt": "Attendance", "fieldname": "strike_processed"}):
        frappe.db.set_value("Custom Field", 
            {"dt": "Attendance", "fieldname": "strike_processed"}, 
            {
                "hidden": 1,
                "in_list_view": 0
            }
        )
    
    frappe.db.commit()
    
    # Clear cache
    frappe.clear_cache(doctype="Attendance")