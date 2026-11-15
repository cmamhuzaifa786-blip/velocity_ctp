# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Order Closing Sheet: per Garment Order, quantities through the factory and the result per piece.

Costs per piece are split so that actual and estimated figures are never mixed silently:
- Production Cost (Actual): fabric + accessories + contractor + in-house conversion, from the values
  stored on the source documents at submit (the same value the finished pieces carry in stock and in
  the Delivery Notes' cost of goods sold). A category without any actual yet uses its Cost Sheet
  estimate; "Actual Covers" lists the categories that are actual.
- Rejection Cost (Actual): value of the pieces rejected at the processes (stored when they moved to the
  Rejection Store), spread over the shipped pieces. Pieces rejected at cutting carry no separate value:
  their fabric is already in the good pieces' fabric cost.
- Commercial Costs (Estimate): the Cost Sheet's "Percent of Quoted FOB" heads (commission, bank,
  insurance, sample, service charges).
- Other Costs (Estimate): the Cost Sheet's remaining per-piece heads outside production (courier,
  clearing, transport, pocketing and similar).
Each order has detail rows per order colour (quantities only; the cut colour is shown when the colour
is cut from another one). Costs are per order.
Margins: Production Margin % = (quoted - production - rejection) / quoted; Full Margin % = (quoted -
total) / quoted. Quoted is the Cost Sheet's quoted FOB in PKR.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

from velocity_ctp.costing.actuals import actual_accessory_cost, actual_conversion_cost, actual_fabric_cost
from velocity_ctp.shipping.delivery import shipped_qty
from velocity_ctp.velocity_ctp.report.order_costing.order_costing import CATEGORIES, estimates

PKR = "Company:company:default_currency"
PERCENT = "Percent of Quoted FOB"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Garment Order", "read", throw=True)
	message = _(
		"Production and Rejection Cost are actual (values stored in stock when the work was done); Commercial "
		"and Other Costs are Cost Sheet estimates. Hover a column header for its definition."
	)
	return columns(), data(filters), message


def col(fieldname, label, fieldtype, width, description, **kw):
	return {
		"fieldname": fieldname,
		"label": label,
		"fieldtype": fieldtype,
		"width": width,
		"description": description,
		**kw,
	}


def money(fieldname, label, width, description):
	return col(fieldname, label, "Currency", width, description, options=PKR)


def columns():
	return [
		col("garment_order", _("Garment Order"), "Link", 125, _("The order."), options="Garment Order"),
		col("customer", _("Customer"), "Link", 130, _("Customer of the order."), options="Customer"),
		col("status", _("Status"), "Data", 110, _("Order status.")),
		col("order_colour", _("Order Colour"), "Data", 120, _("Detail rows: the colour the buyer ordered.")),
		col(
			"cut_colour",
			_("Cut Colour"),
			"Data",
			110,
			_("Detail rows: the colour it is cut in, when different."),
		),
		col("ordered", _("Ordered"), "Int", 80, _("Order quantity.")),
		col("cut", _("Cut (Good)"), "Int", 90, _("Good pieces of submitted Cut Receives.")),
		col("rejected", _("Rejected"), "Int", 85, _("Pieces rejected at cutting and at the processes.")),
		col("packed", _("Packed"), "Int", 80, _("Pieces on submitted Packing Lists.")),
		col("shipped", _("Shipped"), "Int", 80, _("Pieces on submitted Delivery Notes.")),
		col(
			"short_excess_percent", _("Short / Excess %"), "Percent", 125, _("(Shipped - Ordered) / Ordered.")
		),
		money("fabric", _("Fabric / Pc"), 115, _("Actual: fabric value of the good pieces (Cut Receive).")),
		money(
			"accessories",
			_("Accessories / Pc"),
			135,
			_("Actual: accessories consumed into packed pieces (Packing Lists)."),
		),
		money(
			"contractor",
			_("Contractor / Pc"),
			130,
			_("Actual: contractor charges per process, summed (Cut Receive, Process Receive)."),
		),
		money(
			"in_house",
			_("In-house / Pc"),
			120,
			_("Actual: absorbed labour and overheads per process, summed (Process Receive)."),
		),
		money(
			"production_cost",
			_("Production Cost (Actual)"),
			180,
			_(
				"Fabric + accessories + contractor + in-house per good piece, from stored stock values. Categories with "
				"no actual yet use the Cost Sheet estimate (see Actual Covers)."
			),
		),
		money(
			"rejection_cost",
			_("Rejection Cost (Actual)"),
			170,
			_(
				"Actual: value of pieces rejected at the processes (stored when moved to the Rejection Store), divided "
				"by shipped pieces."
			),
		),
		money(
			"commercial_costs",
			_("Commercial Costs (Estimate)"),
			195,
			_(
				"Estimate: Cost Sheet heads calculated as a percentage of the quoted FOB (commission, bank, insurance, "
				"sample, service)."
			),
		),
		money(
			"other_costs",
			_("Other Costs (Estimate)"),
			165,
			_(
				"Estimate: the Cost Sheet's other per-piece heads outside production (courier, clearing, transport, pocketing)."
			),
		),
		money(
			"total_cost",
			_("Total Cost / Pc"),
			135,
			_("Production + Rejection + Commercial + Other (actual and estimates as marked)."),
		),
		money("quoted", _("Quoted / Pc (PKR)"), 135, _("Cost Sheet quoted FOB in PKR.")),
		col(
			"production_margin_percent",
			_("Production Margin %"),
			"Percent",
			150,
			_("(Quoted - Production Cost - Rejection Cost) / Quoted: actual figures only."),
		),
		col(
			"full_margin_percent",
			_("Full Margin %"),
			"Percent",
			115,
			_("(Quoted - Total Cost) / Quoted: includes the estimated commercial and other costs."),
		),
		col(
			"estimated_margin_percent",
			_("Cost Sheet Margin %"),
			"Percent",
			145,
			_("Estimate: the Cost Sheet's own profit %."),
		),
		col(
			"actual_basis",
			_("Actual Covers"),
			"Data",
			420,
			_("Production categories with actual figures; the others use the estimate."),
		),
	]


