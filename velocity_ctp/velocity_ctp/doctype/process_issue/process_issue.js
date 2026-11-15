// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.ui.form.on("Process Issue", {
	setup(frm) {
		frm.set_query("service_order", () => ({
			query: "velocity_ctp.procurement.services.service_order_query",
			filters: { supplier: frm.doc.party },
		}));
		frm.set_query("production_process", () => ({
			filters: { is_active: 1, name: ["not in", ["Cutting", "Packing"]] },
		}));
		frm.set_query("bundle", "bundles", () => ({
			query: "velocity_ctp.production.queries.issuable_bundles",
			filters: { process: frm.doc.production_process || "" },
		}));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Gate Outward"), () =>
				frappe.new_doc("Gate Outward", {
					gate_pass_type: "Process Challan",
					reference_doctype: "Process Issue",
					reference_name: frm.doc.name,
				}), __("Create"));
		}
		frm.trigger("toggle_party");
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Print Challan"), () => open_challan(frm)).addClass("btn-primary");
			frm.add_custom_button(
				__("Process Receive"),
				() =>
					frappe.new_doc("Process Receive", {
						production_process: frm.doc.production_process,
						party: frm.doc.party,
					}),
				__("Create")
			);
			if (frm.doc.stock_entry) {
				frm.add_custom_button(__("Stock Entry"), () => frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry), __("View"));
			}
		}
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Scan Station"), () => frappe.set_route("scan-station"));
		}
	},

	production_process(frm) {
		frm.trigger("toggle_party");
		if (frm.doc.production_process) {
			frappe.db.get_value("Process", frm.doc.production_process, "default_piece_rate").then((r) => {
				if (r.message && !flt(frm.doc.piece_rate)) frm.set_value("piece_rate", r.message.default_piece_rate);
			});
		}
	},

	process_type: (frm) => frm.trigger("toggle_party"),

	toggle_party(frm) {
		const type = frm.doc.process_type;
		const outsourced = type === "Outsourced" || (type === "Both" && !!frm.doc.party);
		frm.toggle_reqd("party", type === "Outsourced");
		frm.toggle_display("party", type !== "In-house");
		frm.toggle_display("service_order", outsourced);
		frm.toggle_reqd("service_order", outsourced);
		frm.set_df_property("piece_rate", "read_only", outsourced ? 1 : 0);
	},

	party: (frm) => frm.trigger("toggle_party"),
});

function open_challan(frm) {
	const params = new URLSearchParams({
		doctype: frm.doc.doctype,
		name: frm.doc.name,
		format: "Process Challan",
		no_letterhead: 1,
		trigger_print: 1,
	});
	window.open(`/printview?${params.toString()}`, "_blank");
}
