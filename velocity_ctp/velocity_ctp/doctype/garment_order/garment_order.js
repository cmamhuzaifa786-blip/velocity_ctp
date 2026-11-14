// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

const VT_CSS = "/assets/velocity_ctp/css/velocity.css";
const HOLD_ROLES = ["System Manager", "Velocity Merchandiser"];

frappe.ui.form.on("Garment Order", {
	setup(frm) {
		frm.set_query("style", () => ({
			filters: frm.doc.customer ? { customer: frm.doc.customer } : {},
		}));
	},

	onload(frm) {
		frappe.require(VT_CSS);
		if (frm.is_new()) {
			if (!frm.doc.company) {
				frm.set_value("company", frappe.defaults.get_user_default("Company"));
			} else if (!frm.doc.currency) {
				frm.trigger("company");
			}
		}
	},

	refresh(frm) {
		frm.toggle_display("items", !!frm.vt_show_rows);
		vt_matrix.load(frm);
		add_action_buttons(frm);
	},

	company(frm) {
		if (frm.doc.company && !frm.doc.currency) {
			frappe.db.get_value("Company", frm.doc.company, "default_currency").then((r) => {
				if (r.message && r.message.default_currency) {
					frm.set_value("currency", r.message.default_currency);
				}
			});
		}
	},

	customer(frm) {
		if (frm.doc.style && frm.vt_layout && frm.vt_layout.customer !== frm.doc.customer) {
			frm.set_value("style", null);
		}
	},

	style(frm) {
		frm.vt_layout = null;
		vt_matrix.load(frm).then(() => {
			const layout = frm.vt_layout;
			if (!layout) return;
			if (!frm.doc.customer && layout.customer) {
				frm.set_value("customer", layout.customer);
			}
			// Drop rows that do not belong to the newly selected style.
			const stale = (frm.doc.items || []).filter((row) => !vt_matrix.in_layout(layout, row));
			if (stale.length) {
				stale.forEach((row) => frappe.model.clear_doc(row.doctype, row.name));
				vt_matrix.after_change(frm);
				frappe.show_alert({
					message: __("{0} row(s) removed because they do not match the selected style.", [
						stale.length,
					]),
					indicator: "orange",
				});
			}
		});
	},

	excess_percent(frm) {
		(frm.doc.items || []).forEach((row) => vt_matrix.calc_row(frm, row));
		vt_matrix.after_change(frm);
	},
});

frappe.ui.form.on("Garment Order Item", {
	order_qty: (frm, cdt, cdn) => on_row_change(frm, cdt, cdn),
	rate: (frm, cdt, cdn) => on_row_change(frm, cdt, cdn),
	colour: (frm) => vt_matrix.render(frm),
	size: (frm) => vt_matrix.render(frm),
	items_remove: (frm) => vt_matrix.after_change(frm),
});

function on_row_change(frm, cdt, cdn) {
	vt_matrix.calc_row(frm, locals[cdt][cdn]);
	vt_matrix.after_change(frm);
}

