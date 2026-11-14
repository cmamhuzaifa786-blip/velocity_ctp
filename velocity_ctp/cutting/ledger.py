"""Cutting quantities read from submitted documents (one query each, no per-row queries).

These are summaries of our own documents for validation and reporting. Stock itself lives only in
ERPNext's Stock Ledger (through the Stock Entries); batch stock is always checked with ERPNext.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import frappe
from frappe.utils import cint, flt

FabricKey = tuple[str, str]  # (fabric_item, batch_no)
PieceKey = tuple[str, str, str]  # (garment_order, colour lower, size lower)


def piece_key(garment_order: str, colour: str, size: str) -> PieceKey:
	return (garment_order, (colour or "").strip().lower(), (size or "").strip().lower())


def job_fabric(
	job_maps: Iterable[str],
	exclude_fabric_issue: str | None = None,
	exclude_cut_receive: str | None = None,
) -> dict[str, dict[FabricKey, dict[str, float]]]:
	"""{job_map: {(item, batch): {"issued", "returned", "used"}}} from submitted documents."""
	job_maps = list(job_maps)
	result: dict[str, dict[FabricKey, dict[str, float]]] = defaultdict(
		lambda: defaultdict(lambda: {"issued": 0.0, "returned": 0.0, "used": 0.0})
	)
	if not job_maps:
		return result

	fi = frappe.qb.DocType("Fabric Issue")
	fii = frappe.qb.DocType("Fabric Issue Item")
	query = (
		frappe.qb.from_(fii)
		.inner_join(fi)
		.on(fi.name == fii.parent)
		.select(fi.job_map, fi.issue_type, fii.fabric_item, fii.batch_no, fii.qty)
		.where((fi.docstatus == 1) & fi.job_map.isin(job_maps) & (fii.parenttype == "Fabric Issue"))
	)
	if exclude_fabric_issue:
		query = query.where(fi.name != exclude_fabric_issue)
	for job_map, issue_type, item, batch, qty in query.run():
		key = "issued" if issue_type == "Issue" else "returned"
		result[job_map][(item, batch)][key] += flt(qty)

	cr = frappe.qb.DocType("Cut Receive")
	crf = frappe.qb.DocType("Cut Receive Fabric")
	query = (
		frappe.qb.from_(crf)
		.inner_join(cr)
		.on(cr.name == crf.parent)
		.select(cr.job_map, crf.fabric_item, crf.batch_no, crf.used_qty)
		.where((cr.docstatus == 1) & cr.job_map.isin(job_maps) & (crf.parenttype == "Cut Receive"))
	)
	if exclude_cut_receive:
		query = query.where(cr.name != exclude_cut_receive)
	for job_map, item, batch, used in query.run():
		result[job_map][(item, batch)]["used"] += flt(used)
	return result


def fabric_balance(values: dict[str, float]) -> float:
	"""Fabric issued to a Job Map that is neither used nor returned (still in Cutting WIP)."""
	return flt(values["issued"] - values["returned"] - values["used"], 6)


def cut_quantities(
	garment_orders: Iterable[str], exclude_cut_receive: str | None = None
) -> dict[PieceKey, dict[str, int]]:
	"""{(order, colour, size): {"cut", "rejected"}} across submitted Cut Receives."""
	garment_orders = list(garment_orders)
	result: dict[PieceKey, dict[str, int]] = defaultdict(lambda: {"cut": 0, "rejected": 0})
	if not garment_orders:
		return result
	cr = frappe.qb.DocType("Cut Receive")
	crp = frappe.qb.DocType("Cut Receive Piece")
	query = (
		frappe.qb.from_(crp)
		.inner_join(cr)
		.on(cr.name == crp.parent)
		.select(crp.garment_order, crp.colour, crp.size, crp.cut_qty, crp.rejected_qty)
		.where(
			(cr.docstatus == 1) & crp.garment_order.isin(garment_orders) & (crp.parenttype == "Cut Receive")
		)
	)
	if exclude_cut_receive:
		query = query.where(cr.name != exclude_cut_receive)
	for order, colour, size, cut, rejected in query.run():
		values = result[piece_key(order, colour, size)]
		values["cut"] += cint(cut)
		values["rejected"] += cint(rejected)
	return result


def order_cut_totals(garment_orders: Iterable[str]) -> dict[str, int]:
	"""{garment_order: total cut qty} across submitted Cut Receives."""
	totals: dict[str, int] = defaultdict(int)
	for (order, _colour, _size), values in cut_quantities(garment_orders).items():
		totals[order] += values["cut"]
	return totals


def submitted_cutting_documents(job_map: str) -> list[tuple[str, str]]:
	"""Submitted Fabric Issues, Cutting Markers and Cut Receives of a Job Map: [(doctype, name)]."""
	found = []
	for doctype in ("Fabric Issue", "Cutting Marker", "Cut Receive"):
		for name in frappe.get_all(
			doctype, filters={"job_map": job_map, "docstatus": 1}, pluck="name", limit=3
		):
			found.append((doctype, name))
	return found
