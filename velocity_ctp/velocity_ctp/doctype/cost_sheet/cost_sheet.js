// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const CS_METHOD = "velocity_ctp.velocity_ctp.doctype.cost_sheet.cost_sheet.";
const CS_SECTIONS = ["Material", "Processing", "Overheads", "Commercial", "Freight"];

frappe.ui.form.on("Cost Sheet", {
	setup(frm) {
		frm.set_query("style", () => ({ filters: frm.doc.customer ? { customer: frm.doc.customer } : {} }));
		frm.set_query("fabric_item", "fabrics", () => ({ filters: { item_group: "Fabric", disabled: 0 } }));
		frm.set_query("accessory_item", "accessories", () => ({ filters: { item_group: "Accessories & Trims", disabled: 0 } }));
		frm.vt_recalc = frappe.utils.debounce(() => recalculate(frm), 450);
	},

	onload(frm) {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
		if (frm.is_new() && !frm.doc.company) frm.set_value("company", frappe.defaults.get_user_default("Company"));
		if (frm.is_new() && !(frm.doc.costs || []).length) recalculate(frm);
	},

	refresh(frm) {
		render_summary(frm);
		add_buttons(frm);
		show_status(frm);
		if (frm.doc.status === "Pending Approval") frm.disable_form();
	},

	customer(frm) {
		if (frm.doc.style && frm.doc.customer) {
			frappe.db.get_value("Style", frm.doc.style, "customer").then((r) => {
				if (r.message && r.message.customer !== frm.doc.customer) frm.set_value("style", null);
			});
		}
	},
	style(frm) {
		if (frm.doc.style && !frm.doc.customer) {
			frappe.db.get_value("Style", frm.doc.style, "customer").then((r) => r.message && frm.set_value("customer", r.message.customer));
		}
	},
	excess_percent: (frm) => frm.vt_recalc(),
	exchange_rate: (frm) => frm.vt_recalc(),
	quoted_fob_fc: (frm) => frm.vt_recalc(),
	quoted_cnf_fc: (frm) => frm.vt_recalc(),
	price_basis: (frm) => frm.vt_recalc(),
	quantity_pcs: (frm) => frm.vt_recalc(),
	currency: (frm) => render_summary(frm),
});

for (const table of ["Cost Sheet Fabric", "Cost Sheet Accessory"]) {
	frappe.ui.form.on(table, {
		usage_per_pc: (frm) => frm.vt_recalc(),
		unit_cost: (frm) => frm.vt_recalc(),
		fabrics_remove: (frm) => frm.vt_recalc(),
		accessories_remove: (frm) => frm.vt_recalc(),
	});
}
frappe.ui.form.on("Cost Sheet Head", {
	rate_or_percent: (frm) => frm.vt_recalc(),
	cost_head: (frm) => frm.vt_recalc(),
	costs_remove: (frm) => frm.vt_recalc(),
});

function recalculate(frm) {
	if (frm.doc.docstatus !== 0 || frm.doc.status === "Pending Approval") return;
	frm.call({ method: "recalculate", doc: frm.doc }).then(() => {
		frm.refresh_fields();
		render_summary(frm);
		frm.dirty();
	});
}

function call_action(method, args, frm, message) {
	return frappe
		.call({ method: CS_METHOD + method, args, freeze: true })
		.then((r) => {
			if (message) frappe.show_alert({ message, indicator: "green" });
			return r.message;
		});
}

