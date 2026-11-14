"""Production Control Tower and per-order process progress (set-based queries, no per-row queries)."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from velocity_ctp.production import flow

LIVE_STATUSES = ("In Cutting", "Issued", "Received")
AGE_BUCKETS = (("0-3", 0, 3), ("4-7", 4, 7), ("8+", 8, 100000))


def _check() -> None:
	if not frappe.has_permission("Bundle", "read"):
		frappe.throw(_("You do not have permission to read Bundles."), frappe.PermissionError)


def pieces_in_wip() -> int:
	"""Cut pieces not yet packed (bundles still in production)."""
	rows = frappe.get_all(
		"Bundle", filters={"status": ("in", LIVE_STATUSES)}, fields=["qty", "packed_qty"], limit_page_length=0
	)
	return sum(cint(r.qty) - cint(r.packed_qty) for r in rows)


@frappe.whitelist()
def get_control_tower() -> dict:
	_check()
	today = getdate(nowdate())
	processes = flow.active_processes()
	order = {p.name: p.sequence for p in processes}
	bundles = frappe.get_all(
		"Bundle",
		filters={"status": ("in", LIVE_STATUSES)},
		fields=["name", "garment_order", "colour", "size", "qty", "packed_qty", "status", "current_process",
		        "current_party", "issued_on", "open_issue", "pending_repair_qty"],
		limit_page_length=0,
	)  # fmt: skip

	by_process: dict[str, dict] = {p.name: {"process": p.name, "process_type": p.process_type, "bundles": 0, "pieces": 0,
	                                        "issued": 0, "received": 0, "repair": 0} for p in processes if p.name != flow.PACKING}  # fmt: skip
	by_party: dict[str, dict] = {}
	ageing: dict[tuple[str, str], dict] = {}
	for b in bundles:
		pieces = cint(b.qty) - cint(b.packed_qty)
		card = by_process.setdefault(
			b.current_process,
			{
				"process": b.current_process,
				"bundles": 0,
				"pieces": 0,
				"issued": 0,
				"received": 0,
				"repair": 0,
			},
		)
		card["bundles"] += 1
		card["pieces"] += pieces
		card["repair"] += cint(b.pending_repair_qty)
		card["received" if b.status == "Received" else "issued"] += pieces
		if b.status == "Issued" and b.current_party:
			party = by_party.setdefault(
				b.current_party,
				{"party": b.current_party, "bundles": 0, "pieces": 0, "processes": set(), "oldest": None},
			)
			party["bundles"] += 1
			party["pieces"] += pieces
			party["processes"].add(b.current_process)
			if b.issued_on and (not party["oldest"] or getdate(b.issued_on) < getdate(party["oldest"])):
				party["oldest"] = b.issued_on
		if b.status == "Issued" and b.issued_on:
			age = date_diff(today, b.issued_on)
			key = (b.current_process, b.current_party or "")
			row = ageing.setdefault(
				key, {"process": b.current_process, "party": b.current_party or "", **{name: {"bundles": 0, "pieces": 0} for name, _a, _b in AGE_BUCKETS}}
			)  # fmt: skip
			for name, low, high in AGE_BUCKETS:
				if low <= age <= high:
					row[name]["bundles"] += 1
					row[name]["pieces"] += pieces

	# Output and rejection: Process Receives today and in the last 7 days.
	week_start = add_days(today, -6)
	receipts = frappe.get_all(
		"Process Receive",
		filters={"docstatus": 1, "posting_date": ("between", (week_start, today))},
		fields=["production_process", "party", "posting_date", "total_fresh", "total_rejected"],
		limit_page_length=0,
	)
	output = {
		p: {"process": p, "today_fresh": 0, "today_rejected": 0, "week_fresh": 0, "week_rejected": 0}
		for p in by_process
		if p != flow.CUTTING
	}
	for r in receipts:
		row = output.setdefault(
			r.production_process,
			{
				"process": r.production_process,
				"today_fresh": 0,
				"today_rejected": 0,
				"week_fresh": 0,
				"week_rejected": 0,
			},
		)
		row["week_fresh"] += cint(r.total_fresh)
		row["week_rejected"] += cint(r.total_rejected)
		if getdate(r.posting_date) == today:
			row["today_fresh"] += cint(r.total_fresh)
			row["today_rejected"] += cint(r.total_rejected)
	for row in output.values():
		row["today_rejection"] = _pct(row["today_rejected"], row["today_fresh"] + row["today_rejected"])
		row["week_rejection"] = _pct(row["week_rejected"], row["week_fresh"] + row["week_rejected"])

	# Contractor rejection over all their receipts.
	party_totals = defaultdict(lambda: [0, 0])
	for r in frappe.get_all(
		"Process Receive", filters={"docstatus": 1, "party": ("is", "set")},
		fields=["party", "total_fresh", "total_rejected"], limit_page_length=0,
	):  # fmt: skip
		party_totals[r.party][0] += cint(r.total_fresh)
		party_totals[r.party][1] += cint(r.total_rejected)
	contractors = []
	for name in sorted(set(by_party) | set(party_totals)):
		row = by_party.get(
			name, {"party": name, "bundles": 0, "pieces": 0, "processes": set(), "oldest": None}
		)
		fresh, rejected = party_totals.get(name, [0, 0])
		contractors.append(
			{
				"party": name,
				"processes": ", ".join(sorted(row["processes"], key=lambda p: order.get(p, 99))),
				"bundles": row["bundles"],
				"pieces": row["pieces"],
				"oldest": str(row["oldest"]) if row["oldest"] else None,
				"oldest_days": date_diff(today, row["oldest"]) if row["oldest"] else None,
				"rejection": _pct(rejected, fresh + rejected),
			}
		)

	return {
		"today": str(today),
		"wip": sorted(by_process.values(), key=lambda c: order.get(c["process"], 99)),
		"contractors": contractors,
		"ageing": sorted(ageing.values(), key=lambda r: (order.get(r["process"], 99), r["party"])),
		"age_buckets": [name for name, _a, _b in AGE_BUCKETS],
		"output": sorted(output.values(), key=lambda r: order.get(r["process"], 99)),
		"pieces_in_wip": sum(c["pieces"] for c in by_process.values()),
	}


def _pct(part: float, whole: float) -> float | None:
	return flt(part / whole * 100, 1) if whole else None


@frappe.whitelist()
def get_ageing_bundles(process: str, bucket: str, party: str | None = None) -> list[dict]:
	"""Bundles issued and not received for a process / party / age bucket (Control Tower drill-down)."""
	_check()
	low, high = next((lo, hi) for name, lo, hi in AGE_BUCKETS if name == bucket)
	today = getdate(nowdate())
	filters = {
		"status": "Issued",
		"current_process": process,
		"issued_on": ("between", (add_days(today, -high), add_days(today, -low))),
	}
	filters["current_party"] = party if party else ("is", "not set")
	rows = frappe.get_all(
		"Bundle", filters=filters,
		fields=["name", "garment_order", "style", "colour", "size", "qty", "pending_repair_qty", "issued_on", "open_issue"],
		order_by="issued_on asc, name asc",
	)  # fmt: skip
	for r in rows:
		r.days = date_diff(today, r.issued_on)
	return rows


# ----------------------------------------------------------------------------------------------
# Order Tracker: progress per order through a process
# ----------------------------------------------------------------------------------------------


def order_progress(orders: list[str]) -> dict:
	"""Per order and process: pieces issued, received (fresh + rejected), in repair, and still upstream.

	Also pieces packed per order and good pieces per order. Three queries in total.
	"""
	if not orders:
		return {"process": {}, "packed": {}, "good": {}, "upstream": {}}
	seq = {p.name: p.sequence for p in flow.active_processes()}

	pi, pib = frappe.qb.DocType("Process Issue"), frappe.qb.DocType("Process Issue Bundle")
	issued = (
		frappe.qb.from_(pib).inner_join(pi).on(pi.name == pib.parent)
		.select(pi.production_process, pib.garment_order, frappe.query_builder.functions.Sum(pib.qty))
		.where((pi.docstatus == 1) & pib.garment_order.isin(orders) & (pib.parenttype == "Process Issue"))
		.groupby(pi.production_process, pib.garment_order).run()
	)  # fmt: skip
	pr, prb = frappe.qb.DocType("Process Receive"), frappe.qb.DocType("Process Receive Bundle")
	received = (
		frappe.qb.from_(prb).inner_join(pr).on(pr.name == prb.parent)
		.select(pr.production_process, prb.garment_order, frappe.query_builder.functions.Sum(prb.fresh_qty + prb.rejected_qty))
		.where((pr.docstatus == 1) & prb.garment_order.isin(orders) & (prb.parenttype == "Process Receive"))
		.groupby(pr.production_process, prb.garment_order).run()
	)  # fmt: skip
	bundles = frappe.get_all(
		"Bundle", filters={"garment_order": ("in", orders)},
		fields=["garment_order", "status", "current_process", "qty", "packed_qty", "pending_repair_qty"],
		limit_page_length=0,
	)  # fmt: skip

	progress: dict = defaultdict(lambda: defaultdict(lambda: {"issued": 0, "received": 0, "repair": 0}))
	for process, order, qty in issued:
		progress[order][process]["issued"] += cint(qty)
	for process, order, qty in received:
		progress[order][process]["received"] += cint(qty)
	packed: dict[str, int] = defaultdict(int)
	good: dict[str, int] = defaultdict(int)
	upstream: dict = defaultdict(lambda: defaultdict(int))  # order -> process -> pieces not yet there
	for b in bundles:
		packed[b.garment_order] += cint(b.packed_qty)
		if b.status == "Rejected":
			continue
		good[b.garment_order] += cint(b.qty)
		if b.status == "Issued":
			progress[b.garment_order][b.current_process]["repair"] += cint(b.pending_repair_qty)
		here = seq.get(b.current_process, 0)
		for process, s in seq.items():
			if s > here:
				upstream[b.garment_order][process] += cint(b.qty)
	return {"process": progress, "packed": packed, "good": good, "upstream": upstream}


def stage_for_process(orders: list, context: dict, process: str) -> dict:
	if process not in {p.name for p in flow.active_processes()}:
		return {o.name: {"state": "pending", "detail": _("Not used")} for o in orders}
	data = context.get("production")
	if data is None:
		data = context["production"] = order_progress([o.name for o in orders])
	result = {}
	for o in orders:
		values = data["process"].get(o.name, {}).get(process, {"issued": 0, "received": 0, "repair": 0})
		issued, received, repair = values["issued"], values["received"], values["repair"]
		target = issued + data["upstream"].get(o.name, {}).get(process, 0)
		hint = _("{0} pcs in repair").format(repair) if repair else ""
		if not issued:
			result[o.name] = {"state": "pending", "detail": _("Not started"), "hint": hint}
		elif target and received >= target:
			result[o.name] = {"state": "done", "detail": _("{0} pcs · 100%").format(received), "hint": hint}
		else:
			pct = round(received / target * 100) if target else 0
			result[o.name] = {
				"state": "active",
				"detail": _("{0}/{1} · {2}%").format(received, target, pct),
				"hint": hint,
			}
	return result


def stage_packing_progress(orders: list, context: dict) -> dict:
	data = context.get("production")
	if data is None:
		data = context["production"] = order_progress([o.name for o in orders])
	result = {}
	for o in orders:
		packed, good = cint(data["packed"].get(o.name)), cint(data["good"].get(o.name))
		if not packed:
			result[o.name] = {"state": "pending", "detail": _("Not started")}
		elif good and packed >= good:
			result[o.name] = {"state": "done", "detail": _("{0} pcs · 100%").format(packed)}
		else:
			pct = round(packed / good * 100) if good else 0
			result[o.name] = {"state": "active", "detail": _("{0}/{1} · {2}%").format(packed, good, pct)}
	return result
