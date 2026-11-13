// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const VT_APPROVALS = [
	{ check: "fit_sample_approved", date: "fit_sample_date", by: "fit_sample_by", label: __("Fit Sample") },
	{
		check: "size_set_sample_approved",
		date: "size_set_sample_date",
		by: "size_set_sample_by",
		label: __("Size Set Sample"),
	},
	{
		check: "photo_sample_approved",
		date: "photo_sample_date",
		by: "photo_sample_by",
		label: __("Photo Sample"),
	},
	{ check: "pp_sample_approved", date: "pp_sample_date", by: "pp_sample_by", label: __("PP Sample") },
	{ check: "ok_to_cut", date: "ok_to_cut_date", by: "ok_to_cut_by", label: __("OK to Cut") },
];
const PICKABLE_STATUSES = ["Open", "On Hold"];

frappe.ui.form.on("Job Map", {
	setup(frm) {
		frm.set_query("garment_order", "jobs", () => ({
			filters: { docstatus: 1, status: ["!=", "Cancelled"] },
		}));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		render_approval_tracker(frm);
		if (!frm.doc.job_closed) {
			frm.add_custom_button(__("Pick Orders"), () => pick_orders(frm));
		}
	},

	ok_to_cut(frm) {
		if (frm.doc.ok_to_cut && !frm.doc.pp_sample_approved) {
			frm.set_value("ok_to_cut", 0);
			frappe.msgprint({
				title: __("PP Sample Not Approved"),
				message: __(
					"OK to Cut can only be given after the PP sample is approved. Please tick PP Sample Approved first."
				),
				indicator: "orange",
			});
			return;
		}
		stamp(frm, "ok_to_cut");
	},

	pp_sample_approved(frm) {
		if (!frm.doc.pp_sample_approved && frm.doc.ok_to_cut) {
			frm.set_value("ok_to_cut", 0);
			frappe.show_alert({
				message: __("OK to Cut was removed because the PP sample is no longer approved."),
				indicator: "orange",
			});
		}
		stamp(frm, "pp_sample_approved");
	},
	fit_sample_approved: (frm) => stamp(frm, "fit_sample_approved"),
	size_set_sample_approved: (frm) => stamp(frm, "size_set_sample_approved"),
	photo_sample_approved: (frm) => stamp(frm, "photo_sample_approved"),
});

/** Show the date and approver immediately; the server sets the final values on save. */
function stamp(frm, check) {
	const a = VT_APPROVALS.find((x) => x.check === check);
	if (frm.doc[check]) {
		frm.doc[a.date] = frappe.datetime.get_today();
		frm.doc[a.by] = frappe.session.user;
	} else {
		frm.doc[a.date] = null;
		frm.doc[a.by] = null;
	}
	frm.refresh_fields([a.date, a.by]);
	render_approval_tracker(frm);
}

function render_approval_tracker(frm) {
	const esc = frappe.utils.escape_html;
	const next = VT_APPROVALS.find((a) => !frm.doc[a.check]);
	const html = VT_APPROVALS.map((a) => {
		const done = !!frm.doc[a.check];
		const cls = done ? "vt-approval--done" : a === next ? "vt-approval--next" : "";
		const detail = done
			? `${frappe.datetime.str_to_user(frm.doc[a.date]) || ""}<br>${esc(
					frappe.user.full_name(frm.doc[a.by]) || ""
			  )}`
			: a === next
			? __("Next approval")
			: __("Pending");
		return `<div class="vt-approval ${cls}">
			<span class="vt-approval__name">${a.label}</span>${detail}
		</div>`;
	}).join("");
	frm.get_field("approval_tracker").$wrapper.html(`<div class="vt-approvals">${html}</div>`);
}

function pick_orders(frm) {
	if (frm.doc.job_closed) {
		frappe.msgprint(__("Orders cannot be added to a closed Job Map."));
		return;
	}
	frappe
		.call({
			method: "velocity_ctp.velocity_ctp.doctype.job_map.job_map.get_unavailable_orders",
			args: { job_map: frm.is_new() ? null : frm.doc.name },
		})
		.then((r) => {
			const exclude = (r.message || []).concat((frm.doc.jobs || []).map((row) => row.garment_order));
			const filters = { docstatus: 1, status: ["in", PICKABLE_STATUSES] };
			if (exclude.length) filters.name = ["not in", exclude];

			new frappe.ui.form.MultiSelectDialog({
				doctype: "Garment Order",
				target: frm,
				setters: { customer: null, style: null },
				data_fields: [],
				columns: ["name", "customer", "style", "ship_date", "total_order_qty", "status"],
				primary_action_label: __("Add to Job Map"),
				get_query: () => ({ filters }),
				action(selections) {
					if (!selections || !selections.length) {
						frappe.msgprint(__("Please select at least one Garment Order."));
						return;
					}
					frappe.db
						.get_list("Garment Order", {
							filters: { name: ["in", selections] },
							fields: [
								"name",
								"style",
								"customer",
								"ship_date",
								"total_order_qty",
								"total_cutting_qty",
							],
							limit: selections.length,
						})
						.then((orders) => {
							// Remove an empty starter row, if any.
							(frm.doc.jobs || [])
								.filter((row) => !row.garment_order)
								.forEach((row) => frappe.model.clear_doc(row.doctype, row.name));
							orders.forEach((o) =>
								frm.add_child("jobs", {
									garment_order: o.name,
									style: o.style,
									customer: o.customer,
									ship_date: o.ship_date,
									total_order_qty: o.total_order_qty,
									total_cutting_qty: o.total_cutting_qty,
								})
							);
							frm.refresh_field("jobs");
							frm.dirty();
							this.dialog.hide();
							frappe.show_alert({
								message: __("{0} order(s) added", [orders.length]),
								indicator: "green",
							});
						});
				},
			});
		});
}
