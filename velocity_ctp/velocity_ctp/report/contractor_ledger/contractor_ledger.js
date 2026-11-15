// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Contractor Ledger"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "supplier", label: __("Contractor"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "from_date", label: __("Work From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Work To"), fieldtype: "Date" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["unbilled", "outstanding"].includes(column.fieldname) && data[column.fieldname] > 0) {
			value = `<span style="color:var(--orange-600);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
