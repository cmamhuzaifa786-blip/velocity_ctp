# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""PO Status: every Purchase Order row with ordered, received and pending quantity (stock UOM),
days overdue and the approval state."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

CLOSED = ("Closed", "Completed", "Delivered")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Purchase Order", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{
			"fieldname": "supplier",
			"label": _("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 280,
		},
		{
			"fieldname": "purchase_order",
			"label": _("Purchase Order"),
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 205,
		},
		{"fieldname": "po_category", "label": _("Category"), "fieldtype": "Data", "width": 110},
		{"fieldname": "po_type", "label": _("Type"), "fieldtype": "Data", "width": 85},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 210},
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 120,
		},
		{"fieldname": "ordered", "label": _("Ordered"), "fieldtype": "Float", "width": 95},
		{"fieldname": "received", "label": _("Received"), "fieldtype": "Float", "width": 95},
		{"fieldname": "pending", "label": _("Pending"), "fieldtype": "Float", "width": 95},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
		{"fieldname": "schedule_date", "label": _("Required By"), "fieldtype": "Date", "width": 105},
		{"fieldname": "days_overdue", "label": _("Days Overdue"), "fieldtype": "Int", "width": 95},
		{"fieldname": "approval_status", "label": _("Approval Status"), "fieldtype": "Data", "width": 190},
		{"fieldname": "status", "label": _("PO Status"), "fieldtype": "Data", "width": 160},
	]


def data(filters):
	po = frappe.qb.DocType("Purchase Order")
	poi = frappe.qb.DocType("Purchase Order Item")
	query = (
		frappe.qb.from_(poi)
		.inner_join(po)
		.on(po.name == poi.parent)
		.select(
			po.supplier,
			po.name.as_("purchase_order"),
			po.po_category,
			po.po_type,
			po.workflow_state,
			po.status,
			po.docstatus,
			poi.item_code,
			poi.garment_order,
			poi.stock_qty,
			poi.received_qty,
			poi.conversion_factor,
			poi.stock_uom.as_("uom"),
			poi.schedule_date,
		)
		.where((poi.parenttype == "Purchase Order") & (po.docstatus < 2))
		.orderby(poi.schedule_date)
		.orderby(po.name)
		.orderby(poi.idx)
	)
	for field in ("supplier", "po_category", "po_type", "company"):
		if filters.get(field):
			query = query.where(po[field] == filters.get(field))
	if filters.garment_order:
		query = query.where(poi.garment_order == filters.garment_order)
	if filters.item_code:
		query = query.where(poi.item_code == filters.item_code)
	if filters.from_date:
		query = query.where(po.transaction_date >= filters.from_date)
	if filters.to_date:
		query = query.where(po.transaction_date <= filters.to_date)

	allowed = set(frappe.get_list("Purchase Order", filters={"docstatus": ("<", 2)}, pluck="name"))
	today = getdate(nowdate())
	rows = []
	for r in query.run(as_dict=True):
		if r.purchase_order not in allowed:
			continue
		ordered = flt(r.stock_qty)
		received = flt(flt(r.received_qty) * flt(r.conversion_factor or 1), 3)
		pending = flt(max(ordered - received, 0.0), 3) if r.status not in CLOSED else 0.0
		if filters.only_pending and not pending:
			continue
		overdue = (
			date_diff(today, r.schedule_date)
			if r.docstatus == 1 and pending > 0 and r.schedule_date and getdate(r.schedule_date) < today
			else 0
		)
		if filters.only_overdue and not overdue:
			continue
		rows.append(
			{
				**r,
				"ordered": ordered,
				"received": received,
				"pending": pending,
				"days_overdue": overdue,
				"approval_status": _(r.workflow_state)
				if r.workflow_state
				else (_("Approved") if r.docstatus == 1 else _("Draft")),
				"status": _(r.status),
			}
		)
	return rows
