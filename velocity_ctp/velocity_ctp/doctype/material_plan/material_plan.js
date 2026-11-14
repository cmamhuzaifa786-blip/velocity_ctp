// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const MP_METHOD = "velocity_ctp.velocity_ctp.doctype.material_plan.material_plan.";

frappe.ui.form.on("Material Plan", {
	setup(frm) {
		frm.set_query("garment_order", () => ({ filters: { docstatus: 1, status: ["!=", "Cancelled"] } }));
		frm.set_query("fabric_item", "fabrics", () => ({ filters: { item_group: "Fabric", disabled: 0 } }));
		frm.set_query("accessory_item", "accessories", () => ({ filters: { disabled: 0, is_stock_item: 1 } }));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		load_order(frm);
		if (frm.doc.docstatus === 0 && frm.doc.garment_order) {
			frm.add_custom_button(__("Load from Cost Sheet"), () => load_cost_sheet(frm));
			for (const [label, basis] of [
				[__("Size-wise"), "Per Size"],
				[__("Colour-wise"), "Per Colour"],
				[__("Colour & Size-wise"), "Per Colour & Size"],
			]) {
				frm.add_custom_button(label, () => generate_rows(frm, basis), __("Generate Rows"));
			}
		}
		if (frm.doc.garment_order) {
			frm.add_custom_button(__("Check Availability"), () => check_availability(frm));
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Create Material Request"), () =>
				frappe
					.call({ method: MP_METHOD + "create_material_request", args: { material_plan: frm.doc.name }, freeze: true })
					.then((r) => r.message && frappe.set_route("Form", "Material Request", r.message))
			).addClass("btn-primary");
		}
		if (frm.doc.material_request) {
			frm.add_custom_button(__("Material Requests"), () => frappe.set_route("List", "Material Request", { material_plan: frm.doc.name }), __("View"));
		}
	},

	garment_order: (frm) => load_order(frm),
});

function load_order(frm) {
	if (!frm.doc.garment_order) return;
	frappe.call(MP_METHOD + "get_order_options", { garment_order: frm.doc.garment_order }).then((r) => {
		const o = (frm.vt_order = r.message || {});
		for (const [table, fields] of [["fabrics", ["colour"]], ["accessories", ["colour", "size"]]]) {
			const grid = frm.fields_dict[table].grid;
			fields.forEach((f) => grid.update_docfield_property(f, "options", f === "size" ? o.sizes : o.colours));
		}
		const esc = frappe.utils.escape_html;
		frm.get_field("quantities_html").$wrapper.html(`<div class="vt-mp__qty">
			<span>${__("Total")}: <b>${format_number(o.total || 0, null, 0)}</b></span>
			${(o.sizes || []).map((s) => `<span>${__("Size")} ${esc(s)}: <b>${o.by_size[s.toLowerCase()] || 0}</b></span>`).join("")}
			${(o.colours || []).map((c) => `<span>${esc(c)}: <b>${o.by_colour[c.toLowerCase()] || 0}</b></span>`).join("")}
		</div>`);
	});
}

function load_cost_sheet(frm) {
	frappe.call(MP_METHOD + "get_cost_sheet_lines", { garment_order: frm.doc.garment_order }).then((r) => {
		const d = r.message || {};
		(d.fabrics || []).forEach((row) => frm.add_child("fabrics", row));
		(d.accessories || []).forEach((row) => frm.add_child("accessories", row));
		frm.refresh_fields(["fabrics", "accessories"]);
		frm.dirty();
		frappe.show_alert({
			message: __("Loaded {0} fabric and {1} accessory lines from {2}.", [(d.fabrics || []).length, (d.accessories || []).length, d.cost_sheet]) +
				(d.skipped ? " " + __("{0} lines without a linked item were skipped.", [d.skipped]) : ""),
			indicator: "green",
		});
	});
}

function generate_rows(frm, basis) {
	const o = frm.vt_order || {};
	const dialog = new frappe.ui.Dialog({
		title: __("Generate {0} Rows", [__(basis)]),
		fields: [
			{ fieldname: "item", fieldtype: "Link", options: "Item", label: __("Accessory Item"), reqd: 1 },
			{ fieldname: "consumption", fieldtype: "Float", label: __("Consumption per Unit"), default: 1, reqd: 1 },
			{ fieldname: "excess", fieldtype: "Percent", label: __("Excess %"), default: 0 },
		],
		primary_action_label: __("Add Rows"),
		primary_action(v) {
			const rows = [];
			if (basis === "Per Size") (o.sizes || []).forEach((s) => rows.push({ size: s }));
			if (basis === "Per Colour") (o.colours || []).forEach((c) => rows.push({ colour: c }));
			if (basis === "Per Colour & Size") (o.colours || []).forEach((c) => (o.sizes || []).forEach((s) => rows.push({ colour: c, size: s })));
			rows.forEach((r) =>
				frm.add_child("accessories", { accessory_item: v.item, basis, consumption_per_unit: v.consumption, excess_percent: v.excess, ...r })
			);
			frm.refresh_field("accessories");
			frm.dirty();
			dialog.hide();
			frappe.show_alert({ message: __("{0} rows added. Save to calculate the quantities.", [rows.length]), indicator: "green" });
		},
	});
	dialog.show();
}

function check_availability(frm) {
	frappe
		.call({ method: MP_METHOD + "check_availability", args: frm.is_dirty() || frm.is_new() ? { doc: frm.doc } : { material_plan: frm.doc.name }, freeze: true })
		.then((r) => {
			const rows = r.message || [];
			const esc = frappe.utils.escape_html;
			const n = (v) => format_number(flt(v), null, 2).replace(/\.00$/, "");
			frm.get_field("availability_html").$wrapper.html(
				rows.length
					? `<div class="vt-table-wrap" style="margin:0"><table class="vt-table">
						<thead><tr><th>${__("Item")}</th><th>${__("UOM")}</th><th class="vt-num">${__("Required")}</th><th class="vt-num">${__("In Stock")}</th>
							<th class="vt-num">${__("On Purchase Order")}</th><th class="vt-num">${__("Requested")}</th><th class="vt-num">${__("Reserved by Other Plans")}</th>
							<th class="vt-num">${__("Shortfall")}</th></tr></thead>
						<tbody>${rows
							.map(
								(x) => `<tr class="vt-row--plain"><td><b>${esc(x.item_code)}</b><div class="vt-muted small">${esc(x.item_name || "")} · ${__(x.kind)}</div></td>
									<td>${esc(x.uom || "")}</td><td class="vt-num">${n(x.required)}</td><td class="vt-num">${n(x.in_stock)}</td>
									<td class="vt-num">${n(x.on_order)}</td><td class="vt-num">${n(x.requested)}</td><td class="vt-num">${n(x.reserved)}</td>
									<td class="vt-num">${flt(x.shortfall) > 0 ? `<span class="vt-short">${n(x.shortfall)}</span>` : `<span class="vt-covered">${__("Covered")}</span>`}</td></tr>`
							)
							.join("")}</tbody></table></div>
						<p class="vt-muted small" style="margin-top:8px">${__("Stock counts company warehouses except process WIP, contractor and rejection warehouses. Checked {0}.", [frappe.datetime.now_datetime()])}</p>`
					: `<div class="vt-empty">${__("Add fabric or accessory lines first.")}</div>`
			);
		});
}
