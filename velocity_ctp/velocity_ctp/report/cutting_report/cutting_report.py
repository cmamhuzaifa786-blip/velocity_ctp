# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Cutting Report: fabric and pieces per Job Map and fabric batch, with order/colour detail rows.

Level 0: Job Map + fabric + batch — issued, used and returned in the period, balance still in
Cutting WIP up to the end date, and totals of the detail rows.
Level 1: Garment Order + colour cut from that batch — planned, cut and rejected pieces, fabric used,
wastage, marker efficiency and contractor amount.

Every Cut Receive piece row and fabric row is linked to its Cutting Marker, so fabric used,
wastage and pieces are exact per marker (no allocation).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from velocity_ctp.cutting.settings import get_settings

NUMERIC_FIELDS = (
	"fabric_issued", "fabric_used", "fabric_returned", "fabric_balance", "fabric_required",
	"planned_pcs", "cut_pcs", "rejected_pcs", "contractor_amount", "efficiency_weight", "efficiency_sum",
)  # fmt: skip


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Please set From Date and To Date."))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{"fieldname": "job_map", "label": _("Job Map"), "fieldtype": "Link", "options": "Job Map", "width": 150},
		{"fieldname": "garment_order", "label": _("Garment Order"), "fieldtype": "Link", "options": "Garment Order", "width": 135},
		{"fieldname": "style", "label": _("Style"), "fieldtype": "Link", "options": "Style", "width": 130},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 115},
		{"fieldname": "fabric_item", "label": _("Fabric"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "batch_no", "label": _("Batch"), "fieldtype": "Link", "options": "Batch", "width": 145},
		{"fieldname": "fabric_issued", "label": _("Fabric Issued"), "fieldtype": "Float", "precision": 2, "width": 125},
		{"fieldname": "fabric_used", "label": _("Fabric Used"), "fieldtype": "Float", "precision": 2, "width": 120},
		{"fieldname": "fabric_returned", "label": _("Fabric Returned"), "fieldtype": "Float", "precision": 2, "width": 140},
		{"fieldname": "fabric_balance", "label": _("Balance in Cutting WIP"), "fieldtype": "Float", "precision": 2, "width": 175},
		{"fieldname": "planned_pcs", "label": _("Planned Pcs"), "fieldtype": "Int", "width": 110},
		{"fieldname": "cut_pcs", "label": _("Cut Pcs"), "fieldtype": "Int", "width": 95},
		{"fieldname": "rejected_pcs", "label": _("Rejected Pcs"), "fieldtype": "Int", "width": 120},
		{"fieldname": "wastage_percent", "label": _("Wastage %"), "fieldtype": "Percent", "width": 110},
		{"fieldname": "marker_efficiency", "label": _("Marker Efficiency %"), "fieldtype": "Percent", "width": 165},
		{"fieldname": "contractor_amount", "label": _("Contractor Amount"), "fieldtype": "Currency", "width": 165},
	]  # fmt: skip


