// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const MK_METHOD = "velocity_ctp.velocity_ctp.doctype.cutting_marker.cutting_marker.";

frappe.ui.form.on("Cutting Marker", {
	setup(frm) {
		frm.set_query("job_map", () => ({ filters: { status: "Ready to Cut" } }));
		frm.set_query("garment_order", () => ({
			filters: { name: ["in", frm.vt_orders && frm.vt_orders.length ? frm.vt_orders : [""]] },
		}));
		frm.set_query("fabric_item", () => ({
			filters: { name: ["in", (frm.vt_batches || []).map((b) => b.fabric_item).concat([""])] },
		}));
		frm.set_query("batch_no", () => ({
			filters: {
				name: [
					"in",
					(frm.vt_batches || [])
						.filter((b) => !frm.doc.fabric_item || b.fabric_item === frm.doc.fabric_item)
						.map((b) => b.batch_no)
						.concat([""]),
				],
			},
		}));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		frm.trigger("load_options");
		if (frm.doc.docstatus === 1 && frm.doc.status === "Planned") {
			frm.add_custom_button(
				__("Cut Receive"),
				() => frappe.new_doc("Cut Receive", { job_map: frm.doc.job_map }),
				__("Create")
			);
		}
	},

	job_map(frm) {
		frm.trigger("load_options");
	},
	garment_order(frm) {
		frm.trigger("load_options");
	},

	load_options(frm) {
		if (!frm.doc.job_map) return;
		frappe
			.call(MK_METHOD + "get_order_options", { job_map: frm.doc.job_map, garment_order: frm.doc.garment_order })
			.then((r) => {
				const o = r.message || {};
				frm.vt_orders = o.orders || [];
				frm.set_df_property("colour", "options", o.colours || []);
				frm.fields_dict.size_ratio.grid.update_docfield_property("size", "options", o.sizes || []);
			});
		frappe.call(MK_METHOD + "get_issued_batches", { job_map: frm.doc.job_map }).then((r) => {
			frm.vt_batches = r.message || [];
			const batch = frm.vt_batches.find((b) => b.batch_no === frm.doc.batch_no);
			frm.set_df_property(
				"batch_no",
				"description",
				batch
					? __("{0} m of this batch is issued to the Job Map and not yet used.", [batch.balance])
					: __("Only batches issued to this Job Map can be used.")
			);
		});
	},

	batch_no: (frm) => frm.trigger("load_options"),
	marker_length: (frm) => calculate(frm),
	no_of_plies: (frm) => calculate(frm),
	end_loss_percent: (frm) => calculate(frm),
});

frappe.ui.form.on("Cutting Marker Size", {
	ratio: (frm) => calculate(frm),
	size_ratio_remove: (frm) => calculate(frm),
});

function calculate(frm) {
	const plies = cint(frm.doc.no_of_plies);
	(frm.doc.size_ratio || []).forEach((row) => (row.planned_pieces = cint(row.ratio) * plies));
	frm.refresh_field("size_ratio");
	frm.set_value("total_planned_pieces", (frm.doc.size_ratio || []).reduce((t, r) => t + cint(r.planned_pieces), 0));
	frm.set_value(
		"fabric_required",
		flt(flt(frm.doc.marker_length) * plies * (1 + flt(frm.doc.end_loss_percent) / 100), 3)
	);
}
