"""Actual costs from posted documents (Phase 5: fabric only; other heads are estimates)."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cint, flt


def actual_fabric_cost(orders: list[str]) -> dict[str, dict]:
	"""{garment_order: {"value", "pcs"}}: value of the pieces produced by Cut Receive Repacks.

	The Repack posts, per marker, its fabric rows followed by its good-piece rows (see
	velocity_ctp.cutting.stock.make_cut_repack); the same grouping is rebuilt here to find the
	value posted to each order's pieces.
	"""
	result: dict[str, dict] = defaultdict(lambda: {"value": 0.0, "pcs": 0})
	if not orders:
		return result
	receives = frappe.get_all(
		"Cut Receive Piece",
		filters={"garment_order": ("in", orders), "parenttype": "Cut Receive"},
		pluck="parent",
		distinct=True,
	)
	for name in receives:
		receive = frappe.get_doc("Cut Receive", name)
		if receive.docstatus != 1 or not receive.stock_entry:
			continue
		marker_order = dict(
			frappe.get_all(
				"Cutting Marker",
				filters={"name": ("in", [m.cutting_marker for m in receive.markers])},
				fields=["name", "garment_order"],
				as_list=True,
			)
		)
		rows = sorted(frappe.get_doc("Stock Entry", receive.stock_entry).items, key=lambda r: r.idx)
		position = 0
		for group in receive.marker_groups():
			position += len(group["fabric"])
			order = marker_order.get(group["marker"])
			for _piece in group["pieces"]:
				row = rows[position]
				position += 1
				if order in orders and row.t_warehouse:
					result[order]["value"] += flt(row.basic_amount)
					result[order]["pcs"] += cint(row.transfer_qty)
	return result
