// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Supplier Performance"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("PO Date From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6), reqd: 1 },
		{ fieldname: "to_date", label: __("PO Date To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "po_category", label: __("Category"), fieldtype: "Select", options: ["", "Fabric", "Accessory", "Non-Product", "Service"] },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "on_time_pct" && data.on_time_pct !== null && data.on_time_pct !== undefined) {
			const colour = data.on_time_pct >= 90 ? "green" : data.on_time_pct >= 70 ? "orange" : "red";
			value = `<span style="font-weight:600;color:var(--${colour}-600)">${value}</span>`;
		}
		if (["rejection_pct", "inspection_rejection_pct"].includes(column.fieldname) && data[column.fieldname] > 0) {
			value = `<span style="color:var(--red-600)">${value}</span>`;
		}
		if (column.fieldname === "overdue_rows" && data.overdue_rows > 0) {
			value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
