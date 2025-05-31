// Client script for Attendance customizations
frappe.ui.form.on("Attendance", {
  refresh: function (frm) {
    // Make fields read-only (backup in case field properties don't work)
    frm.set_df_property("late_strike_count", "read_only", 1);
    frm.set_df_property("late_incident_remark", "read_only", 1);

    // Add custom button to check late status
    if (!frm.is_new() && frm.doc.docstatus == 0 && frm.doc.employee) {
      frm.add_custom_button(
        __("Check Late Status"),
        function () {
          frappe.call({
            method:
              "attendance_customization.attendance_customization.attendance_immediate_processor.get_employee_late_status",
            args: {
              employee: frm.doc.employee,
              date: frm.doc.attendance_date,
            },
            callback: function (r) {
              if (r.message && r.message.enabled) {
                let msg = `<b>Late Strike Status for ${
                  frm.doc.employee_name || frm.doc.employee
                }</b><br><br>`;
                msg += `<table class="table table-bordered">`;
                msg += `<tr><td>Total Late Entries</td><td><b>${r.message.late_count}</b></td></tr>`;

                if (r.message.counting_mode == "Strictly Consecutive") {
                  msg += `<tr><td>Consecutive Late Entries</td><td><b>${r.message.consecutive_count}</b></td></tr>`;
                }

                msg += `<tr><td>Strike Threshold</td><td><b>${r.message.threshold}</b></td></tr>`;
                msg += `<tr><td>Counting Mode</td><td>${r.message.counting_mode}</td></tr>`;
                msg += `</table>`;

                if (r.message.next_will_trigger) {
                  msg += `<br><div class="alert alert-danger">`;
                  msg += `<i class="fa fa-exclamation-triangle"></i> <b>Warning:</b> Next late entry will trigger penalty!`;
                  msg += `</div>`;
                }

                frappe.msgprint({
                  title: __("Late Strike Status"),
                  message: msg,
                  indicator: r.message.next_will_trigger ? "red" : "blue",
                });
              } else {
                frappe.msgprint(__("Late penalty is disabled in settings"));
              }
            },
          });
        },
        __("Actions")
      );
    }

    // Show warning if this is a late entry
    if (frm.doc.late_entry && frm.doc.late_strike_count > 0) {
      frm.dashboard.add_comment(
        __("Late Strike Count: {0}", [frm.doc.late_strike_count]),
        "orange"
      );
    }
  },

  late_entry: function (frm) {
    // Show real-time warning when late entry is checked
    if (frm.doc.late_entry && !frm.is_new() && frm.doc.employee) {
      frappe.call({
        method:
          "attendance_customization.attendance_customization.attendance_immediate_processor.get_employee_late_status",
        args: {
          employee: frm.doc.employee,
          date: frm.doc.attendance_date,
        },
        callback: function (r) {
          if (r.message && r.message.enabled && r.message.next_will_trigger) {
            frappe.show_alert(
              {
                message: __(
                  "Warning: This will be late entry #{0}. Penalty will be applied upon submission!",
                  [r.message.late_count + 1]
                ),
                indicator: "red",
              },
              10
            );
          }
        },
      });
    }
  },

  employee: function (frm) {
    // Reset count when employee changes
    if (frm.is_new()) {
      frm.set_value("late_strike_count", 0);
      frm.set_value("late_incident_remark", "");
    }
  },

  before_save: function (frm) {
    // Validate before save
    if (frm.doc.late_entry && !frm.doc.employee) {
      frappe.throw(__("Please select an employee before marking late entry"));
    }
  },
});
