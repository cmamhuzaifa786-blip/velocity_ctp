// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.listview_settings["Job Map"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = {
			"Pending Approvals": "orange",
			"Ready to Cut": "green",
			"On Hold": "red",
			Closed: "gray",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
