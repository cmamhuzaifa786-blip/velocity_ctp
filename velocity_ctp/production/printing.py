"""Data for the Process Challan and Packing List print formats (exposed to Jinja through hooks)."""

from __future__ import annotations

from collections import OrderedDict

import frappe
from frappe.utils import cint


def get_challan_lines(process_issue: str) -> list[dict]:
	"""Bundles of a Process Issue grouped by order, colour and size, in size-set order."""
	frappe.has_permission("Process Issue", "print", process_issue, throw=True)
	doc = frappe.get_doc("Process Issue", process_issue)
	lines: OrderedDict = OrderedDict()
	for row in sorted(
		doc.bundles, key=lambda r: (r.garment_order or "", r.colour or "", _size_rank(r), r.bundle)
	):
		key = (row.garment_order, row.colour, row.size)
		line = lines.setdefault(
			key, {"garment_order": row.garment_order, "style": row.style, "colour": row.colour, "size": row.size,
			      "bundles": [], "qty": 0}
		)  # fmt: skip
		line["bundles"].append(row.bundle)
		line["qty"] += cint(row.qty)
	return list(lines.values())


def _size_rank(row) -> int:
	size_set = (
		frappe.get_cached_value("Garment Order", row.garment_order, "size_set") if row.garment_order else None
	)
	if not size_set:
		return 0
	sizes = [s.size.lower() for s in frappe.get_cached_doc("Size Set", size_set).sizes]
	return sizes.index((row.size or "").lower()) if (row.size or "").lower() in sizes else 99


def get_packing_summary(packing_list: str) -> dict:
	"""Colour x size matrix of packed pieces for a Packing List."""
	frappe.has_permission("Packing List", "print", packing_list, throw=True)
	doc = frappe.get_doc("Packing List", packing_list)
	size_set = frappe.db.get_value("Garment Order", doc.garment_order, "size_set")
	sizes = [s.size for s in frappe.get_cached_doc("Size Set", size_set).sizes] if size_set else []
	used = {(r.size or "").lower() for r in doc.cartons}
	sizes = [s for s in sizes if s.lower() in used] or sorted({r.size for r in doc.cartons})
	matrix: OrderedDict = OrderedDict()
	for row in doc.cartons:
		line = matrix.setdefault(row.colour, {s: 0 for s in sizes})
		size = next((s for s in sizes if s.lower() == (row.size or "").lower()), row.size)
		line[size] = line.get(size, 0) + cint(row.total_pcs)
	return {
		"sizes": sizes,
		"rows": [
			{"colour": c, "values": [v[s] for s in sizes], "total": sum(v.values())}
			for c, v in matrix.items()
		],
		"size_totals": [sum(v[s] for v in matrix.values()) for s in sizes],
		"total": doc.total_pcs,
	}
