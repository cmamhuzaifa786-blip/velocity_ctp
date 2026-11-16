# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""GRN Register: submitted Purchase Receipt rows with challan, lot, shade, accepted and rejected
quantity, and the excess or shortage of the PO row received so far (received to date - ordered)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Purchase Receipt", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 105},
		{
			"fieldname": "purchase_receipt",
			"label": _("GRN"),
			"fieldtype": "Link",
			"options": "Purchase Receipt",
			"width": 180,
		},
		{
			"fieldname": "supplier",
			"label": _("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 280,
		},
		{"fieldname": "supplier_challan_no", "label": _("Challan No."), "fieldtype": "Data", "width": 115},
		{
			"fieldname": "purchase_order",
			"label": _("Purchase Order"),
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 205,
		},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 210},
		{"fieldname": "supplier_lot_no", "label": _("Lot"), "fieldtype": "Data", "width": 110},
		{"fieldname": "shade", "label": _("Shade"), "fieldtype": "Data", "width": 85},
		{"fieldname": "batch_no", "label": _("Batch"), "fieldtype": "Link", "options": "Batch", "width": 265},
		{"fieldname": "received_qty", "label": _("Received"), "fieldtype": "Float", "width": 90},
		{"fieldname": "accepted_qty", "label": _("Accepted"), "fieldtype": "Float", "width": 90},
		{"fieldname": "rejected_qty", "label": _("Rejected"), "fieldtype": "Float", "width": 85},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 65},
		{"fieldname": "po_qty", "label": _("PO Qty"), "fieldtype": "Float", "width": 90},
		{
			"fieldname": "excess_short",
			"label": _("Excess / (Short) vs PO"),
			"fieldtype": "Float",
			"width": 150,
		},
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 115,
		},
	]


def data(filters):
	pr = frappe.qb.DocType("Purchase Receipt")
	pri = frappe.qb.DocType("Purchase Receipt Item")
	poi = frappe.qb.DocType("Purchase Order Item")
	from_date = filters.from_date or get_first_day(nowdate())
	to_date = filters.to_date or getdate(nowdate())
	query = (
		frappe.qb.from_(pri)
		.inner_join(pr)
		.on(pr.name == pri.parent)
		.left_join(poi)
		.on(poi.name == pri.purchase_order_item)
		.select(
			pr.posting_date,
			pr.name.as_("purchase_receipt"),
			pr.supplier,
			pr.supplier_challan_no,
			pri.purchase_order,
			pri.item_code,
			pri.supplier_lot_no,
			pri.shade,
			pri.batch_no,
			pri.received_qty,
			pri.qty.as_("accepted_qty"),
			pri.rejected_qty,
			pri.uom,
			pri.garment_order,
			poi.qty.as_("po_qty"),
			poi.received_qty.as_("po_received"),
		)
		.where(
			(pri.parenttype == "Purchase Receipt")
			& (pr.docstatus == 1)
			& (pr.is_return == 0)
			& (pr.posting_date >= from_date)
			& (pr.posting_date <= to_date)
		)
		.orderby(pr.posting_date)
		.orderby(pr.name)
		.orderby(pri.idx)
	)
	for field in ("supplier", "company"):
		if filters.get(field):
			query = query.where(pr[field] == filters.get(field))
	for field in ("item_code", "garment_order", "purchase_order"):
		if filters.get(field):
			query = query.where(pri[field] == filters.get(field))
	if filters.supplier_lot_no:
		query = query.where(pri.supplier_lot_no.like(f"%{filters.supplier_lot_no}%"))

	allowed = set(frappe.get_list("Purchase Receipt", filters={"docstatus": 1}, pluck="name"))
	rows = []
	for r in query.run(as_dict=True):
		if r.purchase_receipt not in allowed:
			continue
		r.excess_short = flt(flt(r.po_received) - flt(r.po_qty), 3) if r.po_qty is not None else None
		rows.append(r)
	return rows
