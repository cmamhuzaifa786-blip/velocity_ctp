// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["PO Status"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "po_category", label: __("Category"), fieldtype: "Select", options: ["", "Fabric", "Accessory", "Non-Product", "Service"] },
		{ fieldname: "po_type", label: __("Type"), fieldtype: "Select", options: ["", "Regular", "Shortfall"] },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "from_date", label: __("PO Date From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("PO Date To"), fieldtype: "Date" },
		{ fieldname: "only_pending", label: __("Only Pending"), fieldtype: "Check", default: 1 },
		{ fieldname: "only_overdue", label: __("Only Overdue"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "days_overdue" && data.days_overdue > 0) {
			value = `<span style="font-weight:600;color:var(--red-600)">${value}</span>`;
		}
		if (column.fieldname === "approval_status" && data.approval_status && data.approval_status.startsWith(__("Pending"))) {
			value = `<span style="color:var(--orange-600);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
