// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.pages["velocity-home"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Velocity Home"),
		single_column: true,
	});
	frappe.require("/assets/velocity_ctp/css/velocity.css", () => {
		wrapper.velocity_home = new VelocityHome(page);
	});
};

frappe.pages["velocity-home"].on_page_show = function (wrapper) {
	if (wrapper.velocity_home) wrapper.velocity_home.refresh();
};

class VelocityHome {
	constructor(page) {
		this.page = page;
		this.$body = $('<div class="vt-page"></div>').appendTo(page.main);
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		page.add_inner_button(__("Order Tracker"), () => frappe.set_route("order-tracker"));
		this.refresh();
	}

	refresh() {
		frappe
			.call({ method: "velocity_ctp.api.dashboard.get_home_data" })
			.then((r) => this.render(r.message || {}));
	}

	render(data) {
		const esc = frappe.utils.escape_html;
		const today = frappe.datetime.str_to_user(data.today);
		const weekday = moment(data.today).format("dddd");

		this.$body.html(`
			<div class="vt-header">
				<div>
					<div class="vt-header__eyebrow">${esc(data.company || __("No default company"))}</div>
					<h2 class="vt-header__title">${__("Production overview")}</h2>
					<div class="vt-header__meta">${weekday}, ${today}</div>
				</div>
			</div>
			<div class="vt-kpis">${this.kpis_html(data.kpis || [])}</div>
			<div class="vt-grid-2">
				<div class="vt-stack">
					<div class="vt-card">
						<div class="vt-card__title">
							<span>${__("Upcoming Shipments")}</span>
							<span class="vt-card__hint">${__("Next 30 days, including overdue")}</span>
						</div>
						${this.shipments_html(data.shipments || [])}
					</div>
					<div class="vt-card">
						<div class="vt-card__title">
							<span>${__("Orders by Customer")}</span>
							<span class="vt-card__hint">${__("Open orders, most pieces first")}</span>
						</div>
						${this.customers_html(data.customers || [])}
					</div>
				</div>
				<div class="vt-stack">
					${data.pipeline ? this.pipeline_html(data.pipeline) : ""}
					<div class="vt-card">
						<div class="vt-card__title">${__("Quick Actions")}</div>
						<div class="vt-quick">
							${this.quick_action("Garment Order", __("New Garment Order"), "vt-quick__btn--primary")}
							${this.quick_action("Job Map", __("New Job Map"))}
							${this.quick_action("Style", __("New Style"))}
						</div>
					</div>
				</div>
			</div>
		`);
		this.bind(data);
	}

	kpis_html(kpis) {
		return kpis
			.filter((k) => !k.hidden)
			.map(
				(k) => `
				<button type="button" class="vt-kpi vt-kpi--${k.tone}" data-kpi="${k.key}"
					title="${frappe.utils.escape_html(k.label + (k.sub ? " · " + k.sub : ""))}">
					<span class="vt-kpi__label">${k.label}</span>
					<span class="vt-kpi__value">${format_number(k.value || 0, null, 0)}</span>
					<span class="vt-kpi__sub">${k.sub || "&nbsp;"}</span>
				</button>`
			)
			.join("");
	}

	shipments_html(rows) {
		if (!rows.length) {
			return `<div class="vt-empty">${__("No shipments due in the next 30 days.")}</div>`;
		}
		const esc = frappe.utils.escape_html;
		const body = rows
			.map((r) => {
				const days =
					r.days_left < 0
						? __("{0} days late", [Math.abs(r.days_left)])
						: r.days_left === 0
						? __("Today")
						: __("{0} days", [r.days_left]);
				const row_cls = r.overdue ? "vt-row--overdue" : r.days_left <= 14 ? "vt-row--risk" : "";
				return `<tr class="${row_cls}" data-order="${esc(r.name)}">
					<td><span class="vt-link">${esc(r.name)}</span>
						${r.job_map ? `<div class="vt-muted small">${esc(r.job_map)}</div>` : ""}</td>
					<td>${esc(r.customer)}</td>
					<td>${esc(r.style)}${
					r.style_name && r.style_name !== r.style
						? `<div class="vt-muted small">${esc(r.style_name)}</div>`
						: ""
				}</td>
					<td class="vt-num">${format_number(r.total_order_qty || 0, null, 0)}</td>
					<td>${frappe.datetime.str_to_user(r.ship_date)}</td>
					<td class="vt-num vt-days">${days}</td>
					<td>${status_badge(r.status)}</td>
				</tr>`;
			})
			.join("");
		return `<div class="vt-table-wrap"><table class="vt-table">
			<thead><tr>
				<th>${__("Job #")}</th><th>${__("Customer")}</th><th>${__("Style")}</th>
				<th class="vt-num">${__("Qty")}</th><th>${__("Ship Date")}</th>
				<th class="vt-num">${__("Days Left")}</th><th>${__("Status")}</th>
			</tr></thead><tbody>${body}</tbody></table></div>`;
	}

