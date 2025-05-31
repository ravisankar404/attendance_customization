frappe.ui.form.on("Attendance", {
  late_entry: function (frm) {
    // Force recalculate late strike count when late entry is changed
    if (frm.doc.employee && frm.doc.attendance_date) {
      frappe.call({
        method:
          "attendance_customization.attendance_customization.attendance_immediate_processor.get_employee_late_count",
        args: {
          employee: frm.doc.employee,
          date: frm.doc.attendance_date,
          exclude_current: !frm.is_new() ? frm.doc.name : null,
        },
        callback: function (r) {
          if (r.message) {
            let count = r.message.count;
            if (frm.doc.late_entry && frm.is_new()) {
              count += 1;
            }
            frm.set_value("late_strike_count", count);
          }
        },
      });
    } else {
      frm.set_value("late_strike_count", 0);
    }
  },

  before_save: function (frm) {
    // Ensure count is updated before save
    if (!frm.doc.late_entry) {
      frm.set_value("late_strike_count", 0);
    }
  },
});
