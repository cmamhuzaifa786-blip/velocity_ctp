// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Process", {
	setup(frm) {
		frm.set_query("wip_warehouse", () => ({ filters: { is_group: 0 } }));
		frm.set_query("next_process", (doc) => ({
			filters: { is_active: 1, name: ["!=", doc.name || ""] },
		}));
	},
});
