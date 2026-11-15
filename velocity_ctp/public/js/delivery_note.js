// Velocity CTP additions to the standard Delivery Note form (loaded through doctype_js).
frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.is_return) {
			frm.add_custom_button(__("Gate Outward"), () =>
				frappe.new_doc("Gate Outward", {
					gate_pass_type: "Delivery",
					reference_doctype: "Delivery Note",
					reference_name: frm.doc.name,
					party_type: "Customer",
					party: frm.doc.customer,
				}), __("Create"));
		}
	},
});
