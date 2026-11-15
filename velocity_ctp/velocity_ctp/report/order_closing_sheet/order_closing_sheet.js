// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Order Closing Sheet"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["", "Open", "On Hold", "In Production", "Completed"] },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "short_excess_percent" && data.short_excess_percent) {
			value = `<span style="color:var(--${data.short_excess_percent < 0 ? "orange" : "blue"}-600)">${value}</span>`;
		}
		if (column.fieldname === "margin_percent" && data.margin_percent !== null && data.margin_percent !== undefined) {
			value = `<span style="font-weight:600;color:var(--${data.margin_percent >= 0 ? "green" : "red"}-600)">${value}</span>`;
		}
		return value;
	},
};
