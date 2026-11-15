// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const CBR_METHOD = "velocity_ctp.velocity_ctp.doctype.contractor_bill_run.contractor_bill_run.";

frappe.ui.form.on("Contractor Bill Run", {
	onload(frm) {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
		if (frm.is_new() && !frm.doc.from_date) {
			frm.set_value("from_date", frappe.datetime.month_start());
			frm.set_value("to_date", frappe.datetime.get_today());
		}
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Unbilled Work"), () => get_work(frm)).addClass("btn-primary");
		}
		if (frm.doc.purchase_invoice) {
			frm.add_custom_button(__("Purchase Invoice"), () => frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_invoice), __("View"));
		}
		frm.add_custom_button(__("Contractor Ledger"), () =>
			frappe.set_route("query-report", "Contractor Ledger", { supplier: frm.doc.supplier }), __("View"));
	},
});

function get_work(frm) {
	if (!frm.doc.supplier || !frm.doc.from_date || !frm.doc.to_date) {
		frappe.msgprint(__("Please select the contractor and the period first."));
		return;
	}
	frappe
		.call({
			method: CBR_METHOD + "get_unbilled_work",
			args: { supplier: frm.doc.supplier, from_date: frm.doc.from_date, to_date: frm.doc.to_date, company: frm.doc.company },
			freeze: true,
		})
		.then((r) => {
			const rows = r.message || [];
			frm.clear_table("items");
			rows.forEach((row) => frm.add_child("items", row));
			frm.refresh_field("items");
			frm.set_value("total_qty", rows.reduce((t, x) => t + flt(x.fresh_qty), 0));
			frm.set_value("total_amount", rows.reduce((t, x) => t + flt(x.amount), 0));
			frappe.show_alert({
				message: rows.length ? __("{0} rows of unbilled work added.", [rows.length]) : __("No unbilled work in this period."),
				indicator: rows.length ? "green" : "orange",
			});
		});
}
