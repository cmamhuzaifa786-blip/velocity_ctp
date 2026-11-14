// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const AAL_METHOD = "velocity_ctp.velocity_ctp.doctype.accessory_allocation.accessory_allocation.";

frappe.ui.form.on("Accessory Allocation", {
	setup(frm) {
		frm.set_query("job_map", () => ({ filters: { job_closed: 0 } }));
		frm.set_query("garment_order", () => ({
			filters: { name: ["in", frm.vt_orders || []] },
		}));
		frm.set_query("item", "items", () => ({
			filters: { item_group: ["descendants of (inclusive)", "Accessories & Trims"], disabled: 0, is_stock_item: 1 },
		}));
		frm.set_query("warehouse", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
	},

	onload(frm) {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
		if (frm.is_new() && !frm.doc.warehouse && frm.doc.company) {
			frappe.db
				.get_value("Warehouse", { warehouse_name: "Trim Store", company: frm.doc.company }, "name")
				.then((r) => r.message && r.message.name && frm.set_value("warehouse", r.message.name));
		}
	},

	refresh(frm) {
		frm.trigger("load_options");
		if (frm.doc.docstatus === 1 && ["Allocated", "Partly Issued"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Release Unissued"), () => {
				frappe.confirm(
					__("Release the quantity of this allocation that is not yet issued? It becomes free for other jobs."),
					() =>
						frappe
							.call({ method: AAL_METHOD + "release_unissued", args: { name: frm.doc.name }, freeze: true })
							.then(() => frm.reload_doc())
				);
			});
			frm.add_custom_button(__("Accessory Issue"), () => {
				frappe.new_doc("Accessory Issue", { job_map: frm.doc.job_map, garment_order: frm.doc.garment_order });
			}, __("Create"));
		}
		if (frm.doc.docstatus === 0) frm.trigger("refresh_available");
	},

	job_map(frm) {
		frm.trigger("load_options");
	},
	garment_order: (frm) => frm.trigger("load_options"),
	warehouse: (frm) => frm.trigger("refresh_available"),

	load_options(frm) {
		if (!frm.doc.job_map) return;
		frappe
			.call(AAL_METHOD + "get_job_options", { job_map: frm.doc.job_map, garment_order: frm.doc.garment_order })
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

	refresh_available(frm) {
		const items = [...new Set((frm.doc.items || []).map((r) => r.item).filter(Boolean))];
		if (!items.length || !frm.doc.warehouse) return;
		frappe
			.call(AAL_METHOD + "get_available_unallocated", {
				items,
				warehouse: frm.doc.warehouse,
				name: frm.is_new() ? null : frm.doc.name,
			})
			.then((r) => {
				(frm.doc.items || []).forEach((row) => {
					if (row.item && r.message[row.item] !== undefined && row.available_unallocated !== r.message[row.item]) {
						frappe.model.set_value(row.doctype, row.name, "available_unallocated", r.message[row.item]);
					}
				});
			});
	},
});

frappe.ui.form.on("Accessory Allocation Item", {
	item: (frm) => frm.trigger("refresh_available"),
	qty: (frm) => update_total(frm),
	items_remove: (frm) => update_total(frm),
});

function update_total(frm) {
	frm.set_value("total_qty", (frm.doc.items || []).reduce((t, r) => t + flt(r.qty), 0));
}
