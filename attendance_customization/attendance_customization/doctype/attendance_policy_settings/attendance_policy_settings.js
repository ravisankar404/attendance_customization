// Copyright (c) 2025, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Attendance Policy Settings", {
  refresh: function (frm) {
    // Add custom buttons or actions here if needed
    frm.set_intro(
      __("Configure attendance late penalty rules for your organization."),
      "blue"
    );

    // Add help text
    if (frm.doc.enable_late_penalty) {
      frm.dashboard.add_comment(
        __(
          "Late penalty is currently enabled. Employees will receive penalties based on the configured rules."
        ),
        "green"
      );

      // Add reprocess button when late penalty is enabled and apply_from_date exists
      if (frm.doc.apply_from_date) {
        frm.add_custom_button(
          __("Reprocess Attendance"),
          function () {
            frappe.confirm(
              __(
                "This will reprocess all attendance records from {0}. Continue?",
                [frm.doc.apply_from_date]
              ),
              function () {
                frappe.call({
                  method:
                    "attendance_customization.attendance_customization.tasks.late_strike_processor.reprocess_attendance_from_date",
                  args: {
                    from_date: frm.doc.apply_from_date,
                  },
                  freeze: true,
                  freeze_message: __("Processing attendance records..."),
                  callback: function (r) {
                    if (r.message) {
                      frappe.msgprint({
                        title: __("Reprocess Complete"),
                        message: r.message,
                        indicator: "green",
                      });
                      // Refresh the form
                      frm.reload_doc();
                    }
                  },
                  error: function (r) {
                    frappe.msgprint({
                      title: __("Error"),
                      message: __(
                        "Failed to reprocess attendance records. Check error logs."
                      ),
                      indicator: "red",
                    });
                  },
                });
              }
            );
          },
          __("Actions")
        );
      }
    }
  },

  enable_late_penalty: function (frm) {
    // Clear fields when late penalty is disabled
    if (!frm.doc.enable_late_penalty) {
      frm.set_value("strike_threshold", "");
      frm.set_value("counting_mode", "");
      frm.set_value("penalty_action", "");
      frm.set_value("apply_from_date", "");
    }

    // Refresh field properties
    frm.refresh_fields();
  },

  strike_threshold: function (frm) {
    // Validate strike threshold on change
    if (frm.doc.strike_threshold && frm.doc.strike_threshold < 1) {
      frappe.msgprint(
        __("Strike Threshold must be at least 1"),
        __("Validation Error")
      );
      frm.set_value("strike_threshold", 1);
    }
  },

  counting_mode: function (frm) {
    // Add description based on counting mode
    if (frm.doc.counting_mode === "Cumulative") {
      frm.set_df_property(
        "counting_mode",
        "description",
        __("All late strikes in the period are counted together")
      );
    } else if (frm.doc.counting_mode === "Strictly Consecutive") {
      frm.set_df_property(
        "counting_mode",
        "description",
        __("Only consecutive late days trigger the penalty")
      );
    }
  },

  penalty_action: function (frm) {
    // Add description based on penalty action
    if (frm.doc.penalty_action === "Half-day") {
      frm.set_df_property(
        "penalty_action",
        "description",
        __("Half-day salary deduction will be applied")
      );
    } else if (frm.doc.penalty_action === "Full-day") {
      frm.set_df_property(
        "penalty_action",
        "description",
        __("Full-day salary deduction will be applied")
      );
    }
  },
});
