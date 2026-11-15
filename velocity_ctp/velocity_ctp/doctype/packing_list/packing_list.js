// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const PL_METHOD = "velocity_ctp.velocity_ctp.doctype.packing_list.packing_list.";

frappe.ui.form.on("Packing List", {
	setup(frm) {
		frm.set_query("garment_order", () => ({ filters: { docstatus: 1 } }));
	},

	onload() {
		frappe.require("/assets/velocity_ctp/css/velocity.css");
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1 && !frm.doc.delivery_note) {
			frm.add_custom_button(__("Create Delivery Note"), () => vt_create_delivery(frm)).addClass("btn-primary");
		}
		if (frm.doc.delivery_note) {
			frm.add_custom_button(__("Delivery Note"), () => frappe.set_route("Form", "Delivery Note", frm.doc.delivery_note), __("View"));
		}
		load_options(frm);
		render_summary(frm);
		if (frm.doc.docstatus === 0 && frm.doc.garment_order) {
			frm.add_custom_button(__("Pick from Bundles"), () => pick_from_bundles(frm));
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Print Packing List"), () => {
				const params = new URLSearchParams({ doctype: frm.doc.doctype, name: frm.doc.name, format: "Packing List", no_letterhead: 1 });
				window.open(`/printview?${params.toString()}`, "_blank");
			}).addClass("btn-primary");
		}
	},

	garment_order(frm) {
		load_options(frm);
	},
});

frappe.ui.form.on("Packing List Carton", {
	carton_from: (frm, cdt, cdn) => calculate(frm, cdt, cdn),
	carton_to: (frm, cdt, cdn) => calculate(frm, cdt, cdn),
	pcs_per_carton: (frm, cdt, cdn) => calculate(frm, cdt, cdn),
	colour: (frm) => render_summary(frm),
	size: (frm) => render_summary(frm),
	cartons_remove: (frm) => calculate(frm),
	cartons_add(frm, cdt, cdn) {
		const rows = frm.doc.cartons || [];
		const last = rows.length > 1 ? rows[rows.length - 2] : null;
		if (last && cint(last.carton_to)) {
			frappe.model.set_value(cdt, cdn, "carton_from", cint(last.carton_to) + 1);
		}
	},
});

function calculate(frm, cdt, cdn) {
	if (cdt && cdn) {
		const row = locals[cdt][cdn];
		const cartons = cint(row.carton_to) >= cint(row.carton_from) && cint(row.carton_from) > 0 ? cint(row.carton_to) - cint(row.carton_from) + 1 : 0;
		row.no_of_cartons = cartons;
		row.total_pcs = cartons * cint(row.pcs_per_carton);
	}
	frm.doc.total_cartons = (frm.doc.cartons || []).reduce((t, r) => t + cint(r.no_of_cartons), 0);
	frm.doc.total_pcs = (frm.doc.cartons || []).reduce((t, r) => t + cint(r.total_pcs), 0);
	frm.refresh_fields(["cartons", "total_cartons", "total_pcs"]);
	render_summary(frm);
}

function load_options(frm) {
	if (!frm.doc.style) return Promise.resolve();
	return frappe
		.call("velocity_ctp.velocity_ctp.doctype.style.style.get_matrix_layout", { style: frm.doc.style })
		.then((r) => {
			frm.vt_layout = r.message || { colours: [], sizes: [] };
			const grid = frm.fields_dict.cartons.grid;
			grid.update_docfield_property("colour", "options", frm.vt_layout.colours);
			grid.update_docfield_property("size", "options", frm.vt_layout.sizes);
			render_summary(frm);
		});
}

/** Read-only colour x size summary of the packed pieces (same look as the Garment Order matrix). */
function render_summary(frm) {
	const field = frm.get_field("summary_matrix");
	if (!field) return;
	const rows = (frm.doc.cartons || []).filter((r) => r.colour && r.size);
	if (!rows.length) {
		field.$wrapper.html("");
		return;
	}
	const esc = frappe.utils.escape_html;
	const layout = frm.vt_layout || { sizes: [] };
	const used = new Set(rows.map((r) => r.size.toLowerCase()));
	let sizes = (layout.sizes || []).filter((s) => used.has(s.toLowerCase()));
	rows.forEach((r) => {
		if (!sizes.some((s) => s.toLowerCase() === r.size.toLowerCase())) sizes.push(r.size);
	});
	const colours = [...new Set(rows.map((r) => r.colour))];
	const cell = (c, s) =>
		rows
			.filter((r) => r.colour === c && r.size.toLowerCase() === s.toLowerCase())
			.reduce((t, r) => t + cint(r.total_pcs), 0);
	const body = colours
		.map((c) => {
			const vals = sizes.map((s) => cell(c, s));
			return `<tr><th class="vt-matrix__colour" scope="row">${esc(c)}</th>${vals
				.map((v) => `<td><span class="vt-matrix__value">${v || "–"}</span></td>`)
				.join("")}<td class="vt-matrix__total">${vals.reduce((a, b) => a + b, 0)}</td></tr>`;
		})
		.join("");
	const totals = sizes.map((s) => colours.reduce((t, c) => t + cell(c, s), 0));
	field.$wrapper.html(`
		<div class="vt-matrix">
			<div class="vt-matrix__bar"><div class="vt-matrix__summary">${__("Packed pieces by colour and size")} ·
				<b>${format_number(frm.doc.total_pcs || 0, null, 0)}</b> ${__("pcs in")} <b>${frm.doc.total_cartons || 0}</b> ${__("cartons")}</div></div>
			<div class="vt-matrix__scroll"><table>
				<thead><tr><th class="vt-matrix__colour">${__("Colour / Size")}</th>${sizes.map((s) => `<th>${esc(s)}</th>`).join("")}
					<th class="vt-matrix__total">${__("Total")}</th></tr></thead>
				<tbody>${body}</tbody>
				<tfoot><tr><td class="vt-matrix__colour">${__("Total")}</td>${totals.map((v) => `<td>${v}</td>`).join("")}
					<td class="vt-matrix__total">${totals.reduce((a, b) => a + b, 0)}</td></tr></tfoot>
			</table></div>
		</div>`);
}

