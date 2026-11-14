# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Order Costing: the Cost Sheet estimate per Garment Order against actual fabric cost.

Actual fabric cost per piece is the value of the pieces produced by the order's Cut Receives
(fabric consumed per marker, see velocity_ctp.costing.actuals). All other costs are the Cost
Sheet estimate until later phases post them (labelled "Estimate").
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from velocity_ctp.costing.actuals import actual_fabric_cost
from velocity_ctp.cutting.settings import get_settings

PKR = "Company:company:default_currency"


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns() -> list[dict]:
	return [
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 130,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 120,
		},
		{"fieldname": "style", "label": _("Style"), "fieldtype": "Link", "options": "Style", "width": 115},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 105},
		{
			"fieldname": "cost_sheet",
			"label": _("Cost Sheet"),
			"fieldtype": "Link",
			"options": "Cost Sheet",
			"width": 155,
		},
		{"fieldname": "quantity", "label": _("Order Qty"), "fieldtype": "Int", "width": 90},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
		{
			"fieldname": "quoted_fob",
			"label": _("Quoted FOB"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 105,
		},
		{
			"fieldname": "costed_fob",
			"label": _("Costed FOB (Estimate)"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 160,
		},
		{
			"fieldname": "estimated_profit_percent",
			"label": _("Profit % (Estimate)"),
			"fieldtype": "Percent",
			"width": 145,
		},
		{
			"fieldname": "fabric_cost_estimate",
			"label": _("Fabric / Pc (Estimate, PKR)"),
			"fieldtype": "Currency",
			"options": PKR,
			"width": 190,
		},
		{
			"fieldname": "fabric_cost_actual",
			"label": _("Fabric / Pc (Actual, PKR)"),
			"fieldtype": "Currency",
			"options": PKR,
			"width": 175,
		},
		{
			"fieldname": "fabric_variance",
			"label": _("Fabric Variance / Pc (PKR)"),
			"fieldtype": "Currency",
			"options": PKR,
			"width": 185,
		},
		{
			"fieldname": "fabric_variance_percent",
			"label": _("Fabric Variance %"),
			"fieldtype": "Percent",
			"width": 140,
		},
		{"fieldname": "pieces_cut", "label": _("Good Pieces Cut"), "fieldtype": "Int", "width": 125},
		{
			"fieldname": "other_costs_estimate",
			"label": _("Other Costs / Pc (Estimate, PKR)"),
			"fieldtype": "Currency",
			"options": PKR,
			"width": 220,
		},
	]


def data(filters: frappe._dict) -> list[dict]:
	order_filters = {"docstatus": 1}
	for field in ("customer", "status"):
		if filters.get(field):
			order_filters[field] = filters[field]
	if filters.garment_order:
		order_filters["name"] = filters.garment_order
	if filters.only_costed:
		order_filters["cost_sheet"] = ("is", "set")
	orders = frappe.get_list(
		"Garment Order",
		filters=order_filters,
		fields=[
			"name",
			"customer",
			"style",
			"status",
			"cost_sheet",
			"total_order_qty",
			"currency",
			"company",
		],
		order_by="name asc",
	)
	sheets = {
		s.name: s
		for s in frappe.get_all(
			"Cost Sheet",
			filters={"name": ("in", [o.cost_sheet for o in orders if o.cost_sheet] or [""])},
			fields=[
				"name",
				"quoted_fob_fc",
				"costed_fob_fc",
				"profit_fob_percent",
				"fabric_cost_pkr",
				"costed_fob_pkr",
				"currency",
			],
		)
	}
	actual = actual_fabric_cost([o.name for o in orders])
	target = flt(get_settings().target_margin_percent)
	rows = []
	for o in orders:
		cs = sheets.get(o.cost_sheet)
		act = actual.get(o.name, {"value": 0, "pcs": 0})
		actual_pc = flt(act["value"] / act["pcs"], 2) if act["pcs"] else None
		estimate_pc = flt(cs.fabric_cost_pkr, 2) if cs else None
		variance = flt(actual_pc - estimate_pc, 2) if actual_pc is not None and estimate_pc else None
		rows.append(
			{
				"garment_order": o.name,
				"customer": o.customer,
				"style": o.style,
				"status": _(o.status),
				"cost_sheet": o.cost_sheet,
				"quantity": cint(o.total_order_qty),
				"currency": cs.currency if cs else o.currency,
				"quoted_fob": cs.quoted_fob_fc if cs else None,
				"costed_fob": cs.costed_fob_fc if cs else None,
				"estimated_profit_percent": cs.profit_fob_percent if cs else None,
				"fabric_cost_estimate": estimate_pc,
				"fabric_cost_actual": actual_pc,
				"fabric_variance": variance,
				"fabric_variance_percent": flt(variance / estimate_pc * 100, 2)
				if variance is not None and estimate_pc
				else None,
				"pieces_cut": act["pcs"],
				"other_costs_estimate": flt(cs.costed_fob_pkr - cs.fabric_cost_pkr, 2) if cs else None,
				"target_margin": target,
				"company": o.company,
			}
		)
	return rows
