// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Process Receive", {
	setup(frm) {
		frm.set_query("production_process", () => ({
			filters: { is_active: 1, name: ["not in", ["Cutting", "Packing"]] },
		}));
		frm.set_query("bundle", "bundles", () => ({
			query: "velocity_ctp.production.queries.receivable_bundles",
			filters: { process: frm.doc.production_process || "", party: frm.doc.party || "" },
		}));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		frm.trigger("toggle_fields");
		load_colours(frm);
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Scan Station"), () => frappe.set_route("scan-station"));
		}
		for (const [field, label] of [["stock_entry", __("Stock Entry")], ["repack_entry", __("Colour Change Entry")]]) {
			if (frm.doc[field]) {
				frm.add_custom_button(label, () => frappe.set_route("Form", "Stock Entry", frm.doc[field]), __("View"));
			}
		}
	},

	production_process: (frm) => frm.trigger("toggle_fields"),
	process_type: (frm) => frm.trigger("toggle_fields"),
	allow_rejection: (frm) => frm.trigger("toggle_fields"),
	allow_colour_change: (frm) => {
		frm.trigger("toggle_fields");
		load_colours(frm);
	},

	toggle_fields(frm) {
		const type = frm.doc.process_type;
		frm.toggle_reqd("party", type === "Outsourced");
		frm.toggle_display("party", type !== "In-house");
		const grid = frm.fields_dict.bundles.grid;
		grid.update_docfield_property("rejected_qty", "read_only", frm.doc.allow_rejection ? 0 : 1);
		grid.update_docfield_property("to_colour", "read_only", frm.doc.allow_colour_change ? 0 : 1);
		grid.refresh();
	},
});

frappe.ui.form.on("Process Receive Bundle", {
	bundle(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.bundle || !frm.doc.production_process) return;
		frappe
			.call("velocity_ctp.api.scan.scan", {
				barcode: row.bundle,
				process: frm.doc.production_process,
				action: "Receive",
				party: frm.doc.party || null,
			})
			.then((r) => {
				const res = r.message || {};
				if (!res.ok) {
					frappe.msgprint({ title: __("Bundle Cannot Be Received"), message: res.reason, indicator: "red" });
					frappe.model.set_value(cdt, cdn, "bundle", null);
					return;
				}
				const b = res.bundle;
				Object.assign(row, {
					process_issue: b.process_issue,
					garment_order: b.garment_order,
					colour: b.colour,
					size: b.size,
					issued_qty: b.issued_qty,
					fresh_qty: b.fresh_qty,
					rejected_qty: 0,
					repair_qty: 0,
				});
				frm.refresh_field("bundles");
				load_colours(frm);
			});
	},
	rejected_qty: (frm, cdt, cdn) => rebalance(frm, cdt, cdn),
	repair_qty: (frm, cdt, cdn) => rebalance(frm, cdt, cdn),
});

/** Keep fresh = issued - rejected - repair while the user edits rejected or repair. */
function rebalance(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const fresh = cint(row.issued_qty) - cint(row.rejected_qty) - cint(row.repair_qty);
	frappe.model.set_value(cdt, cdn, "fresh_qty", Math.max(0, fresh));
}

function load_colours(frm) {
	const bundles = (frm.doc.bundles || []).map((r) => r.bundle).filter(Boolean);
	if (!frm.doc.allow_colour_change || !bundles.length) return;
	frappe
		.call("velocity_ctp.velocity_ctp.doctype.process_receive.process_receive.get_colour_options", { bundles })
		.then((r) => {
			const all = new Set();
			Object.values(r.message || {}).forEach((list) => list.forEach((c) => all.add(c)));
			frm.fields_dict.bundles.grid.update_docfield_property("to_colour", "options", [...all]);
		});
}