	quick_action(doctype, label, modifier = "") {
		return `<button type="button" class="btn vt-quick__btn ${modifier}" data-new="${doctype}">
			<span class="vt-quick__plus" aria-hidden="true">+</span><span>${label}</span>
		</button>`;
	}

	customers_html(rows) {
		if (!rows.length) {
			return `<div class="vt-empty">${__("No open orders.")}</div>`;
		}
		const esc = frappe.utils.escape_html;
		const body = rows
			.map(
				(r, i) => `<tr data-customer="${i}" class="${r.overdue ? "vt-row--overdue" : ""}">
					<td><span class="vt-link">${esc(r.customer_name)}</span>${
					r.customer_name !== r.customer ? `<div class="vt-muted small">${esc(r.customer)}</div>` : ""
				}</td>
					<td class="vt-num">${format_number(r.orders, null, 0)}</td>
					<td class="vt-num">${format_number(r.pieces, null, 0)}</td>
					<td class="vt-num ${r.overdue ? "vt-days" : ""}">${
					r.next_ship_date ? frappe.datetime.str_to_user(r.next_ship_date) : "–"
				}</td>
				</tr>`
			)
			.join("");
		return `<div class="vt-table-wrap"><table class="vt-table">
			<thead><tr>
				<th>${__("Customer")}</th><th class="vt-num">${__("Open Orders")}</th>
				<th class="vt-num">${__("Pieces on Order")}</th><th class="vt-num">${__("Next Ship Date")}</th>
			</tr></thead><tbody>${body}</tbody></table></div>`;
	}

	pipeline_html(pipeline) {
		const total = pipeline.stages.reduce((t, s) => t + s.count, 0);
		const hint = [
			pipeline.active === 1 ? __("1 active job") : __("{0} active jobs", [pipeline.active]),
			__("{0} ready to cut", [pipeline.ready]),
		].join(" · ");
		if (!total) {
			const message = pipeline.active
				? __("All active jobs are ready to cut.")
				: __("No active jobs.");
			return `<div class="vt-card">
				<div class="vt-card__title">
					<span>${__("Approval Pipeline")}</span>
					<span class="vt-card__hint">${hint}</span>
				</div>
				<div class="vt-empty vt-empty--compact">
					${pipeline.active ? '<span class="vt-empty__icon" aria-hidden="true">✓</span>' : ""}
					${message}
				</div>
			</div>`;
		}
		const bar = pipeline.stages
			.filter((s) => s.count)
			.map(
				(s) =>
					`<div class="vt-stagebar__seg vt-stage-${
						pipeline.stages.indexOf(s) + 1
					}" style="flex-grow:${s.count}" title="${s.label}: ${s.count}"></div>`
			)
			.join("");
		const list = pipeline.stages
			.map(
				(s, i) => `<li data-stage="${i}">
					<span class="vt-dot vt-stage-${i + 1}"></span>
					<span class="vt-stage-list__label">${__("Waiting for {0}", [s.label])}</span>
					<span class="vt-stage-list__count">${s.count}</span>
				</li>`
			)
			.join("");
		return `<div class="vt-card">
			<div class="vt-card__title">
				<span>${__("Approval Pipeline")}</span>
				<span class="vt-card__hint">${hint}</span>
			</div>
			<div class="vt-stagebar">${bar}</div>
			<ul class="vt-stage-list">${list}</ul>
		</div>`;
	}

	bind(data) {
		const kpis = Object.fromEntries((data.kpis || []).map((k) => [k.key, k]));
		this.$body.find("[data-kpi]").on("click", (e) => {
			const k = kpis[e.currentTarget.dataset.kpi];
			frappe.route_options = k.filters;
			frappe.set_route("List", k.doctype);
		});
		this.$body.find("tr[data-order]").on("click", (e) => {
			frappe.set_route("Form", "Garment Order", e.currentTarget.dataset.order);
		});
		this.$body.find("tr[data-customer]").on("click", (e) => {
			const row = data.customers[cint(e.currentTarget.dataset.customer)];
			frappe.route_options = row.filters;
			frappe.set_route("List", "Garment Order");
		});
		this.$body.find("[data-stage]").on("click", (e) => {
			const stage = data.pipeline.stages[cint(e.currentTarget.dataset.stage)];
			frappe.route_options = stage.filters;
			frappe.set_route("List", "Job Map");
		});
		this.$body.find("[data-new]").on("click", (e) => frappe.new_doc(e.currentTarget.dataset.new));
	}
}

function status_badge(status) {
	const tone =
		{
			Open: "info",
			"In Production": "ok",
			"On Hold": "bad",
			Draft: "",
			Completed: "ok",
		}[status] || "";
	return `<span class="vt-badge ${tone ? "vt-badge--" + tone : ""}">${__(status)}</span>`;
}
