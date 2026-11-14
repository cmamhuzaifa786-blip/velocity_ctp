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
const PP_REQUIRED_MESSAGE = __(
	"OK to Cut can only be given after the PP sample is approved. Please approve the PP sample first."
);

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
		render_jobs_total(frm);
		if (!frm.doc.job_closed && frm.has_perm("write")) {
			frm.add_custom_button(__("Pick Orders"), () => pick_orders(frm));
		}
	},

	ok_to_cut(frm) {
		if (frm.doc.ok_to_cut && !frm.doc.pp_sample_approved) {
			frm.set_value("ok_to_cut", 0);
			frappe.msgprint({ title: __("PP Sample Not Approved"), message: PP_REQUIRED_MESSAGE, indicator: "orange" });
			return;
		}
		stamp(frm, "ok_to_cut");
	},

	pp_sample_approved(frm) {
		if (!frm.doc.pp_sample_approved && frm.doc.ok_to_cut) {
			frm.set_value("ok_to_cut", 0);
		}
		stamp(frm, "pp_sample_approved");
	},
	fit_sample_approved: (frm) => stamp(frm, "fit_sample_approved"),
	size_set_sample_approved: (frm) => stamp(frm, "size_set_sample_approved"),
	photo_sample_approved: (frm) => stamp(frm, "photo_sample_approved"),
});

frappe.ui.form.on("Job Map Order", {
	garment_order: (frm) => setTimeout(() => render_jobs_total(frm), 300),
	jobs_add: (frm) => render_jobs_total(frm),
	jobs_remove: (frm) => render_jobs_total(frm),
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

/**
 * Approval cards are the control: a card approves its stage, an approved card undoes it.
 * Both ask for confirmation and save the Job Map, so the change lands in the timeline.
 * Users without write permission see the cards but cannot click them.
 */
function render_approval_tracker(frm) {
	const esc = frappe.utils.escape_html;
	const can_edit = frm.has_perm("write");
	const next = VT_APPROVALS.find((a) => !frm.doc[a.check]);

	const html = VT_APPROVALS.map((a) => {
		const done = !!frm.doc[a.check];
		const blocked = a.check === "ok_to_cut" && !done && !frm.doc.pp_sample_approved;
		let state = "pending";
		let detail = __("Pending");
		if (done) {
			state = "done";
			const date = frappe.datetime.str_to_user(frm.doc[a.date]) || "";
			detail = `${__("Approved {0}", [`<span class="vt-nowrap">${date}</span>`])}<br>${esc(
				frappe.user.full_name(frm.doc[a.by]) || ""
			)}`;
		} else if (blocked) {
			state = "blocked";
			detail = __("Needs PP approval");
		} else if (a === next) {
			state = "next";
			detail = can_edit ? __("Click to approve") : __("Next approval");
		} else if (can_edit) {
			detail = __("Click to approve");
		}
		const action = done ? __("Undo {0} approval", [a.label]) : __("Approve {0}", [a.label]);
		return `<button type="button" class="vt-approval vt-approval--${state}" data-approval="${a.check}"
			${can_edit ? `title="${esc(action)}"` : "disabled aria-disabled=\"true\""}>
			<span class="vt-approval__name">
				<span class="vt-approval__mark" aria-hidden="true">${done ? "✓" : ""}</span>${a.label}
			</span>
			<span class="vt-approval__detail">${detail}</span>
		</button>`;
	}).join("");

	const $wrapper = frm.get_field("approval_tracker").$wrapper;
	$wrapper.html(`<div class="vt-approvals ${can_edit ? "" : "vt-approvals--readonly"}">${html}</div>`);
	if (can_edit) {
		$wrapper.find("[data-approval]").on("click", (e) => on_approval_click(frm, e.currentTarget.dataset.approval));
	}
}

function on_approval_click(frm, check) {
	const a = VT_APPROVALS.find((x) => x.check === check);
	const approve = !frm.doc[check];

	if (approve && check === "ok_to_cut" && !frm.doc.pp_sample_approved) {
		frappe.msgprint({ title: __("PP Sample Not Approved"), message: PP_REQUIRED_MESSAGE, indicator: "orange" });
		return;
	}

	const notes = [];
	if (approve) {
		notes.push(__("Today's date and your name will be recorded as the approval."));
	} else {
		notes.push(__("The approval date and approver will be cleared."));
		if (check === "pp_sample_approved" && frm.doc.ok_to_cut) {
			notes.push(__("OK to Cut will also be removed, because it needs the PP approval."));
		}
	}
	if (frm.is_dirty() && !frm.is_new()) {
		notes.push(__("Your other unsaved changes on this Job Map will be saved too."));
	}
	const question = approve ? __("Approve the {0}?", [a.label]) : __("Undo the {0} approval?", [a.label]);

	frappe.confirm(`<p><b>${question}</b></p><p>${notes.join("<br>")}</p>`, () => {
		frm.set_value(check, approve ? 1 : 0).then(() => {
			if (frm.is_new()) {
				frappe.show_alert({
					message: __("The approval will be recorded when you save this Job Map."),
					indicator: "blue",
				});
				return;
			}
			frm.save().catch(() => frm.reload_doc());
		});
	});
}

function render_jobs_total(frm) {
	const field = frm.get_field("jobs_total");
	if (!field) return;
	const rows = (frm.doc.jobs || []).filter((r) => r.garment_order);
	const order = rows.reduce((t, r) => t + cint(r.total_order_qty), 0);
	const cut = rows.reduce((t, r) => t + cint(r.total_cutting_qty), 0);
	field.$wrapper.html(
		rows.length
			? `<div class="vt-grid-total">
				<span class="vt-grid-total__label">${__("Total")}
					<span class="vt-muted">· ${__("{0} orders", [rows.length])}</span></span>
				<span class="vt-grid-total__item">${__("Order Qty")}
					<b>${format_number(order, null, 0)}</b></span>
				<span class="vt-grid-total__item">${__("Cut Qty")}
					<b>${format_number(cut, null, 0)}</b></span>
			</div>`
			: ""
	);
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
							render_jobs_total(frm);
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
