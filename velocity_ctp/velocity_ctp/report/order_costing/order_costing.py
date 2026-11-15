# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Order Costing: Cost Sheet estimate against actual cost per piece, per Garment Order (PKR).

Actuals come from figures stored on the source documents when they were submitted:
- Fabric: Cut Receive pieces (fabric value of each marker's pieces)
- Accessories: Packing Lists (accessories consumed into the packed pieces) / packed pieces
- Contractor: contractor charges per process (Cut Receive with a contractor, outsourced Process Receives),
  amount / pieces of that process, summed over the processes
- In-house conversion: absorbed labour and overheads per process, the same way
Estimates: Cost Sheet fabric and accessory cost, and its Processing heads split by the Cost Head's
Conversion Type (Contractor / In-house). Total Cost = these four + the Cost Sheet's other heads
(overheads, commercial) at estimate; a category without any actual yet is counted at its estimate.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from velocity_ctp.costing.actuals import actual_accessory_cost, actual_conversion_cost, actual_fabric_cost
from velocity_ctp.cutting.settings import get_settings

PKR = "Company:company:default_currency"
CATEGORIES = (
	("fabric", "Fabric"),
	("accessories", "Accessories"),
	("contractor", "Contractor"),
	("in_house", "In-house Conversion"),
)


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def money(fieldname: str, label: str, width: int = 140) -> dict:
	return {"fieldname": fieldname, "label": label, "fieldtype": "Currency", "options": PKR, "width": width}


def columns() -> list[dict]:
	cols = [
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
			"width": 150,
		},
		{"fieldname": "quantity", "label": _("Order Qty"), "fieldtype": "Int", "width": 85},
		{"fieldname": "pieces_cut", "label": _("Good Pieces Cut"), "fieldtype": "Int", "width": 120},
		{"fieldname": "packed_pcs", "label": _("Packed"), "fieldtype": "Int", "width": 80},
	]
	for key, label in CATEGORIES:
		cols.append(money(f"{key}_estimate", _("{0} / Pc (Estimate)").format(_(label)), 175))
		cols.append(money(f"{key}_actual", _("{0} / Pc (Actual)").format(_(label)), 165))
	cols += [
		money("total_estimate", _("Total Cost / Pc (Estimate)"), 185),
		money("total_actual", _("Total Cost / Pc (Actual)"), 175),
		money("quoted_fob", _("Quoted FOB / Pc (PKR)"), 165),
		{
			"fieldname": "estimated_margin_percent",
			"label": _("Margin % (Estimate)"),
			"fieldtype": "Percent",
			"width": 145,
		},
		{
			"fieldname": "actual_margin_percent",
			"label": _("Actual Margin %"),
			"fieldtype": "Percent",
			"width": 125,
		},
		money("variance", _("Variance / Pc (Actual - Estimate)"), 225),
		{"fieldname": "actual_basis", "label": _("Actual Covers"), "fieldtype": "Data", "width": 430},
	]
	return cols


def estimates(sheet_names: list[str]) -> dict[str, dict]:
	"""{cost sheet: {fabric, accessories, contractor, in_house, total, quoted, margin}} per piece in PKR."""
	if not sheet_names:
		return {}
	sheets = {
		s.name: s
		for s in frappe.get_all(
			"Cost Sheet",
			filters={"name": ("in", sheet_names)},
			fields=[
				"name",
				"fabric_cost_pkr",
				"accessory_cost_pkr",
				"costed_fob_pkr",
				"quoted_fob_pkr",
				"profit_fob_percent",
			],
		)
	}
	conversion_type = dict(frappe.get_all("Cost Head", fields=["name", "conversion_type"], as_list=True))
	processing: dict[str, dict] = defaultdict(lambda: {"contractor": 0.0, "in_house": 0.0})
	for parent, head, section, amount in frappe.db.sql(
		"""select parent, cost_head, section, amount_pkr from `tabCost Sheet Head`
		where parenttype = 'Cost Sheet' and parent in %(p)s""",
		{"p": sheet_names},
	):
		if section == "Processing":
			key = "in_house" if conversion_type.get(head) == "In-house" else "contractor"
			processing[parent][key] += flt(amount)
	return {
		name: {
			"fabric": flt(s.fabric_cost_pkr, 2),
			"accessories": flt(s.accessory_cost_pkr, 2),
			"contractor": flt(processing[name]["contractor"], 2),
			"in_house": flt(processing[name]["in_house"], 2),
			"total": flt(s.costed_fob_pkr, 2),
			"quoted": flt(s.quoted_fob_pkr, 2),
			"margin": flt(s.profit_fob_percent, 2),
		}
		for name, s in sheets.items()
	}


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
		fields=["name", "customer", "style", "status", "cost_sheet", "total_order_qty", "company"],
		order_by="name asc",
	)
	names = [o.name for o in orders]
	est = estimates(list({o.cost_sheet for o in orders if o.cost_sheet}))
	fabric = actual_fabric_cost(names)
	conversion = actual_conversion_cost(names)
	accessories = actual_accessory_cost(names)
	target = flt(get_settings().target_margin_percent)

	rows = []
	for o in orders:
		e = est.get(o.cost_sheet)
		f = fabric.get(o.name, {"value": 0, "pcs": 0})
		a = accessories.get(o.name, {"value": 0, "pcs": 0})
		c = conversion.get(o.name, {})
		actual = {
			"fabric": flt(f["value"] / f["pcs"], 2) if f["pcs"] else None,
			"accessories": flt(a["value"] / a["pcs"], 2) if a["pcs"] and a["value"] else None,
			"contractor": flt(c["contractor"], 2) if c.get("has_contractor") else None,
			"in_house": flt(c["in_house"], 2) if c.get("has_in_house") else None,
		}
		row = {
			"garment_order": o.name,
			"customer": o.customer,
			"style": o.style,
			"status": _(o.status),
			"cost_sheet": o.cost_sheet,
			"quantity": cint(o.total_order_qty),
			"pieces_cut": f["pcs"],
			"packed_pcs": a["pcs"],
			"target_margin": target,
			"company": o.company,
			"actual_basis": ", ".join(_(label) for key, label in CATEGORIES if actual[key] is not None)
			or _("No actuals yet"),
		}
		for key, _label in CATEGORIES:
			row[f"{key}_estimate"] = e[key] if e else None
			row[f"{key}_actual"] = actual[key]
		if e:
			other = e["total"] - sum(e[key] for key, _label in CATEGORIES)
			total_actual = other + sum(
				actual[key] if actual[key] is not None else e[key] for key, _label in CATEGORIES
			)
			row.update(
				{
					"total_estimate": e["total"],
					"total_actual": flt(total_actual, 2),
					"quoted_fob": e["quoted"],
					"estimated_margin_percent": e["margin"],
					"actual_margin_percent": flt((e["quoted"] - total_actual) / e["quoted"] * 100, 2)
					if e["quoted"]
					else None,
					"variance": flt(total_actual - e["total"], 2),
				}
			)
		rows.append(row)
	return rows
