"""Actual costs from posted documents (fabric only for now; other heads are estimates)."""

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
