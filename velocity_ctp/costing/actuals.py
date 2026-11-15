"""Actual costs per Garment Order from figures stored on the source documents when they were submitted."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt


def actual_fabric_cost(orders: list[str]) -> dict[str, dict]:
	"""{garment_order: {"value", "pcs"}} from the fabric cost stored on submitted Cut Receive pieces.

	Fabric Cost Amount is stored per piece row when the Cut Receive is submitted (the value the
	Repack posted to those pieces); value / pcs is the quantity-weighted cost per piece.
	"""
	if not orders:
		return {}
	cr = frappe.qb.DocType("Cut Receive")
	crp = frappe.qb.DocType("Cut Receive Piece")
	Sum = frappe.query_builder.functions.Sum
	rows = (
		frappe.qb.from_(crp)
		.inner_join(cr)
		.on(cr.name == crp.parent)
		.select(crp.garment_order, Sum(crp.fabric_cost_amount), Sum(crp.good_qty))
		.where((cr.docstatus == 1) & crp.garment_order.isin(orders) & (crp.parenttype == "Cut Receive"))
		.groupby(crp.garment_order)
		.run()
	)
	return {order: {"value": flt(value), "pcs": cint(pcs)} for order, value, pcs in rows}


def actual_conversion_cost(orders: list[str]) -> dict[str, dict]:
	"""{garment_order: {"contractor": per pc, "in_house": per pc}} from amounts stored at submit.

	Per process: amount / pieces (Cut Receive good pieces, Process Receive fresh pieces), then summed over
	the processes, so a piece that went through cutting, stitching, washing and finishing carries the
	cost of each step.
	"""
	if not orders:
		return {}
	per_process: dict[tuple[str, str], dict] = {}
	for order, process, contractor, in_house, qty in frappe.db.sql(
		"""select crp.garment_order, 'Cutting', sum(crp.contractor_cost_amount), sum(crp.conversion_cost_amount), sum(crp.good_qty)
		from `tabCut Receive Piece` crp join `tabCut Receive` cr on cr.name = crp.parent
		where cr.docstatus = 1 and crp.parenttype = 'Cut Receive' and crp.garment_order in %(o)s group by crp.garment_order
		union all
		select prb.garment_order, pr.production_process, sum(prb.contractor_cost_amount), sum(prb.conversion_cost_amount),
			sum(prb.fresh_qty)
		from `tabProcess Receive Bundle` prb join `tabProcess Receive` pr on pr.name = prb.parent
		where pr.docstatus = 1 and prb.parenttype = 'Process Receive' and prb.garment_order in %(o)s
		group by prb.garment_order, pr.production_process""",
		{"o": orders},
	):
		per_process[(order, process)] = {
			"contractor": flt(contractor),
			"in_house": flt(in_house),
			"qty": cint(qty),
		}
	result: dict[str, dict] = {}
	for (order, _process), v in per_process.items():
		entry = result.setdefault(
			order, {"contractor": 0.0, "in_house": 0.0, "has_contractor": False, "has_in_house": False}
		)
		if v["qty"]:
			entry["contractor"] += v["contractor"] / v["qty"]
			entry["in_house"] += v["in_house"] / v["qty"]
		entry["has_contractor"] |= v["contractor"] > 0
		entry["has_in_house"] |= v["in_house"] > 0
	return result


def actual_accessory_cost(orders: list[str]) -> dict[str, dict]:
	"""{garment_order: {"value", "pcs"}}: accessories consumed into packed pieces (Packing Lists)."""
	if not orders:
		return {}
	return {
		order: {"value": flt(value), "pcs": cint(pcs)}
		for order, value, pcs in frappe.db.sql(
			"""select garment_order, sum(accessory_amount), sum(total_pcs) from `tabPacking List`
			where docstatus = 1 and garment_order in %(o)s group by garment_order""",
			{"o": orders},
		)
	}
