frappe.pages["bulk-delete-attendance"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Bulk Delete Attendance"),
		single_column: true,
	});

	frappe.breadcrumbs.add("HR");

	// ── State ──────────────────────────────────────────────────────────────
	let previewData = null; // Holds the last fetched count result

	// ── Build UI ───────────────────────────────────────────────────────────
	const $body = $(page.body).addClass("no-border").css({ padding: "20px" });

	$body.html(`
		<div class="bulk-delete-attendance-wrapper" style="max-width:680px; margin:0 auto;">

			<!-- Card: Date Range -->
			<div class="frappe-card" style="padding:24px 28px; margin-bottom:20px; border-radius:8px; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.08);">
				<h5 style="margin:0 0 18px; font-size:14px; font-weight:600; color:var(--text-color);">
					${__("Select Date Range")}
				</h5>
				<div style="display:flex; gap:16px; flex-wrap:wrap; align-items:flex-end;">
					<div style="flex:1; min-width:160px;">
						<label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:6px;">
							${__("From Date")} <span style="color:var(--red)">*</span>
						</label>
						<input id="bda-from-date" type="date" class="form-control input-sm"
							style="width:100%; font-size:13px;" />
					</div>
					<div style="flex:1; min-width:160px;">
						<label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:6px;">
							${__("To Date")} <span style="color:var(--red)">*</span>
						</label>
						<input id="bda-to-date" type="date" class="form-control input-sm"
							style="width:100%; font-size:13px;" />
					</div>
					<div>
						<button id="bda-preview-btn" class="btn btn-default btn-sm" style="min-width:120px;">
							<i class="fa fa-search"></i> ${__("Preview Records")}
						</button>
					</div>
				</div>
				<p id="bda-date-error" style="color:var(--red); font-size:12px; margin:10px 0 0; display:none;"></p>
			</div>

			<!-- Card: Preview Results (hidden until fetched) -->
			<div id="bda-preview-card" class="frappe-card"
				style="padding:24px 28px; margin-bottom:20px; border-radius:8px; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.08); display:none;">
				<h5 style="margin:0 0 16px; font-size:14px; font-weight:600; color:var(--text-color);">
					${__("Records Found")}
				</h5>

				<div id="bda-count-area" style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px;">
					<!-- stat pills injected by JS -->
				</div>

				<div id="bda-zero-msg" style="display:none; padding:14px 0; color:var(--text-muted); font-size:13px; text-align:center;">
					<i class="fa fa-check-circle" style="color:var(--green); font-size:20px;"></i>
					<br><br>${__("No attendance records found for the selected date range.")}
				</div>

				<!-- Warning for submitted records -->
				<div id="bda-submit-warn"
					style="display:none; background:#fff8e1; border-left:4px solid #f39c12; padding:10px 14px; border-radius:4px; font-size:12px; margin-bottom:16px; color:#7d5800;">
					<i class="fa fa-exclamation-triangle"></i>
					${__("Submitted attendance records will be <strong>cancelled first</strong>, then permanently deleted.")}
				</div>

				<!-- Irreversible action warning -->
				<div id="bda-delete-section" style="display:none;">
					<div style="background:#fdf2f2; border-left:4px solid var(--red); padding:10px 14px; border-radius:4px; font-size:12px; margin-bottom:16px; color:#9e2a2b;">
						<i class="fa fa-trash"></i>
						<strong>${__("This action is permanent and cannot be undone.")}</strong>
						${__("All attendance records in the selected range will be deleted.")}
					</div>
					<button id="bda-delete-btn" class="btn btn-danger btn-sm" style="min-width:180px;">
						<i class="fa fa-trash"></i> ${__("Bulk Delete Attendance")}
					</button>
				</div>
			</div>

			<!-- Card: Result (hidden until delete completes) -->
			<div id="bda-result-card" class="frappe-card"
				style="padding:24px 28px; border-radius:8px; background:#fff; box-shadow:0 1px 4px rgba(0,0,0,.08); display:none;">
				<div id="bda-result-content"></div>
			</div>

		</div>
	`);

	// ── Date helpers ───────────────────────────────────────────────────────
	function getFromDate() { return $("#bda-from-date").val(); }
	function getToDate()   { return $("#bda-to-date").val(); }

	function showDateError(msg) {
		$("#bda-date-error").text(msg).show();
	}
	function clearDateError() {
		$("#bda-date-error").hide().text("");
	}

	function validateDates() {
		clearDateError();
		const from = getFromDate();
		const to   = getToDate();

		if (!from) { showDateError(__("Please select a From Date.")); return false; }
		if (!to)   { showDateError(__("Please select a To Date."));   return false; }

		if (from > to) {
			showDateError(__("From Date cannot be after To Date."));
			return false;
		}

		// Warn if range > 366 days (backend also enforces this)
		const diffDays = (new Date(to) - new Date(from)) / 86400000;
		if (diffDays > 366) {
			showDateError(__("Date range cannot exceed 366 days. Please split into smaller batches."));
			return false;
		}

		return true;
	}

	// ── Stat pill helper ───────────────────────────────────────────────────
	function buildStatPill(label, value, color) {
		return `
			<div style="background:${color}18; border:1px solid ${color}44;
				border-radius:6px; padding:10px 18px; text-align:center; min-width:100px;">
				<div style="font-size:22px; font-weight:700; color:${color};">${value}</div>
				<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">${label}</div>
			</div>`;
	}

	// ── Preview ────────────────────────────────────────────────────────────
	function fetchPreview() {
		if (!validateDates()) return;

		previewData = null;
		$("#bda-preview-card").hide();
		$("#bda-result-card").hide();

		const $btn = $("#bda-preview-btn").prop("disabled", true)
			.html(`<i class="fa fa-spinner fa-spin"></i> ${__("Fetching...")}`);

		frappe.call({
			method: "attendance_customization.attendance_customization.page.bulk_delete_attendance.bulk_delete_attendance.get_attendance_count",
			args: { from_date: getFromDate(), to_date: getToDate() },
			freeze: false,
			callback(r) {
				$btn.prop("disabled", false).html(`<i class="fa fa-search"></i> ${__("Preview Records")}`);

				if (r.exc || !r.message) return; // frappe shows error toast automatically

				const data = r.message;
				previewData = data;

				// Build pills
				const $counts = $("#bda-count-area").empty();
				$counts.append(buildStatPill(__("Total"), data.total, "var(--blue)"));
				if (data.draft)     $counts.append(buildStatPill(__("Draft"),     data.draft,     "var(--gray-600)"));
				if (data.submitted) $counts.append(buildStatPill(__("Submitted"), data.submitted, "var(--orange)"));
				if (data.cancelled) $counts.append(buildStatPill(__("Cancelled"), data.cancelled, "var(--green)"));

				if (data.total === 0) {
					$("#bda-zero-msg").show();
					$("#bda-submit-warn").hide();
					$("#bda-delete-section").hide();
				} else {
					$("#bda-zero-msg").hide();
					$("#bda-submit-warn").toggle(data.submitted > 0);
					$("#bda-delete-section").show();
				}

				$("#bda-preview-card").show();
			},
			error() {
				$btn.prop("disabled", false).html(`<i class="fa fa-search"></i> ${__("Preview Records")}`);
			},
		});
	}

	// ── Delete ─────────────────────────────────────────────────────────────
	function confirmAndDelete() {
		if (!previewData || previewData.total === 0) return;

		const total = previewData.total;
		const from  = getFromDate();
		const to    = getToDate();

		// For large datasets show an extra typed-confirmation
		if (total > 200) {
			frappe.prompt(
				[{
					label: __("Type DELETE to confirm"),
					fieldname: "confirm_text",
					fieldtype: "Data",
					reqd: 1,
					description: __("You are about to permanently delete {0} attendance records. This cannot be undone.", [total]),
				}],
				(values) => {
					if ((values.confirm_text || "").trim().toUpperCase() !== "DELETE") {
						frappe.msgprint({ message: __('You must type "DELETE" to confirm.'), indicator: "red" });
						return;
					}
					runDelete(from, to, total);
				},
				__("Confirm Bulk Delete"),
				__("Proceed with Deletion")
			);
		} else {
			frappe.confirm(
				__("Are you sure you want to permanently delete <strong>{0} attendance record(s)</strong> between {1} and {2}?<br><br>This cannot be undone.", [total, from, to]),
				() => runDelete(from, to, total)
			);
		}
	}

	function runDelete(from, to, total) {
		const $btn = $("#bda-delete-btn").prop("disabled", true)
			.html(`<i class="fa fa-spinner fa-spin"></i> ${__("Deleting...")}`);
		$("#bda-result-card").hide();

		frappe.call({
			method: "attendance_customization.attendance_customization.page.bulk_delete_attendance.bulk_delete_attendance.bulk_delete_attendance",
			args: { from_date: from, to_date: to },
			freeze: true,
			freeze_message: __("Deleting attendance records, please wait…"),
			callback(r) {
				$btn.prop("disabled", false).html(`<i class="fa fa-trash"></i> ${__("Bulk Delete Attendance")}`);

				if (r.exc || !r.message) return;

				const res = r.message;
				showResult(res, total);

				// Reset preview so user can't double-delete
				previewData = null;
				$("#bda-preview-card").hide();
			},
			error() {
				$btn.prop("disabled", false).html(`<i class="fa fa-trash"></i> ${__("Bulk Delete Attendance")}`);
			},
		});
	}

	// ── Result card ────────────────────────────────────────────────────────
	function showResult(res, total) {
		const $card = $("#bda-result-card").show();
		const $content = $("#bda-result-content").empty();

		if (res.status === "queued") {
			$content.html(`
				<div style="text-align:center; padding:8px 0;">
					<i class="fa fa-clock-o" style="font-size:32px; color:var(--blue); margin-bottom:12px; display:block;"></i>
					<h5 style="font-weight:600;">${__("Deletion Queued")}</h5>
					<p style="color:var(--text-muted); font-size:13px;">${res.message}</p>
				</div>
			`);
			return;
		}

		const success = res.deleted > 0 || res.failed === 0;
		const icon    = res.failed === 0
			? `<i class="fa fa-check-circle" style="font-size:32px; color:var(--green);"></i>`
			: `<i class="fa fa-exclamation-triangle" style="font-size:32px; color:var(--orange);"></i>`;

		let html = `
			<div style="text-align:center; padding:8px 0 16px;">
				<div style="margin-bottom:10px;">${icon}</div>
				<h5 style="font-weight:600;">
					${res.failed === 0 ? __("Deletion Complete") : __("Completed with Errors")}
				</h5>
			</div>
			<div style="display:flex; gap:12px; justify-content:center; flex-wrap:wrap; margin-bottom:16px;">
				${buildStatPill(__("Deleted"), res.deleted, "var(--green)")}
				${res.failed > 0 ? buildStatPill(__("Failed"), res.failed, "var(--red)") : ""}
			</div>`;

		$content.html(html);

		if (res.errors && res.errors.length) {
			const $errWrap = $(`
				<div style="margin-top:12px;">
					<p style="font-size:12px; font-weight:600; color:var(--red);"></p>
					<div class="bda-err-list" style="background:#fdf2f2; border-radius:4px; padding:10px;
						max-height:180px; overflow-y:auto; font-size:11px; font-family:monospace;"></div>
				</div>`);
			$errWrap.find("p").text(__("Errors (first {0}):", [res.errors.length]));
			const $list = $errWrap.find(".bda-err-list");
			res.errors.forEach(e => {
				// Use .text() for all untrusted server values to prevent XSS
				const $row = $(`<div style="padding:2px 0; border-bottom:1px solid #f5c6c6;"></div>`);
				const $name = $("<strong>").text(e.name);
				const $rest = $("<span>").text(` — ${e.employee || ""} (${e.date}): ${e.error}`);
				$row.append($name, $rest);
				$list.append($row);
			});
			$content.append($errWrap);
		}
	}

	// ── Real-time notification for background jobs ─────────────────────────
	frappe.realtime.on("bulk_delete_attendance_done", (data) => {
		// Only show if this page is still open
		if (!frappe.get_route_str().includes("bulk-delete-attendance")) return;
		showResult({ status: "done", ...data }, data.deleted + data.failed);
		frappe.show_alert({
			message: __("Background deletion complete: {0} deleted, {1} failed.", [data.deleted, data.failed]),
			indicator: data.failed > 0 ? "orange" : "green",
		}, 8);
	});

	// ── Wire events ────────────────────────────────────────────────────────
	$body.on("click", "#bda-preview-btn", fetchPreview);
	$body.on("click", "#bda-delete-btn",  confirmAndDelete);

	// Re-hide preview when dates change
	$body.on("change", "#bda-from-date, #bda-to-date", () => {
		previewData = null;
		clearDateError();
		$("#bda-preview-card").hide();
		$("#bda-result-card").hide();
	});

	// Allow Enter key on date fields to trigger preview
	$body.on("keydown", "#bda-from-date, #bda-to-date", (e) => {
		if (e.key === "Enter") fetchPreview();
	});
};