def split_estimates(sheet_names: list[str]) -> dict[str, dict]:
	"""{cost sheet: {"commercial", "other"}} per piece: percentage heads, and per-piece heads outside production."""
	result: dict[str, dict] = defaultdict(lambda: {"commercial": 0.0, "other": 0.0})
	if not sheet_names:
		return result
	production_heads = {"Fabric Cost", "Accessory Cost"}
	for parent, head, section, calculation, amount in frappe.db.sql(
		"""select parent, cost_head, section, calculation, amount_pkr from `tabCost Sheet Head`
		where parenttype = 'Cost Sheet' and parent in %(p)s""",
		{"p": sheet_names},
	):
		if section == "Freight":
			continue  # outside the FOB cost
		if calculation == PERCENT:
			result[parent]["commercial"] += flt(amount)
		elif section != "Processing" and head not in production_heads:
			result[parent]["other"] += flt(amount)
	return result


def data(filters):
	conditions = {"docstatus": 1}
	for field in ("customer", "status"):
		if filters.get(field):
			conditions[field] = filters[field]
	if filters.garment_order:
		conditions["name"] = filters.garment_order
	orders = frappe.get_list(
		"Garment Order",
		filters=conditions,
		fields=["name", "customer", "status", "cost_sheet", "total_order_qty"],
		order_by="name asc",
	)
	names = [o.name for o in orders] or [""]
	sheets = list({o.cost_sheet for o in orders if o.cost_sheet})
	est = estimates(sheets)
	extra = split_estimates(sheets)
	fabric = actual_fabric_cost(names)
	conversion = actual_conversion_cost(names)
	accessories = actual_accessory_cost(names)
	shipped = shipped_qty(names)

	cut_rejected = dict(
		frappe.db.sql(
			"""select crp.garment_order, sum(crp.rejected_qty) from `tabCut Receive Piece` crp join `tabCut Receive` cr
			on cr.name = crp.parent where cr.docstatus = 1 and crp.garment_order in %(o)s group by crp.garment_order""",
			{"o": names},
		)
	)
	process_rejected = {
		order: (cint(qty), flt(value))
		for order, qty, value in frappe.db.sql(
			"""select prb.garment_order, sum(prb.rejected_qty), sum(prb.rejected_value) from `tabProcess Receive Bundle` prb
			join `tabProcess Receive` pr on pr.name = prb.parent where pr.docstatus = 1 and prb.garment_order in %(o)s
			group by prb.garment_order""",
			{"o": names},
		)
	}
	packed = dict(
		frappe.db.sql(
			"""select garment_order, sum(total_pcs) from `tabPacking List`
			where docstatus = 1 and garment_order in %(o)s group by garment_order""",
			{"o": names},
		)
	)

	colour_rows = colour_quantities([o.name for o in orders])
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
		used = [actual[k] if actual[k] is not None else (e[k] if e else None) for k, _label in CATEGORIES]
		production = (
			flt(sum(v for v in used if v is not None), 2) if any(v is not None for v in used) else None
		)
		ordered, ship = cint(o.total_order_qty), cint(shipped.get(o.name, 0))
		rej_qty, rej_value = process_rejected.get(o.name, (0, 0.0))
		rejection = flt(rej_value / ship, 2) if ship else None
		commercial = flt(extra[o.cost_sheet]["commercial"], 2) if e else None
		other = flt(extra[o.cost_sheet]["other"], 2) if e else None
		total = (
			flt((production or 0) + (rejection or 0) + (commercial or 0) + (other or 0), 2)
			if production is not None
			else None
		)
		quoted = e["quoted"] if e else None
		rows.append(
			{
				"garment_order": o.name,
				"customer": o.customer,
				"status": _(o.status),
				"ordered": ordered,
				"cut": f["pcs"],
				"rejected": cint(cut_rejected.get(o.name, 0)) + rej_qty,
				"packed": cint(packed.get(o.name, 0)),
				"shipped": ship,
				"short_excess_percent": flt((ship - ordered) / ordered * 100, 2)
				if ordered and ship
				else None,
				**actual,
				"production_cost": production,
				"rejection_cost": rejection,
				"commercial_costs": commercial,
				"other_costs": other,
				"total_cost": total,
				"quoted": quoted,
				"production_margin_percent": flt(
					(quoted - (production or 0) - (rejection or 0)) / quoted * 100, 2
				)
				if quoted and production is not None
				else None,
				"full_margin_percent": flt((quoted - total) / quoted * 100, 2)
				if quoted and total is not None
				else None,
				"estimated_margin_percent": e["margin"] if e else None,
				"actual_basis": ", ".join(_(label) for key, label in CATEGORIES if actual[key] is not None)
				or _("No actuals yet"),
				"row_id": o.name,
				"parent_row": None,
				"indent": 0,
			}
		)
		for line in colour_rows.get(o.name, []):
			rows.append(
				{
					**line,
					"garment_order": o.name,
					"row_id": f"{o.name}|{line['order_colour']}",
					"parent_row": o.name,
					"indent": 1,
				}
			)
	return rows