function add_buttons(frm) {
	if (frm.is_new()) return;
	const status = frm.doc.status;
	const onload = frm.doc.__onload || {};
	if (frm.doc.docstatus === 0 && ["Draft", "Rejected"].includes(status) && frm.has_perm("write")) {
		frm.add_custom_button(__("Submit for Approval"), () => {
			const go = () => call_action("submit_for_approval", { cost_sheet: frm.doc.name }, frm, __("Submitted for approval")).then(() => frm.reload_doc());
			frm.is_dirty() ? frm.save().then(go) : go();
		}).addClass("btn-primary");
	}
	if (status === "Pending Approval" && onload.is_approver) {
		frm.add_custom_button(__("Approve"), () => {
			frappe.confirm(__("Approve Cost Sheet {0}? It will be submitted and become the basis for orders.", [frm.doc.name]), () =>
				call_action("approve", { cost_sheet: frm.doc.name }, frm, __("Approved")).then(() => frm.reload_doc())
			);
		}).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for rejection"), reqd: 1 },
				(v) => call_action("reject", { cost_sheet: frm.doc.name, reason: v.reason }, frm, __("Rejected")).then(() => frm.reload_doc()),
				__("Reject Cost Sheet"),
				__("Reject")
			);
		});
	}
	if (status === "Approved" && frappe.model.can_create("Cost Sheet")) {
		frm.add_custom_button(__("Revise"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for the revision"), reqd: 1 },
				(v) =>
					call_action("revise", { cost_sheet: frm.doc.name, reason: v.reason }, frm).then((name) =>
						frappe.set_route("Form", "Cost Sheet", name)
					),
				__("Revise Cost Sheet"),
				__("Create Revision")
			);
		});
	}
	if (frappe.model.can_create("Cost Sheet")) {
		frm.add_custom_button(
			__("Copy to New Style"),
			() => {
				const dialog = new frappe.ui.Dialog({
					title: __("Copy to New Style"),
					fields: [{ fieldname: "style", fieldtype: "Link", options: "Style", label: __("Style"), reqd: 1 }],
					primary_action_label: __("Create Copy"),
					primary_action(v) {
						call_action("copy_to_style", { cost_sheet: frm.doc.name, style: v.style }, frm).then((name) => {
							dialog.hide();
							frappe.set_route("Form", "Cost Sheet", name);
						});
					},
				});
				dialog.show();
			},
			__("Create")
		);
	}
}

function show_status(frm) {
	const esc = frappe.utils.escape_html;
	const onload = frm.doc.__onload || {};
	if (frm.doc.status === "Pending Approval") {
		frm.dashboard.set_headline_alert(__("Waiting for approval. The Cost Sheet cannot be changed until it is approved or rejected."), "orange");
	} else if (frm.doc.status === "Rejected" && frm.doc.rejection_reason) {
		frm.dashboard.set_headline_alert(`${__("Rejected")}: ${esc(frm.doc.rejection_reason)}`, "red");
	} else if (frm.doc.status === "Superseded") {
		frm.dashboard.set_headline_alert(
			onload.current_revision
				? __("Superseded by {0}.", [`<a href="/desk/cost-sheet/${encodeURIComponent(onload.current_revision)}">${esc(onload.current_revision)}</a>`])
				: __("Superseded by a newer revision."),
			"gray"
		);
	} else if (frm.doc.status === "Approved") {
		frm.dashboard.set_headline_alert(
			__("Approved by {0} on {1}.", [esc(frappe.user.full_name(frm.doc.approved_by)), frappe.datetime.str_to_user(frm.doc.approved_on)]),
			"green"
		);
	} else {
		frm.dashboard.clear_headline();
	}
}

