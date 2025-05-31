
# Copyright (c) 2025, Frappe Technologies and Contributors
# See license.txt

import frappe
import unittest
from frappe.tests.utils import FrappeTestCase


class TestAttendancePolicySettings(FrappeTestCase):
    def setUp(self):
        """Set up test data."""
        # Create test settings if they don't exist
        if not frappe.db.exists("Attendance Policy Settings", "Attendance Policy Settings"):
            self.settings = frappe.get_doc({
                "doctype": "Attendance Policy Settings",
                "enable_late_penalty": 1,
                "strike_threshold": 3,
                "counting_mode": "Cumulative",
                "penalty_action": "Half-day"
            }).insert()
        else:
            self.settings = frappe.get_single("Attendance Policy Settings")
    
    def test_validate_mandatory_fields(self):
        """Test that mandatory fields are validated when late penalty is enabled."""
        settings = frappe.get_single("Attendance Policy Settings")
        settings.enable_late_penalty = 1
        settings.strike_threshold = None
        
        with self.assertRaises(frappe.ValidationError):
            settings.save()
    
    def test_strike_threshold_validation(self):
        """Test strike threshold validation."""
        settings = frappe.get_single("Attendance Policy Settings")
        settings.enable_late_penalty = 1
        settings.strike_threshold = 0
        
        with self.assertRaises(frappe.ValidationError):
            settings.save()
    
    def test_get_penalty_settings(self):
        """Test get_penalty_settings method."""
        settings = frappe.get_single("Attendance Policy Settings")
        settings.enable_late_penalty = 1
        settings.strike_threshold = 3
        settings.counting_mode = "Cumulative"
        settings.penalty_action = "Half-day"
        settings.save()
        
        penalty_settings = settings.get_penalty_settings()
        
        self.assertTrue(penalty_settings["enabled"])
        self.assertEqual(penalty_settings["strike_threshold"], 3)
        self.assertEqual(penalty_settings["counting_mode"], "Cumulative")
        self.assertEqual(penalty_settings["penalty_action"], "Half-day")
    
    def test_disabled_penalty_returns_none(self):
        """Test that disabled penalty returns None."""
        settings = frappe.get_single("Attendance Policy Settings")
        settings.enable_late_penalty = 0
        settings.save()
        
        penalty_settings = settings.get_penalty_settings()
        self.assertIsNone(penalty_settings)
    
    def tearDown(self):
        """Clean up test data."""
        frappe.db.rollback()
