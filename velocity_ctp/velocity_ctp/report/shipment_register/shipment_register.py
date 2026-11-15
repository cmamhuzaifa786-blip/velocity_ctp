# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Shipment Register: submitted Delivery Notes with order, packing lists, cartons, pieces, value, the
Sales Invoice(s) made from them and the Gate Outward that let them out."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Delivery Note", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "delivery_note",
			"label": _("Delivery Note"),
			"fieldtype": "Link",
			"options": "Delivery Note",
			"width": 175,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 150,
		},
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 125,
		},
		{
			"fieldname": "sales_order",
			"label": _("Sales Order"),
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 165,
		},
		{"fieldname": "packing_lists", "label": _("Packing Lists"), "fieldtype": "Data", "width": 200},
		{"fieldname": "cartons", "label": _("Cartons"), "fieldtype": "Int", "width": 80},
		{"fieldname": "pcs", "label": _("Pieces"), "fieldtype": "Float", "precision": 0, "width": 85},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
		{
			"fieldname": "value",
			"label": _("Value"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"fieldname": "base_value",
			"label": _("Value (Company Currency)"),
			"fieldtype": "Currency",
			"width": 170,
		},
		{"fieldname": "sales_invoice", "label": _("Sales Invoice"), "fieldtype": "Data", "width": 175},
		{"fieldname": "invoice_status", "label": _("Invoice Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "gate_outward", "label": _("Gate Outward"), "fieldtype": "Data", "width": 135},
	]


def data(filters):
	conditions = {
		"docstatus": 1,
		"is_return": 0,
		"posting_date": [
			"between",
			[filters.from_date or get_first_day(nowdate()), filters.to_date or nowdate()],
		],
	}
	for field in ("customer", "garment_order", "company"):
		if filters.get(field):
			conditions[field] = filters[field]
	notes = frappe.get_list(
		"Delivery Note",
		filters=conditions,
		fields=[
			"name",
			"posting_date",
			"customer",
			"garment_order",
			"total_qty",
			"currency",
			"grand_total",
			"base_grand_total",
		],
		order_by="posting_date asc, name asc",
	)
	names = [n.name for n in notes] or [""]
	lists = defaultdict(list)
	cartons = defaultdict(int)
	for parent, pl, c in frappe.db.sql(
		"select parent, packing_list, total_cartons from `tabShipment Packing List` where parenttype='Delivery Note' and parent in %(n)s order by idx",
		{"n": names},
	):
		lists[parent].append(pl)
		cartons[parent] += cint(c)
	orders = dict(
		frappe.db.sql(
			"select parent, max(against_sales_order) from `tabDelivery Note Item` where parent in %(n)s group by parent",
			{"n": names},
		)
	)
	invoices = defaultdict(dict)
	for dn, si, docstatus, status in frappe.db.sql(
		"""select distinct sii.delivery_note, si.name, si.docstatus, si.status from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent where si.docstatus < 2 and sii.delivery_note in %(n)s""",
		{"n": names},
	):
		invoices[dn][si] = _(status) if docstatus == 1 else _("Draft")
	gates = defaultdict(list)
	for ref, go in frappe.db.sql(
		"select reference_name, name from `tabGate Outward` where docstatus=1 and reference_doctype='Delivery Note' and reference_name in %(n)s",
		{"n": names},
	):
		gates[ref].append(go)
	rows = []
	for n in notes:
		inv = invoices.get(n.name, {})
		rows.append(
			{
				"posting_date": n.posting_date,
				"delivery_note": n.name,
				"customer": n.customer,
				"garment_order": n.garment_order,
				"sales_order": orders.get(n.name),
				"packing_lists": ", ".join(lists.get(n.name, [])),
				"cartons": cartons.get(n.name, 0),
				"pcs": flt(n.total_qty),
				"currency": n.currency,
				"value": n.grand_total,
				"base_value": n.base_grand_total,
				"sales_invoice": ", ".join(inv),
				"invoice_status": ", ".join(inv.values()) or _("Not invoiced"),
				"gate_outward": ", ".join(gates.get(n.name, [])) or _("Not passed"),
			}
		)
	return rows
