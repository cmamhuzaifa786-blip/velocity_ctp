// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Order Costing"] = {
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Open", "On Hold", "In Production", "Completed"],
		},
		{ fieldname: "only_costed", label: __("Only Orders with a Cost Sheet"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "estimated_profit_percent" && data.estimated_profit_percent !== null && data.estimated_profit_percent !== undefined) {
			const ok = data.estimated_profit_percent >= data.target_margin;
			value = `<span style="font-weight:600;color:var(--${ok ? "green" : "red"}-600)">${value}</span>`;
		}
		if (column.fieldname === "fabric_variance" && data.fabric_variance) {
			value = `<span style="color:var(--${data.fabric_variance > 0 ? "red" : "green"}-600)">${value}</span>`;
		}
		return value;
	},
};
