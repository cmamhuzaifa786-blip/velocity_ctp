// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.listview_settings["Cost Sheet"] = {
	add_fields: ["status", "profit_fob_percent"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const colours = { Draft: "red", "Pending Approval": "orange", Approved: "green", Rejected: "red", Superseded: "gray" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
