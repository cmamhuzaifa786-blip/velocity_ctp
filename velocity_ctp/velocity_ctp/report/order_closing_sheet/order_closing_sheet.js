// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Order Closing Sheet"] = {
	tree: true,
	name_field: "row_id",
	parent_field: "parent_row",
	initial_depth: 0,
	filters: [
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "garment_order", label: __("Garment Order"), fieldtype: "Link", options: "Garment Order" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["", "Open", "On Hold", "In Production", "Completed"] },
	],
	after_datatable_render(datatable) {
		// Column definitions (actual or estimate) as header tooltips.
		(datatable.getColumns ? datatable.getColumns() : []).forEach((col) => {
			const description = col.docfield && col.docfield.description;
			if (description) $(datatable.wrapper).find(`.dt-cell--header[data-col-index="${col.colIndex}"]`).attr("title", description);
		});
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "short_excess_percent" && data.short_excess_percent) {
			value = `<span style="color:var(--${data.short_excess_percent < 0 ? "orange" : "blue"}-600)">${value}</span>`;
		}
		if (["production_margin_percent", "full_margin_percent"].includes(column.fieldname) && data[column.fieldname] !== null && data[column.fieldname] !== undefined) {
			value = `<span style="font-weight:600;color:var(--${data[column.fieldname] >= 0 ? "green" : "red"}-600)">${value}</span>`;
		}
		if (["commercial_costs", "other_costs"].includes(column.fieldname) && data[column.fieldname] !== null && data[column.fieldname] !== undefined) {
			value = `<span class="text-muted" title="${__("Estimate")}">${value}</span>`;
		}
		return value;
	},
};
