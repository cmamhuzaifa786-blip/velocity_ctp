// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.listview_settings["Garment Order"] = {
	add_fields: ["status", "ship_date", "docstatus"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const colours = {
			Draft: "red",
			Open: "blue",
			"On Hold": "orange",
			"In Production": "purple",
			Completed: "green",
			Cancelled: "gray",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
