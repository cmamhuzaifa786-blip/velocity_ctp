// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const DIS_METHOD = "velocity_ctp.velocity_ctp.doctype.department_issue.department_issue.";

frappe.ui.form.on("Department Issue", {
	setup(frm) {
		frm.set_query("item", "items", () => ({
			filters: { item_group: ["descendants of (inclusive)", "Non-Product"], disabled: 0, is_stock_item: 1 },
		}));
		frm.set_query("warehouse", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("against_issue", () => ({
			filters: { docstatus: 1, issue_type: "Issue", company: frm.doc.company },
		}));
	},

	onload(frm) {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
		if (frm.is_new()) frm.trigger("load_defaults");
	},

	refresh(frm) {
		if (frm.doc.stock_entry) {
			frm.add_custom_button(__("Stock Entry"), () => frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry), __("View"));
			frm.add_custom_button(
				__("Accounting Ledger"),
				() =>
					frappe.set_route("query-report", "General Ledger", {
						company: frm.doc.company,
						voucher_no: frm.doc.stock_entry,
						from_date: frm.doc.posting_date,
						to_date: frm.doc.posting_date,
						group_by: "Group by Voucher (Consolidated)",
					}),
				__("View")
			);
		}
		if (frm.doc.docstatus === 1 && frm.doc.issue_type === "Issue") {
			frm.add_custom_button(__("Return"), () => {
				frappe.new_doc("Department Issue", {
					issue_type: "Return",
					against_issue: frm.doc.name,
					department: frm.doc.department,
					warehouse: frm.doc.warehouse,
					job_map: frm.doc.job_map,
					purpose: __("Return of unused items from {0}", [frm.doc.name]),
				});
			}, __("Create"));
		}
	},

	department: (frm) => frm.trigger("load_defaults"),

	load_defaults(frm) {
		frappe
			.call(DIS_METHOD + "get_defaults", { department: frm.doc.department, company: frm.doc.company })
			.then((r) => {
				const d = r.message || {};
				if (frm.doc.docstatus !== 0) return;
				if (!frm.doc.warehouse && d.warehouse) frm.set_value("warehouse", d.warehouse);
				frm.set_value("expense_account", d.expense_account || null);
				frm.set_value("cost_center", d.cost_center || null);
			});
	},

	against_issue(frm) {
		if (!frm.doc.against_issue || frm.doc.docstatus !== 0) return;
		frappe.call(DIS_METHOD + "get_return_items", { against_issue: frm.doc.against_issue }).then((r) => {
			frm.clear_table("items");
			(r.message || []).forEach((d) => frm.add_child("items", { item: d.item, qty: d.qty, rate: d.rate, amount: d.qty * d.rate }));
			frm.refresh_field("items");
		});
	},
});