function add_action_buttons(frm) {
	if (frm.doc.docstatus !== 1) return;

	if (!frm.doc.sales_order && frm.doc.status !== "Cancelled") {
		frm.add_custom_button(__("Create Sales Order"), () => {
			frappe.call({
				method: "velocity_ctp.velocity_ctp.doctype.garment_order.garment_order.make_sales_order",
				args: { garment_order: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating Sales Order..."),
				callback: (r) => {
					if (r.message) {
						frappe.show_alert({
							message: __("Sales Order {0} created", [r.message]),
							indicator: "green",
						});
						frappe.set_route("Form", "Sales Order", r.message);
					}
				},
			});
		}).addClass("btn-primary");
	}

	const can_hold = HOLD_ROLES.some((role) => frappe.user.has_role(role));
	if (!can_hold) return;

	if (!["Completed", "Cancelled"].includes(frm.doc.status)) {
		frm.add_custom_button(__("Update Ship Date"), () => update_ship_date(frm), __("Status"));
	}

	const set_hold = (hold) =>
		frappe.call({
			method: "velocity_ctp.velocity_ctp.doctype.garment_order.garment_order.set_hold",
			args: { garment_order: frm.doc.name, hold: hold ? 1 : 0 },
			freeze: true,
			callback: () => frm.reload_doc(),
		});

	if (frm.doc.status === "On Hold") {
		frm.add_custom_button(__("Resume"), () => set_hold(false), __("Status"));
	} else if (!["Completed", "Cancelled"].includes(frm.doc.status)) {
		frm.add_custom_button(
			__("Hold"),
			() => {
				frappe.confirm(__("Put this Garment Order on hold?"), () => set_hold(true));
			},
			__("Status")
		);
	}
}

function update_ship_date(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Update Ship Date"),
		fields: [
			{
				fieldname: "current",
				fieldtype: "Date",
				label: __("Current Ship Date"),
				default: frm.doc.ship_date,
				read_only: 1,
			},
			{ fieldname: "ship_date", fieldtype: "Date", label: __("New Ship Date"), reqd: 1 },
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				description: __("Optional. Added to the timeline with the change."),
			},
		],
		primary_action_label: __("Update"),
		primary_action(values) {
			frappe.call({
				method: "velocity_ctp.velocity_ctp.doctype.garment_order.garment_order.update_ship_date",
				args: { garment_order: frm.doc.name, ship_date: values.ship_date, reason: values.reason },
				freeze: true,
				callback: (r) => {
					if (r.exc) return;
					dialog.hide();
					frappe.show_alert({ message: __("Ship date updated"), indicator: "green" });
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
}

/**
 * Colour x size quantity matrix.
 *
 * The child table "items" stays the source of truth. The matrix reads from it and writes
 * back to it: a quantity above zero creates or updates the row, zero or blank removes it.
 */
const vt_matrix = {
	key: (colour, size) => `${(colour || "").toLowerCase()}\u0000${(size || "").toLowerCase()}`,

	in_layout(layout, row) {
		const colours = layout.colours.map((c) => c.toLowerCase());
		const sizes = layout.sizes.map((s) => s.toLowerCase());
		return (
			colours.includes((row.colour || "").toLowerCase()) &&
			sizes.includes((row.size || "").toLowerCase())
		);
	},

	load(frm) {
		const wrapper = frm.get_field("quantity_matrix").$wrapper;
		if (!frm.doc.style) {
			frm.vt_layout = null;
			wrapper.html(
				`<div class="vt-matrix"><div class="vt-matrix__empty">${__(
					"Select a style to enter quantities by colour and size."
				)}</div></div>`
			);
			return Promise.resolve();
		}
		if (frm.vt_layout && frm.vt_layout.style === frm.doc.style) {
			this.render(frm);
			return Promise.resolve();
		}
		return frappe
			.call({
				method: "velocity_ctp.velocity_ctp.doctype.style.style.get_matrix_layout",
				args: { style: frm.doc.style },
			})
			.then((r) => {
				frm.vt_layout = Object.assign({ style: frm.doc.style }, r.message || {});
				this.render(frm);
			});
	},

	row_map(frm) {
		const map = {};
		(frm.doc.items || []).forEach((row) => (map[this.key(row.colour, row.size)] = row));
		return map;
	},

	colour_rate(frm, colour) {
		const rates = (frm.doc.items || [])
			.filter((r) => (r.colour || "").toLowerCase() === colour.toLowerCase())
			.map((r) => flt(r.rate));
		if (!rates.length) return { value: "", mixed: false };
		const same = rates.every((r) => r === rates[0]);
		return { value: same && rates[0] ? rates[0] : "", mixed: !same };
	},

	render(frm) {
		const layout = frm.vt_layout;
		const wrapper = frm.get_field("quantity_matrix").$wrapper;
		if (!layout) return;

		const cutting = this.mode(frm) === "cutting";
		const field = cutting ? "cutting_qty" : "order_qty";
		const editable = frm.doc.docstatus === 0 && !cutting;
		const rows = this.row_map(frm);
		const esc = frappe.utils.escape_html;
		const unmatched = (frm.doc.items || []).filter((r) => !this.in_layout(layout, r)).length;

		if (!layout.colours.length || !layout.sizes.length) {
			wrapper.html(
				`<div class="vt-matrix"><div class="vt-matrix__empty">${__(
					"The selected style has no colours or its size set has no sizes."
				)}</div></div>`
			);
			return;
		}

		const head = layout.sizes.map((s) => `<th>${esc(s)}</th>`).join("");
		const body = layout.colours
			.map((colour) => {
				const cells = layout.sizes
					.map((size) => {
						const row = rows[this.key(colour, size)];
						const qty = row ? cint(row[field]) : "";
						if (!editable) {
							return `<td><span class="vt-matrix__value">${qty || "–"}</span></td>`;
						}
						return `<td><input type="number" min="0" step="1" inputmode="numeric"
							class="vt-qty ${qty ? "vt-has-value" : ""}"
							data-colour="${esc(colour)}" data-size="${esc(size)}"
							value="${qty}" aria-label="${esc(colour)} ${esc(size)}"></td>`;
					})
					.join("");
				const rate = this.colour_rate(frm, colour);
				const rate_cell = cutting
					? ""
					: editable
					? `<input type="number" min="0" step="any" class="vt-rate" data-colour="${esc(colour)}"
						value="${rate.value}" placeholder="${rate.mixed ? __("Mixed") : "0.00"}"
						aria-label="${__("Rate")} ${esc(colour)}">`
					: `<span class="vt-matrix__value">${
							rate.mixed ? __("Mixed") : format_currency(rate.value || 0, frm.doc.currency)
					  }</span>`;
				return `<tr data-colour="${esc(colour)}">
					<th scope="row" class="vt-matrix__colour" title="${esc(colour)}">${esc(colour)}</th>
					${cells}
					<td class="vt-matrix__total" data-row-total></td>
					${cutting ? "" : `<td class="vt-matrix__rate">${rate_cell}</td>`}
				</tr>`;
			})
			.join("");
		const foot = layout.sizes.map((s) => `<td data-col-total="${esc(s)}"></td>`).join("");
		const toggle_label = frm.vt_show_rows ? __("Hide detail rows") : __("Show detail rows");

		wrapper.html(`
			<div class="vt-matrix">
				<div class="vt-matrix__bar">
					<div class="vt-seg" role="group" aria-label="${__("Quantity shown")}">
						<button type="button" class="vt-seg__btn ${cutting ? "" : "is-active"}"
							data-matrix-mode="order" aria-pressed="${!cutting}">${__("Order Qty")}</button>
						<button type="button" class="vt-seg__btn ${cutting ? "is-active" : ""}"
							data-matrix-mode="cutting" aria-pressed="${cutting}">${__("Cutting Qty")}</button>
					</div>
					<div class="vt-matrix__summary" data-summary></div>
					<button type="button" class="btn btn-xs btn-default" data-toggle-rows>${toggle_label}</button>
				</div>
				${
					cutting
						? `<div class="vt-matrix__note">${__(
								"Cutting quantity = order quantity + {0}% excess per size. Switch to Order Qty to edit.",
								[flt(frm.doc.excess_percent)]
						  )}</div>`
						: ""
				}
				${
					unmatched
						? `<div class="vt-matrix__bar text-warning">${__(
								"{0} detail row(s) do not match this style's colours and sizes. Open the detail rows to review them.",
								[unmatched]
						  )}</div>`
						: ""
				}
				<div class="vt-matrix__scroll">
					<table>
						<thead><tr>
							<th class="vt-matrix__colour">${__("Colour / Size")}</th>
							${head}
							<th class="vt-matrix__total">${__("Total")}</th>
							${cutting ? "" : `<th>${__("Rate")}</th>`}
						</tr></thead>
						<tbody>${body}</tbody>
						<tfoot><tr>
							<td class="vt-matrix__colour">${__("Total")}</td>
							${foot}
							<td class="vt-matrix__total" data-grand-total></td>
							${cutting ? "" : "<td></td>"}
						</tr></tfoot>
					</table>
				</div>
			</div>`);

		this.update_totals(frm);
		this.bind(frm, wrapper);
	},

	mode(frm) {
		return frm.vt_matrix_mode === "cutting" ? "cutting" : "order";
	},

	bind(frm, wrapper) {
		wrapper.find("[data-matrix-mode]").on("click", (e) => {
			const mode = e.currentTarget.dataset.matrixMode;
			if (mode === this.mode(frm)) return;
			frm.vt_matrix_mode = mode;
			this.render(frm);
		});

		wrapper.find("[data-toggle-rows]").on("click", () => {
			frm.vt_show_rows = !frm.vt_show_rows;
			frm.toggle_display("items", frm.vt_show_rows);
			this.render(frm);
		});

		wrapper.find("input.vt-qty").on("input", () => this.update_totals(frm, wrapper));
		wrapper.find("input.vt-qty").on("change", (e) => {
			const input = e.currentTarget;
			const qty = Math.max(0, cint(input.value));
			input.value = qty || "";
			input.classList.toggle("vt-has-value", qty > 0);
			this.set_qty(frm, input.dataset.colour, input.dataset.size, qty);
		});
		wrapper.find("input.vt-qty").on("keydown", (e) => {
			// Enter moves down to the same size in the next colour, like a spreadsheet.
			if (e.key !== "Enter") return;
			e.preventDefault();
			const inputs = wrapper.find("input.vt-qty").toArray();
			const sizes = frm.vt_layout.sizes.length;
			const next = inputs[inputs.indexOf(e.currentTarget) + (e.shiftKey ? -sizes : sizes)];
			$(e.currentTarget).trigger("change");
			if (next) next.focus();
		});
		wrapper.find("input.vt-rate").on("change", (e) => {
			const input = e.currentTarget;
			if (input.value === "") return;
			this.set_rate(frm, input.dataset.colour, flt(input.value));
		});
	},

	set_qty(frm, colour, size, qty) {
		const row = this.row_map(frm)[this.key(colour, size)];
		if (qty > 0) {
			const target =
				row ||
				frm.add_child("items", {
					colour,
					size,
					rate: this.colour_rate(frm, colour).value || 0,
				});
			target.order_qty = qty;
			this.calc_row(frm, target);
		} else if (row) {
			frappe.model.clear_doc(row.doctype, row.name);
		} else {
			return;
		}
		this.after_change(frm, { keep_matrix: true });
	},

	set_rate(frm, colour, rate) {
		(frm.doc.items || [])
			.filter((r) => (r.colour || "").toLowerCase() === colour.toLowerCase())
			.forEach((r) => {
				r.rate = rate;
				this.calc_row(frm, r);
			});
		this.after_change(frm, { keep_matrix: true });
	},

	calc_row(frm, row) {
		const qty = cint(row.order_qty);
		row.excess_qty = Math.floor((qty * flt(frm.doc.excess_percent)) / 100 + 0.5);
		row.cutting_qty = qty + row.excess_qty;
		row.amount = flt(qty * flt(row.rate), precision("amount", row));
	},

	after_change(frm, opts = {}) {
		const items = frm.doc.items || [];
		const sum = (field) => items.reduce((total, r) => total + flt(r[field]), 0);
		frm.doc.total_order_qty = sum("order_qty");
		frm.doc.total_excess_qty = sum("excess_qty");
		frm.doc.total_cutting_qty = sum("cutting_qty");
		frm.doc.total_amount = sum("amount");
		frm.refresh_fields([
			"items",
			"total_order_qty",
			"total_excess_qty",
			"total_cutting_qty",
			"total_amount",
		]);
		frm.dirty();
		if (opts.keep_matrix) {
			this.update_totals(frm);
		} else {
			this.render(frm);
		}
	},

	/** Recalculate row, column and grand totals from the inputs (or the model when read only). */
	update_totals(frm, wrapper) {
		wrapper = wrapper || frm.get_field("quantity_matrix").$wrapper;
		const layout = frm.vt_layout;
		if (!layout) return;
		const rows = this.row_map(frm);
		const field = this.mode(frm) === "cutting" ? "cutting_qty" : "order_qty";
		const qty_of = (colour, size) => {
			const input = wrapper.find(
				`input.vt-qty[data-colour="${CSS.escape(colour)}"][data-size="${CSS.escape(size)}"]`
			);
			if (input.length) return Math.max(0, cint(input.val()));
			const row = rows[this.key(colour, size)];
			return row ? cint(row[field]) : 0;
		};

		const col_totals = {};
		let grand = 0;
		layout.colours.forEach((colour) => {
			let row_total = 0;
			layout.sizes.forEach((size) => {
				const qty = qty_of(colour, size);
				row_total += qty;
				col_totals[size] = (col_totals[size] || 0) + qty;
			});
			grand += row_total;
			wrapper
				.find(`tr[data-colour="${CSS.escape(colour)}"] [data-row-total]`)
				.text(format_number(row_total, null, 0));
		});
		layout.sizes.forEach((size) =>
			wrapper
				.find(`[data-col-total="${CSS.escape(size)}"]`)
				.text(format_number(col_totals[size] || 0, null, 0))
		);
		wrapper.find("[data-grand-total]").text(format_number(grand, null, 0));

		const excess = flt(frm.doc.excess_percent);
		const items = frm.doc.items || [];
		const cutting = items.reduce((t, r) => t + cint(r.cutting_qty), 0);
		// In Order Qty mode the grid total is live (includes a value still being typed).
		const order = field === "order_qty" ? grand : items.reduce((t, r) => t + cint(r.order_qty), 0);
		wrapper.find("[data-summary]").html(
			__("Order {0} pcs · Excess {1}% · Cutting {2} pcs · Amount {3}", [
				`<b>${format_number(order, null, 0)}</b>`,
				`<b>${excess}</b>`,
				`<b>${format_number(cutting, null, 0)}</b>`,
				`<b>${format_currency(frm.doc.total_amount || 0, frm.doc.currency)}</b>`,
			])
		);
	},
};
