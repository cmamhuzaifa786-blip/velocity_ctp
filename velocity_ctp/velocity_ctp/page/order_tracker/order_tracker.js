// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.pages["order-tracker"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Order Tracker"),
		single_column: true,
	});
	frappe.require("/assets/velocity_ctp/css/velocity.css", () => {
		wrapper.order_tracker = new OrderTracker(page);
	});
};

frappe.pages["order-tracker"].on_page_show = function (wrapper) {
	if (wrapper.order_tracker) wrapper.order_tracker.refresh();
};

const RISK_META = {
	on_track: { label: __("On track"), tone: "ok" },
	at_risk: { label: __("At risk"), tone: "warn" },
	overdue: { label: __("Overdue"), tone: "bad" },
};

class OrderTracker {
	constructor(page) {
		this.page = page;
		this.$root = $('<div class="vt-page"></div>').appendTo(page.main);
		this.$filters = $('<div class="vt-filters"></div>').appendTo(this.$root);
		this.$card = $('<div class="vt-card"></div>').appendTo(this.$root);
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		page.add_inner_button(__("Velocity Home"), () => frappe.set_route("velocity-home"));
		this.make_filters();
		this.refresh();
	}

	make_filters() {
		const on_change = () => this.refresh_debounced();
		const defs = [
			{ fieldname: "search", fieldtype: "Data", label: __("Job #"), placeholder: __("Search Job #") },
			{ fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer") },
			{
				fieldname: "style",
				fieldtype: "Link",
				options: "Style",
				label: __("Style"),
				get_query: () => {
					const customer = this.filters.customer.get_value();
					return { filters: customer ? { customer } : {} };
				},
			},
			{
				fieldname: "status",
				fieldtype: "Select",
				label: __("Status"),
				options: ["", "Draft", "Open", "On Hold", "In Production", "Completed", "Cancelled"],
			},
			{ fieldname: "from_date", fieldtype: "Date", label: __("Ship Date From") },
			{ fieldname: "to_date", fieldtype: "Date", label: __("Ship Date To") },
		];
		this.filters = {};
		defs.forEach((df) => {
			const $wrap = $("<div></div>").appendTo(this.$filters);
			const control = frappe.ui.form.make_control({
				parent: $wrap,
				df: Object.assign({}, df, { change: on_change }),
				render_input: true,
			});
			control.refresh();
			this.filters[df.fieldname] = control;
		});
		this.filters.search.$input.on("input", on_change);
		this.refresh_debounced = frappe.utils.debounce(() => this.refresh(), 300);
	}

	get_args() {
		const args = {};
		Object.entries(this.filters).forEach(([key, control]) => {
			const value = control.get_value();
			if (value) args[key] = value;
		});
		return args;
	}

	refresh() {
		frappe
			.call({ method: "velocity_ctp.api.dashboard.get_order_tracker", args: this.get_args() })
			.then((r) => this.render(r.message || { rows: [], stages: [], risk_counts: {} }));
	}

	render(data) {
		const esc = frappe.utils.escape_html;
		const counts = data.risk_counts || {};
		const legend = Object.entries(RISK_META)
			.map(
				([key, meta]) =>
					`<span class="vt-badge vt-badge--${meta.tone}">${meta.label}: ${counts[key] || 0}</span>`
			)
			.join("");

		if (!data.rows.length) {
			this.$card.html(`
				<div class="vt-card__title"><span>${__("Garment Orders")}</span>
					<span class="vt-legend">${legend}</span></div>
				<div class="vt-empty">${__("No Garment Orders match these filters.")}</div>`);
			return;
		}

		const head = data.stages.map((s) => s.label).join(" → ");
		const body = data.rows
			.map((r) => {
				const meta = RISK_META[r.risk];
				const row_cls = r.risk === "overdue" ? "vt-row--overdue" : r.risk === "at_risk" ? "vt-row--risk" : "";
				const days =
					r.days_left === null
						? ""
						: r.days_left < 0
						? __("{0} days late", [Math.abs(r.days_left)])
						: __("{0} days", [r.days_left]);
				const steps = r.stages
					.map(
						(s, i) => `<div class="vt-step vt-step--${s.state}" title="${esc(
							data.stages[i].label + ": " + s.detail
						)}">
							<span class="vt-step__name">${esc(data.stages[i].label)}</span>
							<span class="vt-step__detail">${esc(s.detail)}</span>
						</div>`
					)
					.join("");
				// Compact view (narrow screens): dots plus the current stage as text.
				const current_index = r.stages.findIndex((s) => s.state !== "done");
				const current =
					current_index === -1
						? __("All stages done")
						: `${data.stages[current_index].label}: ${r.stages[current_index].detail}`;
				return `<tr class="${row_cls}" data-order="${esc(r.name)}">
					<td><span class="vt-link">${esc(r.name)}</span>
						<div class="vt-muted small">${esc(r.customer)}</div>
						<div class="vt-muted small vt-only-narrow">${esc(r.style)}</div></td>
					<td class="vt-col-style">${esc(r.style)}<div class="vt-muted small">${esc(r.style_name || "")}</div></td>
					<td class="vt-num">${format_number(r.total_order_qty || 0, null, 0)}</td>
					<td>${r.ship_date ? frappe.datetime.str_to_user(r.ship_date) : ""}
						<div class="small vt-days">${days}</div></td>
					<td><span class="vt-badge vt-badge--${meta.tone}">${meta.label}</span>
						<div class="vt-muted small">${__(r.status)}</div></td>
					<td class="vt-pipeline-cell"><div class="vt-pipeline">${steps}</div>
						<span class="vt-pipeline__current">${esc(current)}</span></td>
				</tr>`;
			})
			.join("");

		this.$card.html(`
			<div class="vt-card__title">
				<span>${__("Garment Orders")}
					<span class="vt-card__hint">${
						data.truncated
							? __("Showing the first {0}. Narrow the filters to see more.", [data.limit])
							: __("{0} orders", [data.rows.length])
					}</span></span>
				<span class="vt-legend">${legend}</span>
			</div>
			<div class="vt-dot-legend" aria-hidden="true">
				<span><i class="vt-step--done"></i>${__("Done")}</span>
				<span><i class="vt-step--active"></i>${__("In progress")}</span>
				<span><i class="vt-step--blocked"></i>${__("On hold")}</span>
				<span><i class="vt-step--pending"></i>${__("Not started")}</span>
				<span class="vt-muted">${__("Hover a dot to see the stage")}</span>
			</div>
			<div class="vt-table-wrap"><table class="vt-table vt-tracker">
				<thead><tr>
					<th>${__("Job #")}</th><th class="vt-col-style">${__("Style")}</th><th class="vt-num">${__("Qty")}</th>
					<th>${__("Ship Date")}</th><th>${__("Risk")}</th>
					<th title="${esc(head)}">${__("Progress")}</th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table></div>`);

		this.$card.find("tr[data-order]").on("click", (e) => {
			frappe.set_route("Form", "Garment Order", e.currentTarget.dataset.order);
		});
	}
}
