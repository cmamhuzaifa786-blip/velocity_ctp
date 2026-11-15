"""Shipment: standard Delivery Notes made from submitted Packing Lists, and order completion.

"Create Delivery Note" maps the order's Sales Order with ERPNext's own mapping and sets the quantity
of each variant from the Packing Lists (Finished Goods Store). A Packing List can be on one active
Delivery Note only, and a Delivery Note cannot deliver more of a variant than its Packing Lists hold.
A Garment Order becomes Completed when the pieces shipped reach the order quantity less the Shipment
Tolerance % (Velocity Settings); cancelling a Delivery Note opens it again.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt

EPS = 1e-9


def packed_by_variant(packing_lists: list[str]) -> dict[str, int]:
	"""{item_code: pieces} on the given Packing Lists."""
	result: dict[str, int] = defaultdict(int)
	for item, qty in frappe.db.sql(
		"""select item_code, sum(total_pcs) from `tabPacking List Carton`
		where parenttype = 'Packing List' and parent in %(p)s group by item_code""",
		{"p": packing_lists or [""]},
	):
		result[item] += cint(qty)
	return result


def active_delivery_of(packing_list: str, exclude: str | None = None) -> str | None:
	"""The Delivery Note (not cancelled) that already ships this Packing List."""
	rows = frappe.db.sql(
		"""select dn.name from `tabShipment Packing List` spl join `tabDelivery Note` dn on dn.name = spl.parent
		where spl.parenttype = 'Delivery Note' and spl.packing_list = %s and dn.docstatus < 2 and dn.name != %s
		limit 1""",
		(packing_list, exclude or ""),
	)
	return rows[0][0] if rows else None


def check_packing_lists(names: list[str], exclude_delivery: str | None = None) -> list[frappe._dict]:
	"""Submitted Packing Lists of one Garment Order and Sales Order, none shipped elsewhere."""
	if not names:
		frappe.throw(_("Please select at least one Packing List."))
	lists = frappe.get_all(
		"Packing List",
		filters={"name": ("in", names)},
		fields=[
			"name",
			"docstatus",
			"garment_order",
			"sales_order",
			"total_pcs",
			"total_cartons",
			"net_weight",
			"gross_weight",
		],
	)
	if len(lists) != len(set(names)):
		frappe.throw(_("One of the Packing Lists does not exist."))
	for pl in lists:
		if pl.docstatus != 1:
			frappe.throw(_("Packing List {0} is not submitted.").format(frappe.bold(pl.name)))
		taken = active_delivery_of(pl.name, exclude_delivery)
		if taken:
			frappe.throw(
				_("Packing List {0} is already shipped on Delivery Note {1}.").format(
					frappe.bold(pl.name), frappe.bold(taken)
				),
				title=_("Already Delivered"),
			)
	orders = {pl.garment_order for pl in lists}
	if len(orders) > 1:
		frappe.throw(
			_("Packing Lists of different Garment Orders ({0}) cannot be shipped together.").format(
				", ".join(sorted(orders))
			)
		)
	return lists


def sales_order_of(garment_order: str, lists: list[frappe._dict]) -> str:
	so = next((pl.sales_order for pl in lists if pl.sales_order), None) or frappe.db.get_value(
		"Garment Order", garment_order, "sales_order"
	)
	if not so or frappe.db.get_value("Sales Order", so, "docstatus") != 1:
		frappe.throw(
			_("Garment Order {0} needs a submitted Sales Order before it can be delivered.").format(
				frappe.bold(garment_order)
			),
			title=_("Sales Order Needed"),
		)
	return so


@frappe.whitelist(methods=["POST"])
def make_delivery_note(packing_lists: str | list) -> str:
	"""Draft Delivery Note for the given Packing Lists (ERPNext's Sales Order -> Delivery Note mapping)."""
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note as map_delivery_note

	from velocity_ctp.production.stock import get_finished_goods_store

	frappe.has_permission("Packing List", "read", throw=True)
	names = frappe.parse_json(packing_lists) if isinstance(packing_lists, str) else packing_lists
	lists = check_packing_lists(names)
	order = lists[0].garment_order
	so = sales_order_of(order, lists)
	need = packed_by_variant(names)

	dn = map_delivery_note(so)
	store = get_finished_goods_store(dn.company)
	rows = []
	for row in dn.items:
		qty = need.pop(row.item_code, 0)
		if qty:
			row.qty = qty
			row.warehouse = store
			rows.append(row)
	if need:
		frappe.throw(
			_("Variant(s) {0} are packed but not on Sales Order {1} (or already fully delivered).").format(
				", ".join(sorted(need)), frappe.bold(so)
			)
		)
	dn.set("items", rows)
	for i, row in enumerate(dn.items, 1):
		row.idx = i
	dn.garment_order = order
	dn.set("packing_lists", [])
	for pl in lists:
		dn.append(
			"packing_lists",
			{
				"packing_list": pl.name,
				"total_pcs": pl.total_pcs,
				"total_cartons": pl.total_cartons,
				"net_weight": pl.net_weight,
				"gross_weight": pl.gross_weight,
			},
		)
	try:
		dn.insert()
	except frappe.PermissionError:
		if frappe.message_log:
			frappe.message_log.pop()
		frappe.throw(
			_("Creating a Delivery Note needs a standard ERPNext role such as Stock User or Sales User."),
			frappe.PermissionError,
		)
	return dn.name


# ----------------------------------------------------------------------------------------------
# Delivery Note hooks
# ----------------------------------------------------------------------------------------------


def delivery_note_validate(doc, method=None) -> None:
	if doc.is_return or not doc.get("packing_lists"):
		return
	names = [r.packing_list for r in doc.packing_lists]
	if len(names) != len(set(names)):
		frappe.throw(_("A Packing List is added more than once."))
	lists = check_packing_lists(names, exclude_delivery=doc.name)
	order = lists[0].garment_order
	if doc.get("garment_order") and doc.garment_order != order:
		frappe.throw(
			_("The Packing Lists are for Garment Order {0}, not {1}.").format(order, doc.garment_order)
		)
	doc.garment_order = order
	by_name = {pl.name: pl for pl in lists}
	for row in doc.packing_lists:
		pl = by_name[row.packing_list]
		row.update({k: pl.get(k) for k in ("total_pcs", "total_cartons", "net_weight", "gross_weight")})
	packed = packed_by_variant(names)
	delivering: dict[str, float] = defaultdict(float)
	for row in doc.items:
		delivering[row.item_code] += flt(row.stock_qty or row.qty)
	for item, qty in delivering.items():
		if qty > packed.get(item, 0) + EPS:
			frappe.throw(
				_(
					"{0}: {1} pieces are on this Delivery Note, but its Packing Lists hold {2} (packed and not yet "
					"delivered)."
				).format(frappe.bold(item), f"{qty:g}", packed.get(item, 0)),
				title=_("More Than Packed"),
			)


def delivery_note_on_submit(doc, method=None) -> None:
	if doc.is_return:
		return
	for row in doc.get("packing_lists") or []:
		frappe.db.set_value(
			"Packing List", row.packing_list, "delivery_note", doc.name, update_modified=False
		)
	if doc.get("garment_order"):
		update_order_completion(doc.garment_order)


def delivery_note_on_cancel(doc, method=None) -> None:
	if doc.is_return:
		return
	for row in doc.get("packing_lists") or []:
		if frappe.db.get_value("Packing List", row.packing_list, "delivery_note") == doc.name:
			frappe.db.set_value(
				"Packing List", row.packing_list, "delivery_note", None, update_modified=False
			)
	if doc.get("garment_order"):
		update_order_completion(doc.garment_order)


# ----------------------------------------------------------------------------------------------
# Order completion
# ----------------------------------------------------------------------------------------------


def shipped_qty(orders: list[str]) -> dict[str, float]:
	"""{garment_order: pieces delivered} from submitted Delivery Notes (returns deducted)."""
	if not orders:
		return {}
	return {
		order: flt(qty)
		for order, qty in frappe.db.sql(
			"""select dn.garment_order, sum(dni.stock_qty) from `tabDelivery Note Item` dni
			join `tabDelivery Note` dn on dn.name = dni.parent
			where dn.docstatus = 1 and dn.garment_order in %(o)s group by dn.garment_order""",
			{"o": orders},
		)
	}


def update_order_completion(garment_order: str) -> None:
	"""Completed when shipped >= order qty x (1 - tolerance); reopened when a delivery is cancelled."""
	from velocity_ctp.cutting.settings import get_settings

	order = frappe.get_doc("Garment Order", garment_order)
	if order.docstatus != 1 or order.status == "Cancelled":
		return
	tolerance = flt(get_settings().shipment_tolerance_percent)
	shipped = shipped_qty([garment_order]).get(garment_order, 0)
	complete = shipped >= cint(order.total_order_qty) * (1 - tolerance / 100) - EPS
	if complete and order.status != "Completed":
		order.db_set("status", "Completed")
		order.add_comment(
			"Info", _("Completed: {0} of {1} pieces shipped.").format(f"{shipped:g}", order.total_order_qty)
		)
	elif not complete and order.status == "Completed":
		status = order.get_resume_status()
		order.db_set("status", status)
		order.add_comment(
			"Info",
			_("Reopened ({0}): {1} of {2} pieces shipped.").format(
				_(status), f"{shipped:g}", order.total_order_qty
			),
		)
