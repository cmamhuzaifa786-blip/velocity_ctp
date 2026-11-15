"""Accessories consumed into finished pieces at packing (standard Repack, no custom ledger).

Accessories issued to a Garment Order sit in the process WIP warehouses as accessory items (Accessory
Issue). When a Packing List is submitted, the accessories of that order not yet consumed are consumed in
proportion to the pieces packed:

    consumed now = not yet consumed x packed now / good pieces of the order not yet packed

(whole units for whole-number UOMs; the last packing takes the rest). The Packing List's stock entry
becomes a Repack: pieces (from the packing source WIP) and the accessories are consumed, and the packed
variants are produced into the Finished Goods Store with their own value plus the accessory value shared
by quantity. GL: Dr Finished Goods (stock) / Cr WIP for both, balanced.
"""

from __future__ import annotations

import math
from collections import defaultdict

import frappe
from frappe.utils import cint, flt


def unconsumed_accessories(
	garment_order: str, exclude_packing_list: str | None = None
) -> dict[tuple[str, str], float]:
	"""{(item, warehouse): issued - returned - consumed} for the order."""
	result: dict[tuple[str, str], float] = defaultdict(float)
	for item, warehouse, qty in frappe.db.sql(
		"""select aii.item, ai.wip_warehouse,
			sum(case when ai.issue_type = 'Return' then -aii.qty else aii.qty end)
		from `tabAccessory Issue Item` aii join `tabAccessory Issue` ai on ai.name = aii.parent
		where ai.docstatus = 1 and ai.garment_order = %s group by aii.item, ai.wip_warehouse""",
		garment_order,
	):
		result[(item, warehouse)] += flt(qty)
	for item, warehouse, qty in frappe.db.sql(
		"""select pla.item, pla.warehouse, sum(pla.qty)
		from `tabPacking List Accessory` pla join `tabPacking List` pl on pl.name = pla.parent
		where pl.docstatus = 1 and pl.garment_order = %s and pl.name != %s group by pla.item, pla.warehouse""",
		(garment_order, exclude_packing_list or ""),
	):
		result[(item, warehouse)] -= flt(qty)
	return {k: v for k, v in result.items() if v > 1e-9}


def pieces_left_to_pack(garment_order: str) -> int:
	"""Good pieces of the order (bundle quantities after rejections) not yet packed."""
	row = frappe.db.sql(
		"select ifnull(sum(qty), 0), ifnull(sum(packed_qty), 0) from `tabBundle` where garment_order = %s",
		garment_order,
	)[0]
	return max(cint(row[0]) - cint(row[1]), 0)


def consumption(
	garment_order: str, packed_now: int, left_before: int, exclude: str | None = None
) -> list[dict]:
	"""Accessory rows {item, warehouse, qty, uom} to consume for `packed_now` pieces."""
	if packed_now <= 0:
		return []
	share = 1.0 if left_before <= packed_now else packed_now / left_before
	rows = []
	for (item, warehouse), left in sorted(unconsumed_accessories(garment_order, exclude).items()):
		uom = frappe.get_cached_value("Item", item, "stock_uom")
		qty = left * share
		if share < 1 and frappe.get_cached_value("UOM", uom, "must_be_whole_number"):
			qty = math.floor(qty + 1e-9)
		in_stock = flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "actual_qty"))
		qty = flt(min(qty, in_stock), 6)
		if qty > 0:
			rows.append({"item": item, "warehouse": warehouse, "qty": qty, "uom": uom})
	return rows


def make_packing_repack(
	company: str, posting_date, remarks: str, pieces: list[dict], accessories: list[dict], fg_store: str
):
	"""Repack: pieces + accessories out, packed variants into the Finished Goods Store.

	Returns (stock entry, {accessory row index: (rate, amount)}).
	"""
	from velocity_ctp.cutting.stock import _new_entry, _post
	from velocity_ctp.production.absorption import set_finished_values

	entry = _new_entry("Repack", company, posting_date, remarks)
	piece_rows: dict[str, list[int]] = defaultdict(list)
	qty_by_item: dict[str, float] = defaultdict(float)
	for p in pieces:
		if flt(p["qty"]) <= 0:
			continue
		entry.append("items", {"item_code": p["item_code"], "qty": p["qty"], "s_warehouse": p["s_warehouse"]})
		piece_rows[p["item_code"]].append(len(entry.items) - 1)
		qty_by_item[p["item_code"]] += flt(p["qty"])
	accessory_rows = []
	for a in accessories:
		entry.append("items", {"item_code": a["item"], "qty": a["qty"], "s_warehouse": a["warehouse"]})
		accessory_rows.append(len(entry.items) - 1)
	finished = {}
	for item, qty in qty_by_item.items():
		entry.append(
			"items",
			{
				"item_code": item,
				"qty": qty,
				"t_warehouse": fg_store,
				"is_finished_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": 0,
			},
		)
		finished[item] = len(entry.items) - 1
	total_qty = sum(qty_by_item.values())

	def distribute(e):
		accessory_value = sum(flt(e.items[i].basic_amount) for i in accessory_rows)
		rows, targets = [], []
		for item, index in finished.items():
			own = sum(flt(e.items[i].basic_amount) for i in piece_rows[item])
			rows.append(e.items[index])
			targets.append(own + accessory_value * qty_by_item[item] / total_qty)
		set_finished_values(e, rows, targets)

	name = _post(entry, distribute=distribute)
	values = {
		k: (flt(entry.items[i].valuation_rate), flt(entry.items[i].amount))
		for k, i in enumerate(accessory_rows)
	}
	return name, values
