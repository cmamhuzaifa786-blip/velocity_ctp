// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Job Accessory Balance"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "job_map", label: __("Job Map"), fieldtype: "Link", options: "Job Map" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{
			fieldname: "item",
			label: __("Accessory"),
			fieldtype: "Link",
			options: "Item",
			get_query: () => ({ filters: { item_group: ["descendants of (inclusive)", "Accessories & Trims"] } }),
		},
		{ fieldname: "include_closed", label: __("Include Closed Job Maps"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "shortfall" && data.shortfall > 0) {
			value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "balance_to_issue" && data.required && data.balance_to_issue === 0) {
			value = `<span style="color:var(--green-600)">${value}</span>`;
		}
		return value;
	},
};
