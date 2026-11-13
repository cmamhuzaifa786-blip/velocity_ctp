// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Size Set", {});

frappe.ui.form.on("Size Set Item", {
	sizes_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.sequence) {
			frappe.model.set_value(cdt, cdn, "sequence", row.idx);
		}
	},
});
