frappe.ui.form.on("Attendance", {
  refresh: function (frm) {
    if (frm.is_new()) {
      frm.set_df_property("late_incident_remark", "hidden", 1);
    } else {
      // Show it when viewing existing attendance
      frm.set_df_property("late_incident_remark", "hidden", 0);
    }

    // Show late strike info
    if (frm.doc.late_entry && frm.doc.late_strike_count > 0) {
      frm.dashboard.add_comment(
        __("Late Strike Count: {0}", [frm.doc.late_strike_count]),
        "orange"
      );
    }

    // Add half-day type visibility
    frm.toggle_display("custom_half_day_type", frm.doc.status === "Half Day");
  },

  status: function (frm) {
    // Show/hide half-day type field
    frm.toggle_display("custom_half_day_type", frm.doc.status === "Half Day");

    // Auto-set genuine half-day flag if leave application exists
    if (frm.doc.status === "Half Day" && frm.doc.leave_application) {
      frm.set_value("custom_is_genuine_half_day", 1);
      frm.set_value("custom_half_day_type", "Personal Permission");
    }
  },

  late_entry: function (frm) {
    if (frm.doc.late_entry) {
      frappe.show_alert(
        {
          message: __(
            "Late entries are processed daily by the system scheduler"
          ),
          indicator: "orange",
        },
        5
      );
    }
  },
});
