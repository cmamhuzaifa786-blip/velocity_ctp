// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Cutting Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "job_map", label: __("Job Map"), fieldtype: "Link", options: "Job Map" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{ fieldname: "cutting_party", label: __("Cutting Party"), fieldtype: "Link", options: "Supplier" },
	],
	tree: true,
	name_field: "row_id",
	parent_field: "parent_row",
	initial_depth: 1,
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "wastage_percent" && data && data.wastage_alert) {
			value = `<span class="text-danger" style="font-weight:600">${value}</span>`;
		}
		if (data && data.indent === 0 && ["job_map", "fabric_item", "batch_no"].includes(column.fieldname)) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
