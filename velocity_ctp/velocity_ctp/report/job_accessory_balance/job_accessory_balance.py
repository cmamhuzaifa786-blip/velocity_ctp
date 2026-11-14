# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Job Accessory Balance: per job (Job Map + Garment Order) and accessory.

Required comes from the order's Material Plan, allocated from submitted Accessory Allocations (less
released), issued and returned from submitted Accessory Issues. Balance to issue = required - (issued -
returned). Shortfall is the Material Plan shortfall (the same calculation as the Material Plan form).
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from velocity_ctp.procurement.availability import compute, plan_requirements
from velocity_ctp.setup.install import get_default_company


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Accessory Issue", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{
			"fieldname": "job_map",
			"label": _("Job Map"),
			"fieldtype": "Link",
			"options": "Job Map",
			"width": 120,
		},
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 120,
		},
		{"fieldname": "item", "label": _("Accessory"), "fieldtype": "Link", "options": "Item", "width": 290},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 65},
		{"fieldname": "required", "label": _("Required"), "fieldtype": "Float", "width": 95},
		{"fieldname": "allocated", "label": _("Allocated"), "fieldtype": "Float", "width": 95},
		{"fieldname": "issued", "label": _("Issued"), "fieldtype": "Float", "width": 90},
		{"fieldname": "returned", "label": _("Returned"), "fieldtype": "Float", "width": 90},
		{"fieldname": "balance_to_issue", "label": _("Balance to Issue"), "fieldtype": "Float", "width": 120},
		{
			"fieldname": "unissued_allocation",
			"label": _("Unissued Allocation"),
			"fieldtype": "Float",
			"width": 135,
		},
		{"fieldname": "shortfall", "label": _("Shortfall"), "fieldtype": "Float", "width": 95},
		{
			"fieldname": "material_plan",
			"label": _("Material Plan"),
			"fieldtype": "Link",
			"options": "Material Plan",
			"width": 120,
		},
	]


def data(filters):
	from velocity_ctp.velocity_ctp.doctype.material_plan.material_plan import job_maps_of_orders

	company = filters.company or get_default_company()
	jobs = frappe.get_all(
		"Job Map Order",
		filters={"parenttype": "Job Map", **({"parent": filters.job_map} if filters.job_map else {})},
		fields=["parent as job_map", "garment_order"],
	)
	if filters.garment_order:
		jobs = [j for j in jobs if j.garment_order == filters.garment_order]
	if not filters.job_map and not filters.include_closed:
		closed = set(frappe.get_all("Job Map", filters={"job_closed": 1}, pluck="name"))
		jobs = [j for j in jobs if j.job_map not in closed]
	if not jobs:
		return []
	orders = list({j.garment_order for j in jobs})

	plans = {
		p.garment_order: p.name
		for p in frappe.get_all(
			"Material Plan",
			filters={"garment_order": ("in", orders), "docstatus": 1},
			fields=["name", "garment_order"],
		)
	}
	needs = plan_requirements(list(plans.values()))
	plan_job_map = job_maps_of_orders(orders)

	lines: dict[tuple[str, str, str], dict] = defaultdict(
		lambda: {
			"required": 0.0,
			"allocated": 0.0,
			"unissued_allocation": 0.0,
			"issued": 0.0,
			"returned": 0.0,
			"uom": None,
		}
	)
	wanted_jobs = {(j.job_map, j.garment_order) for j in jobs}
	for order, plan in plans.items():
		jm = plan_job_map.get(order)
		if (jm, order) not in wanted_jobs:
			continue
		for item, line in needs.get(plan, {}).items():
			if line["kind"] == "Accessory":
				entry = lines[(jm, order, item)]
				entry["required"] += line["required"]
				entry["uom"] = line["uom"]

	for r in frappe.db.sql(
		"""select aa.job_map, aa.garment_order, aai.item, sum(aai.qty - aai.released_qty) as allocated,
			sum(greatest(aai.qty - aai.released_qty - aai.issued_qty, 0)) as unissued
		from `tabAccessory Allocation Item` aai join `tabAccessory Allocation` aa on aa.name = aai.parent
		where aa.docstatus = 1 and aa.garment_order in %(orders)s group by aa.job_map, aa.garment_order, aai.item""",
		{"orders": orders},
		as_dict=True,
	):
		if (r.job_map, r.garment_order) in wanted_jobs:
			entry = lines[(r.job_map, r.garment_order, r.item)]
			entry["allocated"] += flt(r.allocated)
			entry["unissued_allocation"] += flt(r.unissued)

	for r in frappe.db.sql(
		"""select ai.job_map, ai.garment_order, aii.item,
			sum(case when ai.issue_type = 'Issue' then aii.qty else 0 end) as issued,
			sum(case when ai.issue_type = 'Return' then aii.qty else 0 end) as returned
		from `tabAccessory Issue Item` aii join `tabAccessory Issue` ai on ai.name = aii.parent
		where ai.docstatus = 1 and ai.garment_order in %(orders)s group by ai.job_map, ai.garment_order, aii.item""",
		{"orders": orders},
		as_dict=True,
	):
		if (r.job_map, r.garment_order) in wanted_jobs:
			entry = lines[(r.job_map, r.garment_order, r.item)]
			entry["issued"] += flt(r.issued)
			entry["returned"] += flt(r.returned)

	if filters.item:
		lines = {k: v for k, v in lines.items() if k[2] == filters.item}

	shortfall: dict[tuple[str, str], float] = {}
	targets = [{"name": plan, "garment_order": order, "needs": None} for order, plan in plans.items()]
	for plan, rows in compute(company, targets).items() if targets else []:
		for row in rows:
			shortfall[(plan, row["item_code"])] = row["shortfall"]

	items = {k[2] for k in lines}
	info = {
		i.name: i
		for i in frappe.get_all(
			"Item", filters={"name": ("in", list(items) or [""])}, fields=["name", "item_name", "stock_uom"]
		)
	}
	result = []
	for (jm, order, item), v in sorted(lines.items()):
		plan = plans.get(order)
		net = v["issued"] - v["returned"]
		result.append(
			{
				"job_map": jm,
				"garment_order": order,
				"item": item,
				"item_name": info.get(item, {}).get("item_name"),
				"uom": v["uom"] or info.get(item, {}).get("stock_uom"),
				"required": flt(v["required"], 3),
				"allocated": flt(v["allocated"], 3),
				"issued": flt(v["issued"], 3),
				"returned": flt(v["returned"], 3),
				"balance_to_issue": flt(max(v["required"] - net, 0.0), 3) if v["required"] else 0.0,
				"unissued_allocation": flt(v["unissued_allocation"], 3),
				"shortfall": flt(shortfall.get((plan, item), 0.0), 3) if plan else None,
				"material_plan": plan,
			}
		)
	return result
