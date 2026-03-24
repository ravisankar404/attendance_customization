import frappe
from frappe.utils import getdate, get_first_day, get_last_day, now_datetime


# ─────────────────────────────────────────────
# Document event hooks (registered in hooks.py)
# ─────────────────────────────────────────────

def on_submit(doc, method):
    """
    Handle attendance submission - mark late strike as processed.
    """
    if doc.status == "Present" and doc.late_entry == 1 and not doc.strike_processed:
        frappe.db.set_value("Attendance", doc.name, "strike_processed", 1)
        frappe.db.commit()


def validate(doc, method):
    """
    Fires on every attendance save/insert (draft only).

    1. Auto-correct attendance status for half-day leave dates.
       ProcessAttendance creates "Present" from checkins without checking Leave
       Applications. This corrects it to the right status automatically —
       no scheduler needed, works even after delete-and-remark workflows.

    2. Late strike count update (real-time, before submit).
    """
    _ensure_half_day_attendance(doc)

    if doc.status == "Present" and doc.late_entry == 1:
        update_late_strike_count(doc)


# ─────────────────────────────────────────────
# Half-day leave attendance correction
# ─────────────────────────────────────────────

def _ensure_half_day_attendance(doc):
    """
    Auto-correct attendance on half-day leave dates so the Monthly Attendance
    Sheet shows the right status regardless of how attendance was created.

    CASES HANDLED:
      "Present"   + approved half-day leave → "Half Day" + leave_application  (HD/L) ✓
      "Half Day"  + no leave_application    → "Half Day" + leave_application  (HD/L) ✓
      "Absent"    + approved half-day leave → "Half Day" + no leave_application (HD/A) ✓
        └── 0.5 leave consumed by Leave Application + 0.5 salary deduction = L/A ✓

    SKIPPED:
      - Already correct (Half Day + leave_application set): fast exit.
      - On Leave / Work From Home: intentional status, never override.
      - Penalty records (custom_late_penalty_applied=1): penalty processor
        cancels and recreates attendance — don't interfere with it.
      - Missing employee or attendance_date: guard against bad data.

    SAFE WITH late_strike_processor.py:
      The penalty processor sets custom_late_penalty_applied=1 before insert,
      so this function skips penalty records. When penalties are cleared,
      the restored "Present" record is correctly changed to Half Day + leave. ✓
    """
    # Already correct — skip DB query entirely.
    if doc.status == "Half Day" and doc.leave_application:
        return

    # Don't override statuses that are intentionally set.
    if doc.status in ("On Leave", "Work From Home"):
        return

    # Penalty records are managed by late_strike_processor — don't touch them.
    if doc.get("custom_late_penalty_applied"):
        return

    # Guard against incomplete data.
    if not doc.employee or not doc.attendance_date:
        return

    leave = frappe.db.get_value(
        "Leave Application",
        {
            "employee": doc.employee,
            "half_day_date": doc.attendance_date,
            "half_day": 1,
            "status": "Approved",
            "docstatus": 1,
        },
        ["name", "leave_type"],
        as_dict=True,
    )

    if not leave:
        return

    original_status = doc.status
    doc.status = "Half Day"
    doc.leave_type = leave.leave_type

    if original_status != "Absent":
        # Present or Half Day (no leave_application) → link leave → HD/L.
        doc.leave_application = leave.name
    # Absent → Half Day without leave_application → HD/A.
    # Leave Application stays approved → 0.5 leave consumed separately.


# ─────────────────────────────────────────────
# Late strike helpers (used by validate above
# and by late_strike_processor.py scheduled task)
# ─────────────────────────────────────────────

def update_late_strike_count(doc):
    """
    Update the late strike count for the current month on the doc object.
    Called from validate (real-time) and indirectly from the scheduled task.
    """
    attendance_date = getdate(doc.attendance_date)
    first_day = get_first_day(attendance_date)
    last_day = get_last_day(attendance_date)

    late_count = frappe.db.count("Attendance", filters={
        "employee": doc.employee,
        "attendance_date": ["between", [first_day, last_day]],
        "late_entry": 1,
        "status": "Present",
        "docstatus": 1
    })

    if doc.docstatus == 0:
        late_count += 1

    doc.late_strike_count = late_count

    month_year = attendance_date.strftime("%B %Y")
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(late_count, "{}th".format(late_count))
    doc.late_incident_remark = "{} late arrival in {}".format(ordinal, month_year)

    if late_count >= 3:
        doc.late_incident_remark += " - WARNING: Exceeded monthly late arrival limit!"


def get_monthly_late_summary(employee, month=None, year=None):
    """
    Get late arrival summary for an employee for a specific month.
    """
    if not month or not year:
        today = getdate()
        month = today.month
        year = today.year

    first_day = getdate("{}-{:02d}-01".format(year, month))
    last_day = get_last_day(first_day)

    late_entries = frappe.get_all(
        "Attendance",
        filters={
            "employee": employee,
            "attendance_date": ["between", [first_day, last_day]],
            "late_entry": 1,
            "status": "Present",
            "docstatus": 1
        },
        fields=["name", "attendance_date", "late_incident_remark"],
        order_by="attendance_date asc"
    )

    return {
        "employee": employee,
        "month": first_day.strftime("%B %Y"),
        "late_count": len(late_entries),
        "late_entries": late_entries
    }
