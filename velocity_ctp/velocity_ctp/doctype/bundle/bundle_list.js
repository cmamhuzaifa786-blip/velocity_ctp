// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.listview_settings["Bundle"] = {
	add_fields: ["status", "current_process", "qty"],
	hide_name_column: false,
	get_indicator(doc) {
		const colours = { "In Cutting": "blue", Issued: "orange", Received: "purple", Completed: "green", Rejected: "red" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
