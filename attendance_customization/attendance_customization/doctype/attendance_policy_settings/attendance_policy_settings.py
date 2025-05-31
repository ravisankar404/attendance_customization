
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AttendancePolicySettings(Document):
    def validate(self):
        """Validate the attendance policy settings."""
        if self.enable_late_penalty:
            self.validate_mandatory_fields()
            self.validate_strike_threshold()
    
    def validate_mandatory_fields(self):
        """Ensure all required fields are filled when late penalty is enabled."""
        mandatory_fields = [
            "strike_threshold",
            "counting_mode", 
            "penalty_action"
        ]
        
        for field in mandatory_fields:
            if not self.get(field):
                frappe.throw(
                    f"{self.meta.get_label(field)} is required when Enable Late Penalty is checked",
                    title="Missing Required Field"
                )
    
    def validate_strike_threshold(self):
        """Validate strike threshold value."""
        if self.strike_threshold and self.strike_threshold < 1:
            frappe.throw(
                "Strike Threshold must be at least 1",
                title="Invalid Strike Threshold"
            )
    
    def on_update(self):
        """Clear cache when settings are updated."""
        frappe.clear_cache(doctype=self.doctype)
    
    @frappe.whitelist()
    def get_penalty_settings(self):
        """Get penalty settings for use in other modules."""
        if not self.enable_late_penalty:
            return None
            
        return {
            "enabled": True,
            "strike_threshold": self.strike_threshold,
            "counting_mode": self.counting_mode,
            "penalty_action": self.penalty_action
        }


@frappe.whitelist()
def get_attendance_policy_settings():
    """Get the attendance policy settings."""
    try:
        settings = frappe.get_single("Attendance Policy Settings")
        return settings.as_dict()
    except frappe.DoesNotExistError:
        # Return default settings if document doesn't exist
        return {
            "enable_late_penalty": 0,
            "strike_threshold": None,
            "counting_mode": None,
            "penalty_action": None
        }
