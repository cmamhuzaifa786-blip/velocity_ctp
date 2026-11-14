// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const AIS_METHOD = "velocity_ctp.velocity_ctp.doctype.accessory_issue.accessory_issue.";
const AIS_ALLOC = "velocity_ctp.velocity_ctp.doctype.accessory_allocation.accessory_allocation.";

frappe.ui.form.on("Accessory Issue", {
	setup(frm) {
		frm.set_query("job_map", () => (frm.doc.issue_type === "Return" ? {} : { filters: { job_closed: 0 } }));
		frm.set_query("garment_order", () => ({ filters: { name: ["in", frm.vt_orders || []] } }));
		frm.set_query("to_process", () => ({ filters: { is_active: 1 } }));
		frm.set_query("item", "items", () => ({
			filters: { item_group: ["descendants of (inclusive)", "Accessories & Trims"], disabled: 0, is_stock_item: 1 },
		}));
		frm.set_query("store", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},

	onload(frm) {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
		if (frm.is_new() && !frm.doc.store && frm.doc.company) {
			frappe.db
				.get_value("Warehouse", { warehouse_name: "Trim Store", company: frm.doc.company }, "name")
				.then((r) => r.message && r.message.name && frm.set_value("store", r.message.name));
		}
	},

	refresh(frm) {
		frm.trigger("load_options");
		frm.trigger("describe");
		if (frm.doc.stock_entry) {
			frm.add_custom_button(__("Stock Entry"), () => frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry), __("View"));
		}
		if (frm.doc.docstatus === 0) frm.trigger("refresh_balances");
	},

	issue_type(frm) {
		frm.trigger("describe");
		frm.trigger("refresh_balances");
	},
	job_map: (frm) => frm.trigger("load_options"),
	garment_order(frm) {
		frm.trigger("load_options");
		frm.trigger("refresh_balances");
	},
	to_process(frm) {
		frm.trigger("describe");
		frm.trigger("refresh_balances");
	},
	store: (frm) => frm.trigger("refresh_balances"),

	describe(frm) {
		const wip = frm.doc.wip_warehouse || __("the process's WIP warehouse");
		const store = frm.doc.store || __("the store");
		frm.set_df_property(
			"items",
			"description",
			frm.doc.issue_type === "Return"
				? __("Returning from {0} to {1}. Available = issued less returned for this job and process.", [wip, store])
				: __("Issuing from {0} to {1}. Allocated Balance = unissued allocation of this job.", [store, wip])
		);
	},

	load_options(frm) {
		if (!frm.doc.job_map) return;
		frappe
			.call(AIS_ALLOC + "get_job_options", { job_map: frm.doc.job_map, garment_order: frm.doc.garment_order })
			.then((r) => {
				const data = r.message || {};
				frm.vt_orders = data.orders || [];
				if (frm.doc.docstatus === 0 && !frm.doc.garment_order && frm.vt_orders.length === 1) {
					frm.set_value("garment_order", frm.vt_orders[0]);
				}
				const grid = frm.fields_dict.items.grid;
				grid.update_docfield_property("colour", "options", data.colours || []);
				grid.update_docfield_property("size", "options", data.sizes || []);
			});
	},

	refresh_balances(frm) {
		const items = [...new Set((frm.doc.items || []).map((r) => r.item).filter(Boolean))];
		if (!items.length || !frm.doc.job_map || !frm.doc.garment_order) return;
		frappe
			.call(AIS_METHOD + "get_balances", {
				job_map: frm.doc.job_map,
				garment_order: frm.doc.garment_order,
				issue_type: frm.doc.issue_type,
				to_process: frm.doc.to_process,
				items,
				store: frm.doc.store,
				company: frm.doc.company,
			})
			.then((r) => {
				(frm.doc.items || []).forEach((row) => {
					const b = (r.message || {})[row.item];
					if (!b) return;
					frappe.model.set_value(row.doctype, row.name, {
						allocated_balance: b.has_allocation ? b.allocated : null,
						available_qty: b.available,
					});
				});
			});
	},
});

frappe.ui.form.on("Accessory Issue Item", {
	item: (frm) => frm.trigger("refresh_balances"),
	qty: (frm) => update_total(frm),
	items_remove: (frm) => update_total(frm),
});

function update_total(frm) {
	frm.set_value("total_qty", (frm.doc.items || []).reduce((t, r) => t + flt(r.qty), 0));
}
