"""Shipment figures for the Order Tracker (Shipped stage) and Velocity Home (KPIs, Ready to Ship)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, getdate, nowdate

from velocity_ctp.shipping.delivery import shipped_qty


def invoiced_qty(orders: list[str]) -> dict[str, tuple[float, int]]:
	"""{garment_order: (pieces on submitted Sales Invoices, number of invoices)}."""
	if not orders:
		return {}
	return {
		order: (flt(qty), cint(count))
		for order, qty, count in frappe.db.sql(
			"""select si.garment_order, sum(sii.stock_qty), count(distinct si.name) from `tabSales Invoice Item` sii
			join `tabSales Invoice` si on si.name = sii.parent
			where si.docstatus = 1 and si.is_return = 0 and si.garment_order in %(o)s group by si.garment_order""",
			{"o": orders},
		)
	}


def stage_shipped(orders: list[frappe._dict], context: dict) -> dict[str, dict]:
	"""Shipped: pieces on submitted Delivery Notes of the order quantity; invoiced status in the tooltip."""
	from velocity_ctp.cutting.settings import get_settings

	names = [o.name for o in orders]
	shipped = shipped_qty(names)
	invoiced = invoiced_qty(names)
	tolerance = flt(get_settings().shipment_tolerance_percent)
	result = {}
	for o in orders:
		qty, total = flt(shipped.get(o.name)), cint(o.total_order_qty)
		inv_qty, inv_count = invoiced.get(o.name, (0, 0))
		hint = (
			_("Invoiced {0} pcs on {1} invoice(s)").format(f"{inv_qty:g}", inv_count)
			if inv_count
			else _("Not invoiced yet")
		)
		if not qty:
			result[o.name] = {"state": "pending", "detail": _("Not shipped")}
			continue
		pct = round(qty / total * 100) if total else 0
		done = total and qty >= total * (1 - tolerance / 100)
		result[o.name] = {
			"state": "done" if done else "active",
			"detail": _("{0}/{1} · {2}%").format(f"{qty:g}", total, pct),
			"hint": hint,
		}
	return result


def shipped_this_month(company: str | None) -> dict:
	start = get_first_day(nowdate())
	row = frappe.db.sql(
		"""select ifnull(sum(total_qty), 0), ifnull(sum(base_net_total), 0) from `tabDelivery Note`
		where docstatus = 1 and is_return = 0 and posting_date >= %s and (%s is null or company = %s)""",
		(start, company, company),
	)[0]
	return {"pcs": flt(row[0]), "value": flt(row[1]), "from": str(start)}


def ready_to_ship(limit: int = 10) -> list[dict]:
	"""Garment Orders with submitted Packing Lists that are not on a Delivery Note yet."""
	rows = frappe.db.sql(
		"""select pl.garment_order, go.customer, go.ship_date, count(*) as lists, sum(pl.total_pcs) as pcs,
			sum(pl.total_cartons) as cartons
		from `tabPacking List` pl join `tabGarment Order` go on go.name = pl.garment_order
		where pl.docstatus = 1 and ifnull(pl.delivery_note, '') = '' group by pl.garment_order
		order by go.ship_date, pl.garment_order limit %s""",
		limit,
		as_dict=True,
	)
	today = getdate(nowdate())
	for r in rows:
		r.days_left = (getdate(r.ship_date) - today).days if r.ship_date else None
	return rows
