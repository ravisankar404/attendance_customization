import frappe
from attendance_customization.attendance_customization.custom_fields.attendance_custom_fields import create_custom_fields


def after_install():
    """Run after app installation."""
    print("Setting up Attendance Customization...")
    
    # Create custom fields
    create_custom_fields()
    
    # Clear cache
    frappe.clear_cache()
    
    # Create default Attendance Policy Settings if it doesn't exist
    if not frappe.db.exists("Attendance Policy Settings", "Attendance Policy Settings"):
        policy = frappe.new_doc("Attendance Policy Settings")
        policy.enable_late_penalty = 0  # Disabled by default
        policy.strike_threshold = 3
        policy.counting_mode = "Cumulative"
        policy.penalty_action = "Half-day"
        policy.insert(ignore_permissions=True)
        print("Created default Attendance Policy Settings")
    
    print("Attendance Customization setup complete!")


def before_uninstall():
    """Clean up before app uninstall."""
    # Optional: Remove custom fields on uninstall
    # This is usually not done to preserve data
    pass