def get_data(filters: frappe._dict) -> list[dict]:
	job_filter = {"job_map": filters.job_map} if filters.job_map else {}

	# --- fabric issues and returns ---------------------------------------------------------
	fi = frappe.qb.DocType("Fabric Issue")
	fii = frappe.qb.DocType("Fabric Issue Item")
	query = (
		frappe.qb.from_(fii)
		.inner_join(fi)
		.on(fi.name == fii.parent)
		.select(fi.job_map, fi.issue_type, fi.posting_date, fii.fabric_item, fii.batch_no, fii.qty)
		.where(
			(fi.docstatus == 1) & (fi.posting_date <= filters.to_date) & (fii.parenttype == "Fabric Issue")
		)
	)
	if filters.job_map:
		query = query.where(fi.job_map == filters.job_map)
	if filters.cutting_party:
		query = query.where(fi.cutting_party == filters.cutting_party)
	issues = query.run(as_dict=True)

	# --- cut receives in the period ----------------------------------------------------------
	cr_filters = {
		"docstatus": 1,
		"posting_date": ("between", (filters.from_date, filters.to_date)),
		**job_filter,
	}
	if filters.cutting_party:
		cr_filters["cutting_party"] = filters.cutting_party
	receives = {
		r.name: r
		for r in frappe.get_all("Cut Receive", filters=cr_filters, fields=["name", "job_map", "piece_rate"])
	}
	cr_names = list(receives) or [""]
	cr_pieces = frappe.get_all(
		"Cut Receive Piece", filters={"parent": ("in", cr_names), "parenttype": "Cut Receive"},
		fields=["parent", "cutting_marker", "cut_qty", "rejected_qty"],
	)  # fmt: skip
	cr_fabric = frappe.get_all(
		"Cut Receive Fabric", filters={"parent": ("in", cr_names), "parenttype": "Cut Receive"},
		fields=["parent", "cutting_marker", "fabric_item", "batch_no", "required_qty", "used_qty"],
	)  # fmt: skip

	# --- markers: all submitted markers of the Job Maps involved ------------------------------
	marker_filters = {"docstatus": 1, **job_filter}
	if filters.garment_order:
		marker_filters["garment_order"] = filters.garment_order
	if filters.cutting_party:
		marker_filters["cutting_party"] = filters.cutting_party
	markers = {
		m.name: m
		for m in frappe.get_all(
			"Cutting Marker", filters=marker_filters,
			fields=["name", "job_map", "garment_order", "style", "colour", "fabric_item", "batch_no",
			        "fabric_required", "total_planned_pieces", "marker_efficiency"],
		)
	}  # fmt: skip

	parents: dict[tuple, dict] = {}
	children: dict[tuple, dict] = {}

	def parent_row(job_map, item, batch):
		key = (job_map, item, batch)
		if key not in parents:
			parents[key] = {
				"job_map": job_map,
				"fabric_item": item,
				"batch_no": batch,
				**dict.fromkeys(NUMERIC_FIELDS, 0.0),
			}
		return parents[key]

	def child_row(marker):
		key = (marker.job_map, marker.fabric_item, marker.batch_no, marker.garment_order, marker.colour)
		if key not in children:
			children[key] = {
				"job_map": marker.job_map, "fabric_item": marker.fabric_item, "batch_no": marker.batch_no,
				"garment_order": marker.garment_order, "style": marker.style, "colour": marker.colour,
				**dict.fromkeys(NUMERIC_FIELDS, 0.0),
			}  # fmt: skip
		return children[key]

	from_date = getdate(filters.from_date)
	for row in issues:
		parent = parent_row(row.job_map, row.fabric_item, row.batch_no)
		in_period = getdate(row.posting_date) >= from_date
		if row.issue_type == "Issue":
			parent["fabric_balance"] += flt(row.qty)
			if in_period:
				parent["fabric_issued"] += flt(row.qty)
		else:
			parent["fabric_balance"] -= flt(row.qty)
			if in_period:
				parent["fabric_returned"] += flt(row.qty)

	# Fabric used up to the end date reduces the balance (also before the period).
	balance_used = frappe.get_all(
		"Cut Receive Fabric",
		filters={"parenttype": "Cut Receive", "parent": ("in", frappe.get_all(
			"Cut Receive", filters={"docstatus": 1, "posting_date": ("<=", filters.to_date), **job_filter}, pluck="name"
		) or [""])},
		fields=["parent", "fabric_item", "batch_no", "used_qty"],
	)  # fmt: skip
	cr_job = dict(frappe.get_all("Cut Receive", filters={"name": ("in", list({r.parent for r in balance_used}) or [""])},
	                             fields=["name", "job_map"], as_list=True))  # fmt: skip
	for row in balance_used:
		parent_row(cr_job[row.parent], row.fabric_item, row.batch_no)["fabric_balance"] -= flt(row.used_qty)

	# Planned pieces and marker efficiency: every submitted marker.
	for marker in markers.values():
		child = child_row(marker)
		child["planned_pcs"] += cint(marker.total_planned_pieces)
		child["efficiency_sum"] += flt(marker.marker_efficiency) * cint(marker.total_planned_pieces)
		child["efficiency_weight"] += cint(marker.total_planned_pieces) if marker.marker_efficiency else 0
		parent_row(marker.job_map, marker.fabric_item, marker.batch_no)

	# Cut Receives: every piece and fabric row names its marker, so the figures are exact.
	for piece in cr_pieces:
		marker = markers.get(piece.cutting_marker)
		if not marker:
			continue  # marker excluded by the filters
		child = child_row(marker)
		child["cut_pcs"] += cint(piece.cut_qty)
		child["rejected_pcs"] += cint(piece.rejected_qty)
		child["contractor_amount"] += cint(piece.cut_qty) * flt(receives[piece.parent].piece_rate)
	for fabric in cr_fabric:
		parent_row(receives[fabric.parent].job_map, fabric.fabric_item, fabric.batch_no)["fabric_used"] += (
			flt(fabric.used_qty)
		)
		marker = markers.get(fabric.cutting_marker)
		if marker:
			child = child_row(marker)
			child["fabric_used"] += flt(fabric.used_qty)
			child["fabric_required"] += flt(fabric.required_qty)

	alert = flt(get_settings().fabric_wastage_alert_percent)
	data = []
	for key in sorted(parents):
		parent = parents[key]
		kids = [c for ckey, c in sorted(children.items()) if ckey[:3] == key]
		if filters.garment_order and not kids:
			continue
		for field in ("planned_pcs", "cut_pcs", "rejected_pcs", "contractor_amount", "fabric_required",
		              "efficiency_sum", "efficiency_weight"):  # fmt: skip
			parent[field] = sum(flt(c[field]) for c in kids)
		parent_id = "|".join(key)
		data.append(finish(parent, parent_id, None, 0, alert))
		for kid in kids:
			data.append(
				finish(kid, parent_id + "|" + kid["garment_order"] + "|" + kid["colour"], parent_id, 1, alert)
			)
	return data


def finish(row: dict, row_id: str, parent: str | None, indent: int, alert: float) -> dict:
	row = dict(row)
	required = flt(row.pop("fabric_required"))
	weight = flt(row.pop("efficiency_weight"))
	efficiency_sum = flt(row.pop("efficiency_sum"))
	row["wastage_percent"] = (
		flt((flt(row["fabric_used"]) - required) / required * 100, 2) if required else None
	)
	row["wastage_alert"] = bool(alert and row["wastage_percent"] and row["wastage_percent"] > alert)
	row["marker_efficiency"] = flt(efficiency_sum / weight, 2) if weight else None
	for field in ("cut_pcs", "rejected_pcs", "planned_pcs"):
		row[field] = round(flt(row[field]))
	if indent == 1:
		for field in ("fabric_issued", "fabric_returned", "fabric_balance"):
			row[field] = None
	row.update({"row_id": row_id, "parent_row": parent, "indent": indent})
	return row
