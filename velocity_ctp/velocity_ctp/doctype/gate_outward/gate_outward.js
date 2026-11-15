// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const GATE = "velocity_ctp.shipping.gate.";
const GATE_REFERENCES = { Delivery: "Delivery Note", "Process Challan": "Process Issue", "Purchase Return": "Purchase Receipt" };

frappe.ui.form.on("Gate Outward", {
	setup(frm) {
		frm.set_query("reference_doctype", () => ({ filters: { name: ["in", Object.values(GATE_REFERENCES)] } }));
		frm.set_query("reference_name", () => {
			const filters = { docstatus: 1 };
			if (frm.doc.reference_doctype === "Purchase Receipt") filters.is_return = 1;
			return { filters };
		});
		frm.set_query("party_type", () => ({ filters: { name: ["in", ["Customer", "Supplier"]] } }));
	},

	refresh(frm) {
		frm.trigger("toggle_reference");
		if (frm.doc.docstatus === 1 && flt(frm.doc.open_returnable_qty) > 0) {
			frm.add_custom_button(__("Gate Inward (Return)"), () =>
				frappe.new_doc("Gate Inward", {
					gate_pass_type: frm.doc.gate_pass_type === "Repair" ? "Repair Return" : "Other",
					against_gate_outward: frm.doc.name,
					party_type: frm.doc.party_type,
					party: frm.doc.party,
				}), __("Create"));
		}
	},

	gate_pass_type(frm) {
		const reference = GATE_REFERENCES[frm.doc.gate_pass_type];
		frm.set_value("reference_doctype", reference || null);
		if (!reference) frm.set_value("reference_name", null);
		frm.trigger("toggle_reference");
	},

	toggle_reference(frm) {
		const needed = !!GATE_REFERENCES[frm.doc.gate_pass_type];
		frm.toggle_reqd("reference_name", needed);
		frm.set_df_property("reference_doctype", "read_only", needed ? 1 : 0);
	},

	reference_name(frm) {
		if (!frm.doc.reference_doctype || !frm.doc.reference_name || frm.doc.docstatus !== 0) return;
		frappe
			.call(GATE + "get_reference_items", { reference_doctype: frm.doc.reference_doctype, reference_name: frm.doc.reference_name })
			.then((r) => {
				const d = r.message || {};
				if (d.party) frm.set_value({ party_type: d.party_type, party: d.party });
				if (d.vehicle_no && !frm.doc.vehicle_no) frm.set_value("vehicle_no", d.vehicle_no);
				if (d.driver_name && !frm.doc.driver_name) frm.set_value("driver_name", d.driver_name);
				frm.clear_table("items");
				(d.items || []).forEach((row) => frm.add_child("items", row));
				frm.refresh_field("items");
			});
	},
});
