// Copyright (c) 2026, Muhammad Huzaifa and contributors
// For license information, please see license.txt

// Scan Station: shop-floor issue / receive of bundles with a keyboard-wedge barcode scanner.
// The scanner types the barcode and presses Enter into the always-focused scan input.

const VT_SCAN = "velocity_ctp.api.scan.";

frappe.pages["scan-station"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Scan Station"), single_column: true });
	frappe.require("/assets/velocity_ctp/css/velocity.css", () => {
		wrapper.scan_station = new ScanStation(page);
	});
};

frappe.pages["scan-station"].on_page_show = function (wrapper) {
	if (wrapper.scan_station) wrapper.scan_station.focus();
};

class ScanStation {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.queue = Promise.resolve();
		this.$root = $('<div class="vt-page vt-scan"></div>').appendTo(page.main);
		frappe.call(VT_SCAN + "get_setup").then((r) => {
			this.setup = r.message;
			const last = this.setup.last || {};
			this.choice = {
				action: last.action || (this.setup.can_issue ? "Issue" : "Receive"),
				process: this.setup.processes.some((p) => p.name === last.process) ? last.process : (this.setup.processes[0] || {}).name,
				party: last.party || "",
			};
			this.render_setup();
		});
	}

	process_info() {
		return this.setup.processes.find((p) => p.name === this.choice.process) || {};
	}

	needs_party() {
		const type = this.process_info().process_type;
		return type === "Outsourced" || type === "Both";
	}

	// ------------------------------------------------------------------ step 1
	render_setup() {
		const esc = frappe.utils.escape_html;
		const actions = ["Issue", "Receive"]
			.filter((a) => (a === "Issue" ? this.setup.can_issue : this.setup.can_receive))
			.map(
				(a) => `<button type="button" class="vt-choice ${this.choice.action === a ? "is-active" : ""}" data-action="${a}">
					<span class="vt-choice__title">${a === "Issue" ? __("Issue") : __("Receive")}</span>
					<span class="vt-choice__hint">${a === "Issue" ? __("Send bundles to a process") : __("Bundles back from a process")}</span>
				</button>`
			)
			.join("");
		const processes = this.setup.processes
			.map(
				(p) => `<button type="button" class="vt-choice ${this.choice.process === p.name ? "is-active" : ""}" data-process="${esc(p.name)}">
					<span class="vt-choice__title">${esc(p.name)}</span>
					<span class="vt-choice__hint">${__(p.process_type)}</span>
				</button>`
			)
			.join("");
		this.$root.html(`
			<div class="vt-scan__steps"><span class="is-active">1 · ${__("Choose")}</span><span>2 · ${__("Scan")}</span></div>
			<div class="vt-card">
				<div class="vt-card__title">${__("Action")}</div>
				<div class="vt-choices">${actions}</div>
				<div class="vt-card__title" style="margin-top:18px">${__("Process")}</div>
				<div class="vt-choices">${processes || `<div class="vt-empty">${__("No active processes.")}</div>`}</div>
				<div class="vt-scan__party" style="margin-top:18px"></div>
				<button type="button" class="btn btn-primary btn-lg vt-scan__start">${__("Start Scanning")}</button>
			</div>`);

		this.party_control = null;
		if (this.needs_party()) {
			this.party_control = frappe.ui.form.make_control({
				parent: this.$root.find(".vt-scan__party"),
				df: {
					fieldname: "party",
					fieldtype: "Link",
					options: "Supplier",
					label: this.process_info().process_type === "Outsourced" ? __("Party (contractor)") : __("Party (leave empty for in-house)"),
					reqd: this.process_info().process_type === "Outsourced",
				},
				render_input: true,
			});
			this.party_control.set_value(this.choice.party || "");
		}
		this.$root.find("[data-action]").on("click", (e) => {
			this.choice.action = e.currentTarget.dataset.action;
			this.render_setup();
		});
		this.$root.find("[data-process]").on("click", (e) => {
			this.choice.process = e.currentTarget.dataset.process;
			this.render_setup();
		});
		this.$root.find(".vt-scan__start").on("click", () => this.start());
	}

	start() {
		this.choice.party = this.party_control ? this.party_control.get_value() || "" : "";
		if (!this.choice.process) return;
		if (this.process_info().process_type === "Outsourced" && !this.choice.party) {
			frappe.msgprint(__("{0} is outsourced. Please select the party (contractor).", [this.choice.process]));
			return;
		}
		frappe.call({ method: VT_SCAN + "save_choice", args: this.choice });
		this.rows = [];
		this.render_scan();
	}

	// ------------------------------------------------------------------ step 2
	render_scan() {
		const esc = frappe.utils.escape_html;
		const c = this.choice;
		const where = c.party ? `${esc(c.process)} · ${esc(c.party)}` : `${esc(c.process)} · ${__("in-house")}`;
		this.$root.html(`
			<div class="vt-scan__steps"><span>1 · ${__("Choose")}</span><span class="is-active">2 · ${__("Scan")}</span></div>
			<div class="vt-scan__bar">
				<div><span class="vt-badge ${c.action === "Issue" ? "vt-badge--info" : "vt-badge--ok"}">${c.action === "Issue" ? __("Issue") : __("Receive")}</span>
					<span class="vt-scan__where">${where}</span></div>
				<button type="button" class="btn btn-default btn-sm vt-scan__change">${__("Change")}</button>
			</div>
			<div class="vt-card vt-scan__inputcard">
				<label class="vt-scan__label" for="vt-scan-input">${__("Scan bundle barcode")}</label>
				<input id="vt-scan-input" class="vt-scan__input" type="text" autocomplete="off" autocapitalize="characters"
					spellcheck="false" inputmode="text" placeholder="${__("BDL-0000001")}">
				<div class="vt-scan__feedback" role="status" aria-live="polite"></div>
			</div>
			<div class="vt-grid-2 vt-scan__grid">
				<div class="vt-card"><div class="vt-card__title"><span>${__("Scanned Bundles")}</span>
					<span class="vt-card__hint vt-scan__count"></span></div><div class="vt-scan__list"></div></div>
				<div class="vt-stack">
					<div class="vt-card"><div class="vt-card__title">${__("Totals")}</div><div class="vt-scan__totals"></div></div>
					<div class="vt-scan__actions">
						<button type="button" class="btn btn-primary btn-lg vt-scan__submit">${c.action === "Issue" ? __("Submit Issue") : __("Submit Receive")}</button>
						<button type="button" class="btn btn-default btn-lg vt-scan__clear">${__("Clear")}</button>
					</div>
				</div>
			</div>`);
		this.$input = this.$root.find(".vt-scan__input");
		this.$input.on("keydown", (e) => {
			if (e.key !== "Enter") return;
			e.preventDefault();
			const value = this.$input.val().trim();
			this.$input.val("");
			if (value) this.queue = this.queue.then(() => this.scan(value));
		});
		// Keep the scan input focused unless the user is editing a row value or a dialog is open.
		this.$root.on("focusout", (e) => {
			setTimeout(() => {
				const active = document.activeElement;
				const editing = active && active !== this.$input[0] && $(active).closest(".vt-scan__list, .modal, .awesomplete").length;
				if (!editing && !$(".modal.show").length && this.$input && document.body.contains(this.$input[0])) this.focus();
			}, 120);
		});
		this.$root.find(".vt-scan__change").on("click", () => this.render_setup());
		this.$root.find(".vt-scan__submit").on("click", () => this.submit());
		this.$root.find(".vt-scan__clear").on("click", () => {
			if (!this.rows.length) return this.focus();
			frappe.confirm(__("Remove all {0} scanned bundles from the list?", [this.rows.length]), () => {
				this.rows = [];
				this.render_rows();
				this.feedback("info", __("List cleared."));
			});
		});
		this.render_rows();
		this.focus();
	}

	focus() {
		if (this.$input && document.body.contains(this.$input[0])) this.$input.trigger("focus");
	}

	scan(value) {
		return frappe
			.call({
				method: VT_SCAN + "scan",
				args: { barcode: value, ...this.choice, scanned: this.rows.map((r) => r.bundle) },
				type: "POST",
			})
			.then((r) => {
				const res = r.message || {};
				if (!res.ok) {
					this.feedback("bad", res.reason);
					this.beep(false);
					return;
				}
				this.rows.unshift(res.bundle);
				this.render_rows();
				const b = res.bundle;
				this.feedback("ok", __("Added {0}: {1} / {2} · {3} pcs", [b.bundle, b.colour, b.size, b.issued_qty || b.qty]));
				this.beep(true);
			})
			.catch(() => {
				this.feedback("bad", __("The scan could not be checked. Please scan again."));
				this.beep(false);
			});
	}

	feedback(kind, message) {
		const $f = this.$root.find(".vt-scan__feedback");
		$f.removeClass("is-ok is-bad is-info").addClass(`is-${kind}`).text(message);
	}

	beep(ok) {
		try {
			const ctx = this.audio || (this.audio = new (window.AudioContext || window.webkitAudioContext)());
			const osc = ctx.createOscillator();
			const gain = ctx.createGain();
			osc.type = ok ? "sine" : "square";
			osc.frequency.value = ok ? 1046 : 220;
			gain.gain.value = ok ? 0.08 : 0.12;
			osc.connect(gain).connect(ctx.destination);
			osc.start();
			osc.stop(ctx.currentTime + (ok ? 0.08 : 0.35));
		} catch (e) {
			// Sound is optional (some browsers block audio until a user gesture).
		}
	}

	render_rows() {
		const esc = frappe.utils.escape_html;
		const receive = this.choice.action === "Receive";
		const info = this.process_info();
		const $list = this.$root.find(".vt-scan__list");
		if (!this.rows.length) {
			$list.html(`<div class="vt-empty">${__("Scan a bundle barcode to start.")}</div>`);
		} else {
			const head = receive
				? `<th>${__("Bundle")}</th><th>${__("Colour / Size")}</th><th class="vt-num">${__("Open")}</th><th class="vt-num">${__("Fresh")}</th>
				   <th>${__("Rejects")}</th><th>${__("Repair")}</th>${info.allow_colour_change ? `<th>${__("To Colour")}</th>` : ""}<th></th>`
				: `<th>${__("Bundle")}</th><th>${__("Order")}</th><th>${__("Colour / Size")}</th><th class="vt-num">${__("Qty")}</th><th></th>`;
			const body = this.rows
				.map((r, i) => {
					const remove = `<button type="button" class="btn btn-xs btn-default vt-scan__remove" data-i="${i}" aria-label="${__("Remove")}">×</button>`;
					if (!receive) {
						return `<tr><td><b>${esc(r.bundle)}</b></td><td>${esc(r.garment_order)}</td><td>${esc(r.colour)} / ${esc(r.size)}</td>
							<td class="vt-num">${r.qty}</td><td>${remove}</td></tr>`;
					}
					const colours = (r.colours || []).map((c) => `<option ${c === r.to_colour ? "selected" : ""}>${esc(c)}</option>`).join("");
					return `<tr><td><b>${esc(r.bundle)}</b>${r.repair_pending ? `<div class="vt-muted small">${__("repair return")}</div>` : ""}</td>
						<td>${esc(r.colour)} / ${esc(r.size)}</td><td class="vt-num">${r.issued_qty}</td>
						<td class="vt-num"><b>${r.fresh_qty}</b></td>
						<td><input class="vt-scan__qty" type="number" min="0" data-i="${i}" data-f="rejected_qty" value="${r.rejected_qty}" ${info.allow_rejection ? "" : "disabled"}></td>
						<td><input class="vt-scan__qty" type="number" min="0" data-i="${i}" data-f="repair_qty" value="${r.repair_qty}"></td>
						${info.allow_colour_change ? `<td><select class="vt-scan__colour" data-i="${i}"><option value="">${__("Same")}</option>${colours}</select></td>` : ""}
						<td>${remove}</td></tr>`;
				})
				.join("");
			$list.html(`<div class="vt-table-wrap vt-scan__tablewrap"><table class="vt-table vt-scan__table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
		}
		$list.find(".vt-scan__remove").on("click", (e) => {
			this.rows.splice(cint(e.currentTarget.dataset.i), 1);
			this.render_rows();
			this.focus();
		});
		$list.find(".vt-scan__qty").on("change", (e) => {
			const row = this.rows[cint(e.currentTarget.dataset.i)];
			row[e.currentTarget.dataset.f] = Math.max(0, cint(e.currentTarget.value));
			const fresh = row.issued_qty - row.rejected_qty - row.repair_qty;
			if (fresh < 0) {
				row[e.currentTarget.dataset.f] = 0;
				this.feedback("bad", __("Rejected and repair pieces cannot be more than the {0} open pieces of {1}.", [row.issued_qty, row.bundle]));
			}
			row.fresh_qty = row.issued_qty - row.rejected_qty - row.repair_qty;
			if (row.repair_qty && row.to_colour) row.to_colour = "";
			this.render_rows();
		});
		$list.find(".vt-scan__colour").on("change", (e) => {
			const row = this.rows[cint(e.currentTarget.dataset.i)];
			row.to_colour = e.currentTarget.value;
			if (row.to_colour && row.repair_qty) {
				row.to_colour = "";
				this.feedback("bad", __("The colour can only change when no pieces are left for repair."));
				this.render_rows();
			}
		});
		this.render_totals();
	}

	render_totals() {
		const esc = frappe.utils.escape_html;
		const receive = this.choice.action === "Receive";
		const groups = {};
		let pieces = 0;
		this.rows.forEach((r) => {
			const key = `${r.garment_order}|${r.colour}|${r.size}`;
			const g = (groups[key] = groups[key] || { order: r.garment_order, colour: r.colour, size: r.size, bundles: 0, pcs: 0 });
			const pcs = receive ? r.fresh_qty : r.qty;
			g.bundles += 1;
			g.pcs += pcs;
			pieces += pcs;
		});
		this.$root.find(".vt-scan__count").text(__("{0} bundles · {1} pcs", [this.rows.length, pieces]));
		const lines = Object.values(groups);
		this.$root.find(".vt-scan__totals").html(
			`<div class="vt-scan__big"><div><span>${this.rows.length}</span>${__("Bundles")}</div><div><span>${pieces}</span>${
				receive ? __("Fresh pcs") : __("Pieces")
			}</div></div>` +
				(lines.length
					? `<table class="vt-table vt-scan__mini"><tbody>${lines
							.map(
								(g) => `<tr><td>${esc(g.order)}</td><td>${esc(g.colour)} / ${esc(g.size)}</td>
									<td class="vt-num">${g.bundles}</td><td class="vt-num"><b>${g.pcs}</b></td></tr>`
							)
							.join("")}</tbody></table>`
					: "")
		);
	}

	submit() {
		if (!this.rows.length) {
			this.feedback("bad", __("Scan at least one bundle first."));
			return this.focus();
		}
		const $btn = this.$root.find(".vt-scan__submit").prop("disabled", true);
		frappe
			.call({
				method: VT_SCAN + "submit",
				args: { ...this.choice, rows: this.rows },
				type: "POST",
				freeze: true,
				freeze_message: __("Submitting..."),
			})
			.then(
				(r) => {
					$btn.prop("disabled", false);
					this.done(r.message);
				},
				() => {
					$btn.prop("disabled", false);
					this.focus();
				}
			);
	}

	done(result) {
		if (!result) return;
		const esc = frappe.utils.escape_html;
		const route = frappe.router.slug(result.doctype);
		this.rows = [];
		this.$root.html(`
			<div class="vt-card vt-scan__done">
				<div class="vt-scan__done-icon" aria-hidden="true">✓</div>
				<h3>${__("{0} {1} submitted", [__(result.doctype), esc(result.name)])}</h3>
				<p class="vt-muted">${__("{0} bundles · {1} pcs", [result.bundles, result.pieces])}</p>
				<div class="vt-scan__actions">
					<a class="btn btn-default btn-lg" href="/desk/${route}/${encodeURIComponent(result.name)}">${__("Open {0}", [esc(result.name)])}</a>
					${
						result.doctype === "Process Issue"
							? `<a class="btn btn-default btn-lg" target="_blank" href="/printview?${new URLSearchParams({
									doctype: result.doctype,
									name: result.name,
									format: "Process Challan",
									no_letterhead: 1,
									trigger_print: 1,
							  })}">${__("Print Challan")}</a>`
							: ""
					}
					<button type="button" class="btn btn-primary btn-lg vt-scan__again">${__("Scan Next List")}</button>
				</div>
			</div>`);
		this.$root.find(".vt-scan__again").on("click", () => this.render_scan());
		this.beep(true);
	}
}
