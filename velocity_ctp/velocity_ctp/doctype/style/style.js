// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Style", {
	setup(frm) {
		frm.set_query("size_set", () => ({ filters: { is_active: 1 } }));
		frm.set_query("product_category", () => ({ filters: { is_active: 1 } }));
		frm.set_query("wash_type", () => ({ filters: { is_active: 1 } }));
	},

	refresh(frm) {
		if (frm.is_new()) return;

		const complete = frm.doc.template_item && frm.doc.__onload && frm.doc.__onload.variants_complete;
		if (!complete) {
			frm.add_custom_button(__("Create Item Variants"), () => frm.trigger("create_item_variants"));
		}

		if (frm.doc.template_item) {
			frm.add_custom_button(__("View Variants"), () => {
				frappe.set_route("List", "Item", { variant_of: frm.doc.template_item });
			});
		}
	},

	create_item_variants(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Please save the Style before creating item variants."));
			return;
		}
		frappe.call({
			method: "velocity_ctp.velocity_ctp.doctype.style.style.create_item_variants",
			args: { style: frm.doc.name },
			freeze: true,
			freeze_message: __("Creating item variants..."),
			callback: () => frm.reload_doc(),
		});
	},
});