def colour_quantities(orders: list[str]) -> dict[str, list[dict]]:
	"""Per order and order colour: ordered, cut, rejected, packed and shipped pieces."""
	from velocity_ctp.cutting.colours import colour_maps

	if not orders:
		return {}
	values: dict[tuple[str, str], dict] = {}

	def line(order, colour):
		key = (order, (colour or "").lower())
		return values.setdefault(
			key, {"order_colour": colour, "ordered": 0, "cut": 0, "rejected": 0, "packed": 0, "shipped": 0}
		)

	o = {"o": orders}
	for order, colour, qty in frappe.db.sql(
		"""select parent, colour, sum(order_qty) from `tabGarment Order Item`
		where parenttype = 'Garment Order' and parent in %(o)s group by parent, colour""",
		o,
	):
		line(order, colour)["ordered"] += cint(qty)
	for order, colour, good, rejected in frappe.db.sql(
		"""select crp.garment_order, crp.colour, sum(crp.good_qty), sum(crp.rejected_qty) from `tabCut Receive Piece` crp
		join `tabCut Receive` cr on cr.name = crp.parent where cr.docstatus = 1 and crp.garment_order in %(o)s
		group by crp.garment_order, crp.colour""",
		o,
	):
		entry = line(order, colour)
		entry["cut"] += cint(good)
		entry["rejected"] += cint(rejected)
	for order, colour, rejected in frappe.db.sql(
		"""select prb.garment_order, ifnull(b.order_colour, prb.colour), sum(prb.rejected_qty) from `tabProcess Receive Bundle` prb
		join `tabProcess Receive` pr on pr.name = prb.parent left join `tabBundle` b on b.name = prb.bundle
		where pr.docstatus = 1 and prb.garment_order in %(o)s group by prb.garment_order, ifnull(b.order_colour, prb.colour)""",
		o,
	):
		line(order, colour)["rejected"] += cint(rejected)
	for order, colour, qty in frappe.db.sql(
		"""select pl.garment_order, plc.colour, sum(plc.total_pcs) from `tabPacking List Carton` plc
		join `tabPacking List` pl on pl.name = plc.parent where pl.docstatus = 1 and pl.garment_order in %(o)s
		group by pl.garment_order, plc.colour""",
		o,
	):
		line(order, colour)["packed"] += cint(qty)
	for order, colour, qty in frappe.db.sql(
		"""select dn.garment_order, va.attribute_value, sum(dni.stock_qty) from `tabDelivery Note Item` dni
		join `tabDelivery Note` dn on dn.name = dni.parent
		join `tabItem Variant Attribute` va on va.parent = dni.item_code and va.attribute = 'Colour'
		where dn.docstatus = 1 and dn.garment_order in %(o)s group by dn.garment_order, va.attribute_value""",
		o,
	):
		line(order, colour)["shipped"] += cint(qty)
	cut_of = colour_maps(orders)
	result: dict[str, list[dict]] = {}
	for (order, key), v in sorted(values.items()):
		v["cut_colour"] = cut_of.get((order, key)) or ""
		v["short_excess_percent"] = (
			flt((v["shipped"] - v["ordered"]) / v["ordered"] * 100, 2)
			if v["ordered"] and v["shipped"]
			else None
		)
		result.setdefault(order, []).append(v)
	return result
