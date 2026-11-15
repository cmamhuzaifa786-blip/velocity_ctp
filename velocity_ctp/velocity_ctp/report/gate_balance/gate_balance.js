// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.query_reports["Gate Balance"] = {
	filters: [
		{ fieldname: "party", label: __("Party"), fieldtype: "Data" },
		{ fieldname: "only_overdue", label: __("Only Overdue"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.overdue_days > 0 && ["overdue_days", "expected_return_date", "open_qty"].includes(column.fieldname)) {
			value = `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
