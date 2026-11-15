// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const CR_METHOD = "velocity_ctp.velocity_ctp.doctype.cut_receive.cut_receive.";

frappe.ui.form.on("Cut Receive", {
	setup(frm) {
		frm.set_query("job_map", () => ({ filters: { status: "Ready to Cut" } }));
		frm.set_query("service_order", () => ({
			query: "velocity_ctp.procurement.services.service_order_query",
			filters: { supplier: frm.doc.cutting_party },
		}));
		frm.set_query("cutting_marker", "markers", () => ({
			filters: { job_map: frm.doc.job_map || "", docstatus: 1, status: "Planned" },
		}));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.job_map) {
			frm.add_custom_button(__("Get Planned Markers"), () => get_markers(frm));
		}
		if (frm.doc.docstatus === 1 && cint(frm.doc.bundle_count) > 0) {
			frm.add_custom_button(__("Print Bundle Tickets"), () => print_tickets(frm)).addClass("btn-primary");
			frm.add_custom_button(
				__("Bundles"),
				() => frappe.set_route("List", "Bundle", { cut_receive: frm.doc.name }),
				__("View")
			);
		}
		if (frm.doc.stock_entry) {
			frm.add_custom_button(__("Stock Entry"), () => frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry), __("View"));
		}
		show_wastage(frm);
	},

	job_map(frm) {
		frm.clear_table("markers");
		frm.clear_table("pieces");
		frm.clear_table("fabric");
		frm.refresh_fields(["markers", "pieces", "fabric"]);
	},

	piece_rate: (frm) => calculate(frm),
	service_order(frm) {
		frm.set_df_property("piece_rate", "read_only", frm.doc.service_order ? 1 : 0);
		if (frm.doc.service_order) frappe.show_alert({ message: __("The rate comes from the Service Order when you save."), indicator: "blue" });
	},

	sync_markers(frm) {
		if (!(frm.doc.markers || []).some((r) => r.cutting_marker)) return;
		return frm.call({ method: "sync_from_markers", doc: frm.doc }).then(() => {
			frm.dirty();
			show_wastage(frm);
		});
	},
});

frappe.ui.form.on("Cut Receive Marker", {
	cutting_marker: (frm) => frm.trigger("sync_markers"),
	markers_remove: (frm) => frm.trigger("sync_markers"),
});

frappe.ui.form.on("Cut Receive Piece", {
	cut_qty: (frm) => calculate(frm),
	rejected_qty: (frm) => calculate(frm),
});

frappe.ui.form.on("Cut Receive Fabric", {
	used_qty: (frm) => calculate(frm),
});

function get_markers(frm) {
	frappe.call(CR_METHOD + "get_planned_markers", { job_map: frm.doc.job_map }).then((r) => {
		const existing = (frm.doc.markers || []).map((m) => m.cutting_marker);
		const add = (r.message || []).filter((m) => !existing.includes(m));
		if (!add.length) {
			frappe.msgprint(__("There are no other planned markers for this Job Map."));
			return;
		}
		(frm.doc.markers || []).filter((m) => !m.cutting_marker).forEach((m) => frappe.model.clear_doc(m.doctype, m.name));
		add.forEach((name) => frm.add_child("markers", { cutting_marker: name }));
		frm.refresh_field("markers");
		frm.trigger("sync_markers");
	});
}

function calculate(frm) {
	let planned = 0, cut = 0, rejected = 0, good = 0;
	(frm.doc.pieces || []).forEach((p) => {
		p.good_qty = cint(p.cut_qty) - cint(p.rejected_qty);
		planned += cint(p.planned_qty);
		cut += cint(p.cut_qty);
		rejected += cint(p.rejected_qty);
		good += p.good_qty;
	});
	const required = (frm.doc.fabric || []).reduce((t, f) => t + flt(f.required_qty), 0);
	const used = (frm.doc.fabric || []).reduce((t, f) => t + flt(f.used_qty), 0);
	Object.assign(frm.doc, {
		total_planned_qty: planned,
		total_cut_qty: cut,
		total_rejected_qty: rejected,
		total_good_qty: good,
		total_fabric_required: flt(required, 3),
		total_fabric_used: flt(used, 3),
		wastage_percent: required ? flt(((used - required) / required) * 100, 2) : 0,
		contractor_amount: frm.doc.cutting_party ? flt(good * flt(frm.doc.piece_rate), 2) : 0,
	});
	frm.refresh_fields([
		"pieces", "total_planned_qty", "total_cut_qty", "total_rejected_qty", "total_good_qty",
		"total_fabric_required", "total_fabric_used", "wastage_percent", "contractor_amount",
	]);
	frm.dirty();
	show_wastage(frm);
}

function show_wastage(frm) {
	frappe.db.get_single_value("Velocity Settings", "fabric_wastage_alert_percent").then((alert) => {
		const over = alert && flt(frm.doc.wastage_percent) > flt(alert);
		frm.set_df_property(
			"wastage_percent",
			"description",
			over
				? `<span class="text-warning">${__("Above the alert level of {0}%. You can still submit; a warning is recorded in the timeline.", [alert])}</span>`
				: __("Fabric used above the markers' requirement, as a percentage of the requirement.")
		);
	});
}

function print_tickets(frm) {
	frappe.db.get_single_value("Velocity Settings", "bundle_ticket_format").then((setting) => {
		const dialog = new frappe.ui.Dialog({
			title: __("Print Bundle Tickets"),
			fields: [
				{
					fieldname: "ticket_size",
					fieldtype: "Select",
					label: __("Ticket Size"),
					options: [
						{ value: "a4", label: __("A4 sheet") },
						{ value: "thermal", label: __("Thermal 4x2 inch") },
					],
					default: setting === "Thermal 4x2 inch" ? "thermal" : "a4",
				},
				{
					fieldtype: "HTML",
					options: `<p class="text-muted small">${__("{0} bundles from {1}.", [frm.doc.bundle_count, frm.doc.name])}</p>`,
				},
			],
			primary_action_label: __("Open Print View"),
			primary_action(values) {
				const params = new URLSearchParams({
					doctype: frm.doc.doctype,
					name: frm.doc.name,
					format: "Bundle Ticket",
					no_letterhead: 1,
					ticket_size: values.ticket_size,
					trigger_print: 1,
				});
				window.open(`/printview?${params.toString()}`, "_blank");
				dialog.hide();
			},
		});
		dialog.show();
	});
}
