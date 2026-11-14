# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Process Movement Report: every bundle line of submitted Process Issues and Process Receives."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Please set From Date and To Date."))
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))
	return columns(), data(filters)


def columns() -> list[dict]:
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 115},
		{"fieldname": "document_type", "label": _("Document Type"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "document",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "document_type",
			"width": 135,
		},
		{
			"fieldname": "process",
			"label": _("Process"),
			"fieldtype": "Link",
			"options": "Process",
			"width": 105,
		},
		{"fieldname": "party", "label": _("Party"), "fieldtype": "Link", "options": "Supplier", "width": 170},
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 130,
		},
		{"fieldname": "style", "label": _("Style"), "fieldtype": "Link", "options": "Style", "width": 120},
		{"fieldname": "colour", "label": _("Colour"), "fieldtype": "Data", "width": 115},
		{"fieldname": "size", "label": _("Size"), "fieldtype": "Data", "width": 70},
		{"fieldname": "bundle", "label": _("Bundle"), "fieldtype": "Link", "options": "Bundle", "width": 125},
		{"fieldname": "issued", "label": _("Issued"), "fieldtype": "Int", "width": 85},
		{"fieldname": "fresh", "label": _("Fresh"), "fieldtype": "Int", "width": 80},
		{"fieldname": "rejected", "label": _("Rejected"), "fieldtype": "Int", "width": 95},
		{"fieldname": "repair", "label": _("Repair"), "fieldtype": "Int", "width": 85},
		{
			"fieldname": "contractor_amount",
			"label": _("Contractor Amount"),
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def data(filters: frappe._dict) -> list[dict]:
	rows = []
	for doctype, child in (
		("Process Issue", "Process Issue Bundle"),
		("Process Receive", "Process Receive Bundle"),
	):
		parent = frappe.qb.DocType(doctype)
		row = frappe.qb.DocType(child)
		fields = [
			parent.name,
			parent.posting_date,
			parent.production_process,
			parent.party,
			row.bundle,
			row.garment_order,
			row.colour,
			row.size,
		]
		if doctype == "Process Issue":
			fields += [row.style, row.qty]
		else:
			fields += [row.fresh_qty, row.rejected_qty, row.repair_qty, row.piece_rate]
		query = (
			frappe.qb.from_(row)
			.inner_join(parent)
			.on(parent.name == row.parent)
			.select(*fields)
			.where(
				(parent.docstatus == 1)
				& (row.parenttype == doctype)
				& (parent.posting_date >= filters.from_date)
				& (parent.posting_date <= filters.to_date)
			)
		)
		if filters.process:
			query = query.where(parent.production_process == filters.process)
		if filters.party:
			query = query.where(parent.party == filters.party)
		if filters.garment_order:
			query = query.where(row.garment_order == filters.garment_order)
		for r in query.run(as_dict=True):
			line = {
				"posting_date": r.posting_date,
				"document_type": _(doctype),
				"document": r.name,
				"process": r.production_process,
				"party": r.party,
				"garment_order": r.garment_order,
				"colour": r.colour,
				"size": r.size,
				"bundle": r.bundle,
			}
			if doctype == "Process Issue":
				line.update({"style": r.style, "issued": cint(r.qty)})
			else:
				line.update(
					{
						"fresh": cint(r.fresh_qty),
						"rejected": cint(r.rejected_qty),
						"repair": cint(r.repair_qty),
						"contractor_amount": flt(cint(r.fresh_qty) * flt(r.piece_rate), 2)
						if r.party
						else None,
					}
				)
			rows.append(line)
	styles = dict(frappe.get_all("Garment Order", filters={"name": ("in", list({r["garment_order"] for r in rows}) or [""])},
	                             fields=["name", "style"], as_list=True))  # fmt: skip
	for line in rows:
		line.setdefault("style", styles.get(line["garment_order"]))
	return sorted(rows, key=lambda x: (x["posting_date"], x["document"], x["bundle"]))
