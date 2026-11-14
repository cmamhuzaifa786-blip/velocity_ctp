// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bundle", {
	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},
	refresh(frm) {
		if (frm.doc.cut_receive) {
			frm.add_custom_button(__("Cut Receive"), () => frappe.set_route("Form", "Cut Receive", frm.doc.cut_receive), __("View"));
		}
	},
});
