// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["GRN Register"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{ fieldname: "supplier_lot_no", label: __("Lot"), fieldtype: "Data" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "rejected_qty" && data.rejected_qty > 0) {
			value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "excess_short" && data.excess_short) {
			value = `<span style="color:var(--${data.excess_short > 0 ? "orange" : "red"}-600)">${value}</span>`;
		}
		return value;
	},
};
