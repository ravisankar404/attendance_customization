import frappe

def execute():
    """Update late incident remark field settings"""
    
    if frappe.db.exists("Custom Field", {"dt": "Attendance", "fieldname": "late_incident_remark"}):
        frappe.db.set_value("Custom Field", 
            {"dt": "Attendance", "fieldname": "late_incident_remark"}, 
            {
                "description": "",  # Remove description
                "hidden": 0,  # Make visible by default (JS will control visibility)
            }
        )
    
    frappe.db.commit()
    frappe.clear_cache(doctype="Attendance")