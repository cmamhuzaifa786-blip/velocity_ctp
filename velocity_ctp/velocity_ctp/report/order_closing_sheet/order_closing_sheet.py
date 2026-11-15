# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Order Closing Sheet: per Garment Order, quantities through the factory and the actual result.

Ordered, cut (good pieces of Cut Receives), rejected (at cutting and at the processes), packed (Packing
Lists), shipped (Delivery Notes), short / excess % (shipped against ordered), and the actual cost per
piece against the quoted price with the margin, from the costs stored at submit (Phase 7, Order Costing).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from velocity_ctp.shipping.delivery import shipped_qty
from velocity_ctp.velocity_ctp.report.order_costing import order_costing

PKR = "Company:company:default_currency"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Garment Order", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 125,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 130,
		},
		{"fieldname": "style", "label": _("Style"), "fieldtype": "Link", "options": "Style", "width": 110},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "ordered", "label": _("Ordered"), "fieldtype": "Int", "width": 85},
		{"fieldname": "cut", "label": _("Cut (Good)"), "fieldtype": "Int", "width": 90},
		{"fieldname": "rejected", "label": _("Rejected"), "fieldtype": "Int", "width": 85},
		{"fieldname": "packed", "label": _("Packed"), "fieldtype": "Int", "width": 80},
		{"fieldname": "shipped", "label": _("Shipped"), "fieldtype": "Int", "width": 85},
		{
			"fieldname": "short_excess_percent",
			"label": _("Short / Excess %"),
			"fieldtype": "Percent",
			"width": 130,
		},
		{
			"fieldname": "actual_cost",
			"label": _("Actual Cost / Pc"),
			"fieldtype": "Currency",
			"options": PKR,
			"width": 135,
		},
		{
			"fieldname": "quoted",
			"label": _("Quoted / Pc (PKR)"),
			"fieldtype": "Currency",
			"options": PKR,
			"width": 135,
		},
		{"fieldname": "margin_percent", "label": _("Actual Margin %"), "fieldtype": "Percent", "width": 125},
		{
			"fieldname": "estimated_margin_percent",
			"label": _("Margin % (Estimate)"),
			"fieldtype": "Percent",
			"width": 145,
		},
		{"fieldname": "actual_basis", "label": _("Actual Covers"), "fieldtype": "Data", "width": 260},
	]


def data(filters):
	costing = {r["garment_order"]: r for r in order_costing.data(frappe._dict(filters))}
	names = list(costing) or [""]
	cut, cut_rejected = {}, {}
	for order, good, rejected in frappe.db.sql(
		"""select crp.garment_order, sum(crp.good_qty), sum(crp.rejected_qty) from `tabCut Receive Piece` crp
		join `tabCut Receive` cr on cr.name = crp.parent where cr.docstatus = 1 and crp.garment_order in %(o)s
		group by crp.garment_order""",
		{"o": names},
	):
		cut[order], cut_rejected[order] = cint(good), cint(rejected)
	process_rejected = dict(
		frappe.db.sql(
			"""select prb.garment_order, sum(prb.rejected_qty) from `tabProcess Receive Bundle` prb
		join `tabProcess Receive` pr on pr.name = prb.parent where pr.docstatus = 1 and prb.garment_order in %(o)s
		group by prb.garment_order""",
			{"o": names},
		)
	)
	packed = dict(
		frappe.db.sql(
			"select garment_order, sum(total_pcs) from `tabPacking List` where docstatus = 1 and garment_order in %(o)s group by garment_order",
			{"o": names},
		)
	)
	shipped = shipped_qty(names)
	rows = []
	for order, c in costing.items():
		ordered = cint(c["quantity"])
		ship = cint(shipped.get(order, 0))
		rows.append(
			{
				"garment_order": order,
				"customer": c["customer"],
				"style": c["style"],
				"status": c["status"],
				"ordered": ordered,
				"cut": cut.get(order, 0),
				"rejected": cut_rejected.get(order, 0) + cint(process_rejected.get(order, 0)),
				"packed": cint(packed.get(order, 0)),
				"shipped": ship,
				"short_excess_percent": flt((ship - ordered) / ordered * 100, 2)
				if ordered and ship
				else None,
				"actual_cost": c.get("total_actual"),
				"quoted": c.get("quoted_fob"),
				"margin_percent": c.get("actual_margin_percent"),
				"estimated_margin_percent": c.get("estimated_margin_percent"),
				"actual_basis": c.get("actual_basis"),
			}
		)
	return rows
