import frappe

def after_install():
    """Run after app installation."""
    print("Setting up Attendance Customization...")
    
    # Clear cache
    frappe.clear_cache()
    
    # Any additional setup can go here
    print("Attendance Customization setup complete!")