/** Costing sheet: cost heads by section with subtotals, PKR and order currency side by side. */
function render_summary(frm) {
	const field = frm.get_field("summary_html");
	if (!field) return;
	const doc = frm.doc;
	const esc = frappe.utils.escape_html;
	const fc = esc(doc.currency || "");
	const rate = flt(doc.exchange_rate);
	const pkr = (v) => format_number(flt(v), null, 2);
	const toFc = (v) => (rate ? format_number(flt(flt(v) / rate, 2), null, 2) : "–");
	const target = flt((doc.__onload || {}).target_margin || 15);
	const rows = doc.costs || [];
	if (!rows.length) {
		field.$wrapper.html(`<div class="vt-empty">${__("Cost heads load when the Cost Sheet is calculated.")}</div>`);
		return;
	}
	let body = "";
	for (const section of CS_SECTIONS) {
		const lines = rows.filter((r) => r.section === section);
		if (!lines.length) continue;
		const subtotal = lines.reduce((t, r) => t + flt(r.amount_pkr), 0);
		body += `<tr class="vt-costing__section"><td colspan="4">${__(section)}${
			section === "Freight" ? ` <span class="vt-muted">· ${__("CNF only")}</span>` : ""
		}</td></tr>`;
		body += lines
			.map((r) => {
				const rateText =
					r.calculation === "Percent of Quoted FOB"
						? `${format_number(flt(r.rate_or_percent), null, 2)}%`
						: r.calculation === "Computed"
						? `<span class="vt-muted">${__("computed")}</span>`
						: pkr(r.rate_or_percent);
				const dim = !flt(r.amount_pkr) ? "vt-costing__zero" : "";
				return `<tr class="${dim}"><td>${esc(r.cost_head)}</td><td class="vt-num">${rateText}</td>
					<td class="vt-num">${pkr(r.amount_pkr)}</td><td class="vt-num">${toFc(r.amount_pkr)}</td></tr>`;
			})
			.join("");
		body += `<tr class="vt-costing__subtotal"><td>${__("Subtotal")}</td><td></td><td class="vt-num">${pkr(subtotal)}</td><td class="vt-num">${toFc(subtotal)}</td></tr>`;
	}
	const cnf = doc.price_basis === "CNF";
	const result = (label, costed, quoted, profit, percent) => {
		const ok = flt(percent) >= target;
		return `<div class="vt-costing__result ${ok ? "is-ok" : "is-bad"}">
			<div class="vt-costing__result-title">${label}</div>
			<div class="vt-costing__tiles">
				<div><span>${__("Costed")}</span><b>${pkr(costed)}</b><small>${toFc(costed)} ${fc}</small></div>
				<div><span>${__("Quoted")}</span><b>${pkr(quoted)}</b><small>${toFc(quoted)} ${fc}</small></div>
				<div><span>${__("Profit")}</span><b>${pkr(profit)}</b><small>${toFc(profit)} ${fc}</small></div>
				<div class="vt-costing__pct"><span>${__("Profit %")}</span><b>${format_number(flt(percent), null, 2)}%</b>
					<small>${ok ? __("At or above the {0}% target", [target]) : __("Below the {0}% target", [target])}</small></div>
			</div>
		</div>`;
	};
	field.$wrapper.html(`
		<div class="vt-costing">
			<div class="vt-costing__meta">${__("Per piece · PKR and {0} at {1}", [fc || "–", format_number(rate, null, 4)])}${
		flt(doc.excess_percent) ? ` · ${__("fabric and accessories include {0}% excess", [flt(doc.excess_percent)])}` : ""
	}</div>
			<div class="vt-costing__grid">
				<div class="vt-table-wrap vt-costing__wrap"><table class="vt-table vt-costing__table">
					<thead><tr><th>${__("Cost Head")}</th><th class="vt-num">${__("Rate / %")}</th><th class="vt-num">PKR</th><th class="vt-num">${fc}</th></tr></thead>
					<tbody>${body}</tbody>
					<tfoot><tr><td>${__("Costed FOB")}</td><td></td><td class="vt-num">${pkr(doc.costed_fob_pkr)}</td><td class="vt-num">${toFc(doc.costed_fob_pkr)}</td></tr></tfoot>
				</table></div>
				<div class="vt-stack">
					${result(__("FOB"), doc.costed_fob_pkr, doc.quoted_fob_pkr, doc.profit_fob_pkr, doc.profit_fob_percent)}
					${cnf ? result(__("CNF"), doc.costed_cnf_pkr, doc.quoted_cnf_pkr, doc.profit_cnf_pkr, doc.profit_cnf_percent) : ""}
					<div class="vt-card vt-costing__totals">
						<div class="vt-card__title">${__("Whole Order ({0} pcs, PKR)", [format_number(doc.quantity_pcs || 0, null, 0)])}</div>
						<div><span>${__("Costed value")}</span><b>${pkr(doc.total_costed_value)}</b></div>
						<div><span>${__("Quoted value")}</span><b>${pkr(doc.total_quoted_value)}</b></div>
						<div><span>${__("Profit")}</span><b>${pkr(doc.total_profit)}</b></div>
					</div>
				</div>
			</div>
		</div>`);
}
