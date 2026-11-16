// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

frappe.pages["production-control"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Production Control Tower"), single_column: true });
	frappe.require("/assets/velocity_ctp/css/velocity.css", () => {
		wrapper.control_tower = new ControlTower(page);
	});
};

frappe.pages["production-control"].on_page_show = function (wrapper) {
	if (wrapper.control_tower) wrapper.control_tower.refresh();
};

class ControlTower {
	constructor(page) {
		this.page = page;
		this.$body = $('<div class="vt-page"></div>').appendTo(page.main);
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		page.add_inner_button(__("Scan Station"), () => frappe.set_route("scan-station"));
		page.add_inner_button(__("Velocity Home"), () => frappe.set_route("velocity-home"));
		this.refresh();
	}

	refresh() {
		frappe.call("velocity_ctp.api.production.get_control_tower").then((r) => this.render(r.message || {}));
	}

	render(data) {
		const esc = frappe.utils.escape_html;
		const pct = (v) => (v === null || v === undefined ? '<span class="vt-muted">–</span>' : `${format_number(v, null, 1)}%`);
		const wip = (data.wip || [])
			.map((c) => {
				const sub = `${__("{0} bundles", [c.bundles])} · ${
					c.process === "Cutting"
						? __("cut, not issued")
						: __("{0} out · {1} back", [format_number(c.issued, null, 0), format_number(c.received, null, 0)])
				}${c.repair ? " · " + __("{0} in repair", [c.repair]) : ""}`;
				// the line can be cut off on narrow screens; the tooltip shows all of it
				return `<button type="button" class="vt-kpi vt-kpi--${c.repair ? "warn" : "info"}" data-process="${esc(c.process)}" title="${esc(sub)}">
					<span class="vt-kpi__label">${esc(c.process)}</span>
					<span class="vt-kpi__value">${format_number(c.pieces, null, 0)}</span>
					<span class="vt-kpi__sub">${esc(sub)}</span>
				</button>`;
			})
			.join("");
		const contractors = (data.contractors || []).filter((c) => c.bundles);
		const contractorCards = contractors.length
			? contractors
					.map(
						(c) => `<div class="vt-kpi vt-kpi--warn vt-kpi--static">
							<span class="vt-kpi__label" title="${esc(c.party)}">${esc(c.party)}</span>
							<span class="vt-kpi__value">${format_number(c.pieces, null, 0)}</span>
							<span class="vt-kpi__sub">${__("{0} bundles at {1}", [c.bundles, esc(c.processes)])}</span>
						</div>`
					)
					.join("")
			: `<div class="vt-card vt-kpis__empty"><div class="vt-empty vt-empty--compact">${__("No bundles are with contractors.")}</div></div>`;

		const buckets = data.age_buckets || [];
		const ageing = (data.ageing || []).length
			? `<div class="vt-table-wrap"><table class="vt-table">
				<thead><tr><th>${__("Process")}</th><th>${__("Party")}</th>${buckets
					.map((b) => `<th class="vt-num">${__("{0} days", [b])}</th>`)
					.join("")}</tr></thead>
				<tbody>${data.ageing
					.map(
						(r) => `<tr class="vt-row--plain"><td><b>${esc(r.process)}</b></td><td>${esc(r.party || __("In-house"))}</td>${buckets
							.map((b, i) =>
								r[b].bundles
									? `<td class="vt-num"><button type="button" class="vt-age vt-age--${i}" data-process="${esc(r.process)}"
										data-party="${esc(r.party)}" data-bucket="${esc(b)}">${__("{0} bundles · {1} pcs", [r[b].bundles, r[b].pieces])}</button></td>`
									: `<td class="vt-num vt-muted">–</td>`
							)
							.join("")}</tr>`
					)
					.join("")}</tbody></table></div>`
			: `<div class="vt-empty">${__("No bundles are waiting to be received.")}</div>`;

		const output = `<div class="vt-table-wrap"><table class="vt-table">
			<thead><tr><th>${__("Process")}</th><th class="vt-num">${__("Fresh Today")}</th><th class="vt-num">${__("Rejection Today")}</th>
				<th class="vt-num">${__("Fresh 7 Days")}</th><th class="vt-num">${__("Rejection 7 Days")}</th></tr></thead>
			<tbody>${(data.output || [])
				.map(
					(r) => `<tr class="vt-row--plain"><td><b>${esc(r.process)}</b></td><td class="vt-num">${format_number(r.today_fresh, null, 0)}</td>
						<td class="vt-num">${pct(r.today_rejection)}</td><td class="vt-num">${format_number(r.week_fresh, null, 0)}</td>
						<td class="vt-num">${pct(r.week_rejection)}</td></tr>`
				)
				.join("")}</tbody></table></div>`;

		const contractorTable = (data.contractors || []).length
			? `<div class="vt-table-wrap"><table class="vt-table">
				<thead><tr><th>${__("Contractor")}</th><th>${__("Process")}</th><th class="vt-num">${__("Bundles Out")}</th>
					<th class="vt-num">${__("Pieces Out")}</th><th>${__("Oldest Issue")}</th><th class="vt-num">${__("Rejection %")}</th></tr></thead>
				<tbody>${data.contractors
					.map(
						(c) => `<tr data-party="${esc(c.party)}"><td><span class="vt-link">${esc(c.party)}</span></td><td>${esc(c.processes || "–")}</td>
							<td class="vt-num">${c.bundles}</td><td class="vt-num">${format_number(c.pieces, null, 0)}</td>
							<td>${c.oldest ? `${frappe.datetime.str_to_user(c.oldest)} <span class="vt-muted">· ${__("{0} days", [c.oldest_days])}</span>` : "–"}</td>
							<td class="vt-num">${pct(c.rejection)}</td></tr>`
					)
					.join("")}</tbody></table></div>`
			: `<div class="vt-empty">${__("No contractors have been used yet.")}</div>`;

		this.$body.html(`
			<div class="vt-header"><div>
				<div class="vt-header__eyebrow">${__("Production")}</div>
				<h2 class="vt-header__title">${__("Control Tower")}</h2>
				<div class="vt-header__meta">${__("{0} pieces in WIP", [format_number(data.pieces_in_wip || 0, null, 0)])} · ${frappe.datetime.str_to_user(data.today)}</div>
			</div></div>
			<div class="vt-card__title vt-section-title">${__("WIP by Process")}</div>
			<div class="vt-kpis" style="--vt-kpi-count:${(data.wip || []).length}">${wip}</div>
			<div class="vt-card__title vt-section-title">${__("WIP with Contractors")}</div>
			<div class="vt-kpis">${contractorCards}</div>
			<div class="vt-stack" style="margin-top:16px">
				<div class="vt-card"><div class="vt-card__title"><span>${__("WIP Ageing")}</span>
					<span class="vt-card__hint">${__("Issued and not yet received · click to see the bundles")}</span></div>${ageing}</div>
				<div class="vt-card"><div class="vt-card__title"><span>${__("Output and Rejection")}</span>
					<span class="vt-card__hint">${__("Fresh pieces and rejection on Process Receives")}</span></div>${output}</div>
				<div class="vt-card"><div class="vt-card__title">${__("Contractors")}</div>${contractorTable}</div>
			</div>`);

		this.$body.find("[data-process].vt-kpi").on("click", (e) => {
			frappe.route_options = { current_process: e.currentTarget.dataset.process, status: ["in", ["In Cutting", "Issued", "Received"]] };
			frappe.set_route("List", "Bundle");
		});
		this.$body.find(".vt-age").on("click", (e) => this.show_bundles(e.currentTarget.dataset));
		this.$body.find("tr[data-party]").on("click", (e) => {
			frappe.route_options = { current_party: e.currentTarget.dataset.party, status: "Issued" };
			frappe.set_route("List", "Bundle");
		});
	}

