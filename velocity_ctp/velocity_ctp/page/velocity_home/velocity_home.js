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
		page.add_inner_button(__("Control Tower"), () => frappe.set_route("production-control"));
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
			<div class="vt-kpis ${(data.kpis || []).filter((k) => !k.hidden).length > 7 ? "vt-kpis--many" : ""}"
				style="--vt-kpi-count:${(data.kpis || []).filter((k) => !k.hidden).length}">${this.kpis_html(
				data.kpis || []
			)}</div>
			<div class="vt-grid-2">
				<div class="vt-stack">
					<div class="vt-card">
						<div class="vt-card__title">
							<span>${__("Upcoming Shipments")}</span>
							<span class="vt-card__hint">${__("Next 30 days, including overdue")}</span>
						</div>
						${this.shipments_html(data.shipments || [])}
					</div>
					${data.cutting ? this.cutting_html(data.cutting) : ""}
					${data.margin_watch ? this.margin_html(data.margin_watch) : ""}
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
					${data.procurement ? this.procurement_html(data.procurement) : ""}
					${data.ready_to_ship ? this.ready_html(data.ready_to_ship) : ""}
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

	margin_html(watch) {
		const esc = frappe.utils.escape_html;
		const rows = watch.rows || [];
		const body = rows.length
			? `<div class="vt-table-wrap"><table class="vt-table">
				<thead><tr><th>${__("Job #")}</th><th>${__("Customer")}</th><th>${__("Style")}</th>
					<th class="vt-num">${__("Quoted FOB")}</th><th class="vt-num">${__("Costed FOB")}</th><th class="vt-num">${__("Est. Profit %")}</th></tr></thead>
				<tbody>${rows
					.map(
						(r) => `<tr data-order="${esc(r.name)}"><td><span class="vt-link">${esc(r.name)}</span></td><td>${esc(r.customer)}</td>
							<td>${esc(r.style)}</td><td class="vt-num">${format_number(r.quoted_fob, null, 2)} ${esc(r.currency || "")}</td>
							<td class="vt-num">${format_number(r.costed_fob, null, 2)}</td>
							<td class="vt-num"><span class="vt-margin vt-margin--bad">${format_number(r.estimated_profit_percent, null, 1)}%</span></td></tr>`
					)
					.join("")}</tbody></table></div>`
			: `<div class="vt-empty vt-empty--compact">${__("All open costed orders are at or above the {0}% target margin.", [watch.target])}</div>`;
		return `<div class="vt-card">
			<div class="vt-card__title"><span>${__("Margin Watch")}</span>
				<span class="vt-card__hint">${__("Open orders below the {0}% target margin", [watch.target])}</span></div>${body}</div>`;
	}

	cutting_html(cutting) {
		const esc = frappe.utils.escape_html;
		const rows = cutting.rows || [];
		const body = rows.length
			? `<div class="vt-table-wrap"><table class="vt-table">
				<thead><tr>
					<th>${__("Job Map")}</th>
					<th class="vt-num" title="${esc(__("Issued minus returned"))}">${__("Net Issued (m)")}</th>
					<th class="vt-num">${__("Fabric Used (m)")}</th>
					<th>${__("Pieces Cut / Planned")}</th>
					<th class="vt-num">${__("Wastage %")}</th>
				</tr></thead>
				<tbody>${rows
					.map((r) => {
						const pct = r.pieces_planned ? Math.min(100, Math.round((r.pieces_cut / r.pieces_planned) * 100)) : 0;
						const wastage =
							r.wastage_percent === null || r.wastage_percent === undefined
								? '<span class="vt-muted">–</span>'
								: `<span class="${r.wastage_alert ? "vt-wastage-alert" : ""}" ${
										r.wastage_alert ? `title="${esc(__("Above the alert level of {0}%", [cutting.alert]))}"` : ""
								  }>${format_number(r.wastage_percent, null, 2)}%</span>`;
						return `<tr data-job-map="${esc(r.job_map)}" class="${r.wastage_alert ? "vt-row--overdue" : ""}">
							<td><span class="vt-link">${esc(r.job_map)}</span>
								<div class="vt-muted small">${__(r.status)}</div></td>
							<td class="vt-num">${format_number(r.fabric_issued, null, 2)}</td>
							<td class="vt-num">${format_number(r.fabric_used, null, 2)}</td>
							<td><div class="vt-progress"><span style="width:${pct}%"></span></div>
								<div class="small">${format_number(r.pieces_cut, null, 0)} / ${format_number(
							r.pieces_planned,
							null,
							0
						)} <span class="vt-muted">· ${pct}%</span></div></td>
							<td class="vt-num">${wastage}</td>
						</tr>`;
					})
					.join("")}</tbody></table></div>`
			: `<div class="vt-empty">${__("No active Job Maps in cutting.")}</div>`;
		return `<div class="vt-card">
			<div class="vt-card__title">
				<span>${__("Cutting Status")}</span>
				<span class="vt-card__hint">${__("Active Job Maps · wastage alert above {0}%", [cutting.alert])}</span>
			</div>
			${body}
		</div>`;
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

	ready_html(rows) {
		const esc = frappe.utils.escape_html;
		const body = rows.length
			? `<div class="vt-table-wrap"><table class="vt-table">
				<thead><tr><th>${__("Job #")}</th><th class="vt-num">${__("Pcs")}</th><th class="vt-num">${__("Cartons")}</th><th class="vt-num">${__("Ship In")}</th></tr></thead>
				<tbody>${rows
					.map(
						(r) => `<tr data-ready="${esc(r.garment_order)}" class="${r.days_left !== null && r.days_left < 0 ? "vt-row--overdue" : ""}">
							<td><span class="vt-link">${esc(r.garment_order)}</span><div class="vt-muted small">${esc(r.customer || "")} · ${r.lists} ${__("packing list(s)")}</div></td>
							<td class="vt-num">${format_number(r.pcs || 0, null, 0)}</td><td class="vt-num">${format_number(r.cartons || 0, null, 0)}</td>
							<td class="vt-num vt-days">${r.days_left === null ? "—" : r.days_left < 0 ? __("{0} days late", [-r.days_left]) : __("{0} days", [r.days_left])}</td></tr>`
					)
					.join("")}</tbody></table></div>`
			: `<div class="vt-empty vt-empty--compact">${__("Nothing packed is waiting for shipment.")}</div>`;
		return `<div class="vt-card">
			<div class="vt-card__title"><span>${__("Ready to Ship")}</span><span class="vt-card__hint">${__("Packed, no Delivery Note yet")}</span></div>
			${body}
		</div>`;
	}

	procurement_html(procurement) {
		const cards = procurement.cards || [];
		const waiting = cards.reduce((t, c) => t + (c.value || 0), 0);
		const list = cards
			.map(
				(c, i) => `<li data-proc="${i}" title="${frappe.utils.escape_html(c.sub || "")}">
					<span class="vt-dot vt-tone--${c.tone}"></span>
					<span class="vt-stage-list__label">${c.label}<span class="vt-muted small vt-proc__sub">${c.sub || ""}</span></span>
					<span class="vt-stage-list__count ${c.value ? "vt-proc__count--" + c.tone : "vt-muted"}">${format_number(c.value || 0, null, 0)}</span>
				</li>`
			)
			.join("");
		return `<div class="vt-card">
			<div class="vt-card__title">
				<span>${__("Procurement")}</span>
				<span class="vt-card__hint">${waiting ? __("{0} waiting for action", [waiting]) : __("Nothing waiting")}</span>
			</div>
			<ul class="vt-stage-list vt-proc">${list}</ul>
		</div>`;
	}

	bind(data) {
		this.$body.find("tr[data-ready]").on("click", (e) => {
			frappe.route_options = { garment_order: e.currentTarget.dataset.ready, docstatus: 1, delivery_note: ["is", "not set"] };
			frappe.set_route("List", "Packing List");
		});
		this.$body.find("[data-proc]").on("click", (e) => {
			const card = data.procurement.cards[cint(e.currentTarget.dataset.proc)];
			frappe.route_options = card.filters;
			frappe.set_route("List", card.doctype);
		});
		const kpis = Object.fromEntries((data.kpis || []).map((k) => [k.key, k]));
		this.$body.find("[data-kpi]").on("click", (e) => {
			const k = kpis[e.currentTarget.dataset.kpi];
			if (k.route) {
				frappe.set_route(k.route);
				return;
			}
			frappe.route_options = k.filters;
			frappe.set_route("List", k.doctype);
		});
		this.$body.find("tr[data-order]").on("click", (e) => {
			frappe.set_route("Form", "Garment Order", e.currentTarget.dataset.order);
		});
		this.$body.find("tr[data-job-map]").on("click", (e) => {
			frappe.set_route("Form", "Job Map", e.currentTarget.dataset.jobMap);
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
