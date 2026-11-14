// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Process Movement Report"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_days(frappe.datetime.get_today(), -30), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{
			fieldname: "process",
			label: __("Process"),
			fieldtype: "Link",
			options: "Process",
			get_query: () => ({ filters: { name: ["not in", ["Cutting", "Packing"]] } }),
		},
		{ fieldname: "party", label: __("Party"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
	],
};