	show_bundles({ process, party, bucket }) {
		frappe
			.call("velocity_ctp.api.production.get_ageing_bundles", { process, bucket, party: party || null })
			.then((r) => {
				const esc = frappe.utils.escape_html;
				const rows = r.message || [];
				const dialog = new frappe.ui.Dialog({
					title: __("{0} · {1} · {2} days", [process, party || __("In-house"), bucket]),
					size: "large",
					fields: [
						{
							fieldtype: "HTML",
							options: `<div class="vt-table-wrap" style="margin:0"><table class="vt-table">
								<thead><tr><th>${__("Bundle")}</th><th>${__("Order")}</th><th>${__("Colour / Size")}</th>
									<th class="vt-num">${__("Qty")}</th><th>${__("Issued On")}</th><th class="vt-num">${__("Days")}</th><th>${__("Issue")}</th></tr></thead>
								<tbody>${rows
									.map(
										(b) => `<tr><td><a href="/desk/bundle/${encodeURIComponent(b.name)}">${esc(b.name)}</a></td><td>${esc(b.garment_order)}</td>
											<td>${esc(b.colour)} / ${esc(b.size)}</td><td class="vt-num">${b.qty}${
											b.pending_repair_qty ? ` <span class="vt-muted">(${__("{0} repair", [b.pending_repair_qty])})</span>` : ""
										}</td>
											<td>${frappe.datetime.str_to_user(b.issued_on)}</td><td class="vt-num">${b.days}</td>
											<td><a href="/desk/process-issue/${encodeURIComponent(b.open_issue)}">${esc(b.open_issue)}</a></td></tr>`
									)
									.join("")}</tbody></table></div>`,
						},
					],
				});
				dialog.show();
			});
	}
}