function pick_from_bundles(frm) {
	Promise.all([
		frappe.call(PL_METHOD + "get_available", { garment_order: frm.doc.garment_order }),
		frappe.call(PL_METHOD + "get_next_carton", { garment_order: frm.doc.garment_order, exclude: frm.is_new() ? null : frm.doc.name }),
	]).then(([avail, next]) => {
		const lines = avail.message || [];
		if (!lines.length) {
			frappe.msgprint(__("There are no finished pieces waiting to be packed for this order."));
			return;
		}
		const used = (frm.doc.cartons || []).reduce((m, r) => Math.max(m, cint(r.carton_to)), 0);
		const dialog = new frappe.ui.Dialog({
			title: __("Pick from Bundles"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("Finished pieces not yet packed:")}</p><ul>${lines
						.map((l) => `<li>${frappe.utils.escape_html(l.colour)} / ${frappe.utils.escape_html(l.size)}: <b>${l.qty}</b> ${__("pcs")} (${l.bundles} ${__("bundles")})</li>`)
						.join("")}</ul>`,
				},
				{ fieldname: "pcs_per_carton", fieldtype: "Int", label: __("Pcs / Carton"), default: 12, reqd: 1 },
				{ fieldname: "first_carton", fieldtype: "Int", label: __("First Carton No."), default: Math.max(cint(next.message), used + 1), reqd: 1 },
			],
			primary_action_label: __("Add Rows"),
			primary_action(values) {
				const per = cint(values.pcs_per_carton);
				if (per <= 0) return;
				let carton = cint(values.first_carton);
				(frm.doc.cartons || []).filter((r) => !r.colour).forEach((r) => frappe.model.clear_doc(r.doctype, r.name));
				lines.forEach((l) => {
					const full = Math.floor(l.qty / per);
					const rest = l.qty % per;
					if (full) {
						frm.add_child("cartons", { carton_from: carton, carton_to: carton + full - 1, colour: l.colour, size: l.size, pcs_per_carton: per });
						carton += full;
					}
					if (rest) {
						frm.add_child("cartons", { carton_from: carton, carton_to: carton, colour: l.colour, size: l.size, pcs_per_carton: rest });
						carton += 1;
					}
				});
				(frm.doc.cartons || []).forEach((r) => {
					r.no_of_cartons = cint(r.carton_to) - cint(r.carton_from) + 1;
					r.total_pcs = r.no_of_cartons * cint(r.pcs_per_carton);
				});
				calculate(frm);
				frm.dirty();
				dialog.hide();
			},
		});
		dialog.show();
	});
}


function vt_create_delivery(frm) {
	// Other submitted, undelivered Packing Lists of the same order can ship on the same Delivery Note.
	frappe.db
		.get_list("Packing List", {
			filters: { garment_order: frm.doc.garment_order, docstatus: 1, delivery_note: ["is", "not set"] },
			fields: ["name", "total_pcs", "total_cartons", "packing_date"],
			order_by: "packing_date asc",
		})
		.then((lists) => {
			const dialog = new frappe.ui.Dialog({
				title: __("Create Delivery Note"),
				fields: [
					{
						fieldname: "lists",
						fieldtype: "MultiCheck",
						label: __("Packing Lists of {0} to ship", [frm.doc.garment_order]),
						options: lists.map((l) => ({
							label: `${l.name} · ${l.total_pcs} ${__("pcs")} · ${l.total_cartons} ${__("cartons")}`,
							value: l.name,
							checked: l.name === frm.doc.name,
						})),
					},
				],
				primary_action_label: __("Create"),
				primary_action(values) {
					const names = values.lists || [];
					if (!names.length) return frappe.msgprint(__("Select at least one Packing List."));
					frappe
						.call({ method: "velocity_ctp.shipping.delivery.make_delivery_note", args: { packing_lists: names }, freeze: true })
						.then((r) => {
							dialog.hide();
							frappe.set_route("Form", "Delivery Note", r.message);
						});
				},
			});
			dialog.show();
		});
}