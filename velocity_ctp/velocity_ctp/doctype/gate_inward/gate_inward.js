// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gate Inward", {
	setup(frm) {
		frm.set_query("against_gate_outward", () => ({ filters: { docstatus: 1, open_returnable_qty: [">", 0] } }));
		frm.set_query("party_type", () => ({ filters: { name: ["in", ["Customer", "Supplier"]] } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Returnable Items"), () => get_returnables(frm));
		}
	},

	onload(frm) {
		if (frm.is_new() && frm.doc.against_gate_outward && !(frm.doc.items || []).length) get_returnables(frm);
	},
});

function get_returnables(frm) {
	if (!frm.doc.against_gate_outward) {
		frappe.msgprint(__("Select the Gate Outward the items went out on."));
		return;
	}
	frappe.call("velocity_ctp.shipping.gate.get_returnable_items", { gate_outward: frm.doc.against_gate_outward }).then((r) => {
		const rows = r.message || [];
		frm.clear_table("items");
		rows.forEach((row) => frm.add_child("items", row));
		frm.refresh_field("items");
		if (!rows.length) frappe.show_alert({ message: __("Nothing is still out on {0}.", [frm.doc.against_gate_outward]), indicator: "orange" });
	});
}
