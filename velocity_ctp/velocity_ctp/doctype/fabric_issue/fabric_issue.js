// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const FI_METHOD = "velocity_ctp.velocity_ctp.doctype.fabric_issue.fabric_issue.";

frappe.ui.form.on("Fabric Issue", {
	setup(frm) {
		frm.set_query("job_map", () =>
			frm.doc.issue_type === "Return"
				? { filters: { job_closed: 0 } }
				: { filters: { status: "Ready to Cut" } }
		);
		frm.set_query("fabric_item", "items", () => ({
			filters: { item_group: "Fabric", has_batch_no: 1, disabled: 0 },
		}));
		frm.set_query("batch_no", "items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				query: "erpnext.controllers.queries.get_batch_no",
				filters: { item_code: row.fabric_item, warehouse: frm.vt_source_warehouse },
			};
		});
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		frm.trigger("set_source_warehouse");
		if (frm.doc.stock_entry) {
			frm.add_custom_button(__("Stock Entry"), () => frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry), __("View"));
		}
	},

	issue_type(frm) {
		frm.trigger("set_source_warehouse");
		(frm.doc.items || []).forEach((row) => refresh_available(frm, row));
	},
	company: (frm) => frm.trigger("set_source_warehouse"),

	set_source_warehouse(frm) {
		frappe
			.call(FI_METHOD + "get_source_warehouse", { issue_type: frm.doc.issue_type, company: frm.doc.company })
			.then((r) => {
				frm.vt_source_warehouse = r.message;
				frm.set_df_property(
					"items",
					"description",
					frm.doc.issue_type === "Return"
						? __("Returning from {0} to Fabric Store.", [r.message])
						: __("Issuing from {0} to Cutting WIP.", [r.message])
				);
			});
	},
});

frappe.ui.form.on("Fabric Issue Item", {
	fabric_item(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "batch_no", null);
	},
	batch_no(frm, cdt, cdn) {
		refresh_available(frm, locals[cdt][cdn]);
	},
	qty: (frm) => update_total(frm),
	items_remove: (frm) => update_total(frm),
});

function refresh_available(frm, row) {
	if (!row.fabric_item || !row.batch_no) return;
	frappe
		.call(FI_METHOD + "get_available_qty", {
			fabric_item: row.fabric_item,
			batch_no: row.batch_no,
			issue_type: frm.doc.issue_type,
			company: frm.doc.company,
		})
		.then((r) => frappe.model.set_value(row.doctype, row.name, "available_qty", r.message));
}

function update_total(frm) {
	frm.set_value("total_qty", (frm.doc.items || []).reduce((t, r) => t + flt(r.qty), 0));
}
