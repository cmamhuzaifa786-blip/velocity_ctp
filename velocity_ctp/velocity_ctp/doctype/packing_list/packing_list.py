# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from velocity_ctp.production import flow, stock
from velocity_ctp.setup.install import get_default_company

Key = tuple[str, str]  # (colour lower, size lower)


def key_of(colour: str, size: str) -> Key:
	return ((colour or "").strip().lower(), (size or "").strip().lower())


def finished_bundles(garment_order: str) -> list[frappe._dict]:
	"""Bundles of the order fully received from the stage before packing, with unpacked pieces."""
	source = flow.packing_source_process()
	bundles = frappe.get_all(
		"Bundle",
		filters={"garment_order": garment_order, "current_process": source, "status": "Received"},
		fields=["name", "colour", "size", "item_code", "qty", "packed_qty", "current_warehouse"],
		order_by="name asc",
	)
	return [b for b in bundles if cint(b.qty) - cint(b.packed_qty) > 0]


@frappe.whitelist()
def get_available(garment_order: str) -> list[dict]:
	"""Finished pieces not yet packed, per colour and size (for Pick from Bundles)."""
	frappe.has_permission("Packing List", "read", throw=True)
	lines: dict[Key, dict] = {}
	for b in finished_bundles(garment_order):
		line = lines.setdefault(
			key_of(b.colour, b.size), {"colour": b.colour, "size": b.size, "qty": 0, "bundles": 0}
		)
		line["qty"] += cint(b.qty) - cint(b.packed_qty)
		line["bundles"] += 1
	size_order = {}
	size_set = frappe.db.get_value("Garment Order", garment_order, "size_set")
	for i, s in enumerate(
		frappe.get_all("Size Set Item", filters={"parent": size_set, "parenttype": "Size Set"}, pluck="size", order_by="sequence asc, idx asc")
	):  # fmt: skip
		size_order[s.lower()] = i
	return sorted(lines.values(), key=lambda line: (line["colour"], size_order.get(line["size"].lower(), 99)))


@frappe.whitelist()
def get_next_carton(garment_order: str, exclude: str | None = None) -> int:
	frappe.has_permission("Packing List", "read", throw=True)
	pl = frappe.qb.DocType("Packing List")
	plc = frappe.qb.DocType("Packing List Carton")
	query = (
		frappe.qb.from_(plc)
		.inner_join(pl)
		.on(pl.name == plc.parent)
		.select(frappe.query_builder.functions.Max(plc.carton_to))
		.where((pl.garment_order == garment_order) & (pl.docstatus == 1) & (plc.parenttype == "Packing List"))
	)
	if exclude:
		query = query.where(pl.name != exclude)
	return cint(query.run()[0][0]) + 1


class PackingList(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if frappe.db.get_value("Garment Order", self.garment_order, "docstatus") != 1:
			frappe.throw(_("Garment Order {0} must be submitted.").format(frappe.bold(self.garment_order)))
		self.validate_cartons()
		self.validate_sales_order_items()
		self.validate_available()

	def validate_sales_order_items(self) -> None:
		"""Every packed variant must be on the order's Sales Order (when there is one), so it can be delivered."""
		so = self.sales_order or frappe.db.get_value("Garment Order", self.garment_order, "sales_order")
		if not so or frappe.db.get_value("Sales Order", so, "docstatus") not in (0, 1):
			return
		on_order = set(
			frappe.get_all(
				"Sales Order Item", filters={"parent": so, "parenttype": "Sales Order"}, pluck="item_code"
			)
		)
		missing = sorted(
			{
				(r.colour, r.size, r.item_code)
				for r in self.cartons
				if r.item_code and r.item_code not in on_order
			}
		)
		if missing:
			frappe.throw(
				_(
					"{0} is packed but not on Sales Order {1}, so it could not be delivered. Pack the order colours "
					"of the Sales Order, or add the variant to the Sales Order first."
				).format(", ".join(f"{c} / {s} ({i})" for c, s, i in missing), frappe.bold(so)),
				title=_("Not on the Sales Order"),
			)

	def validate_cartons(self) -> None:
		if not self.cartons:
			frappe.throw(_("Please add at least one carton row."))
		style = frappe.db.get_value("Garment Order", self.garment_order, "style")
		variants = frappe.get_doc("Style", style).get_variant_map()
		ranges = []
		for row in self.cartons:
			label = _("Carton row {0}").format(row.idx)
			if cint(row.carton_from) <= 0 or cint(row.carton_to) < cint(row.carton_from):
				frappe.throw(_("{0}: Carton To must be on or after Carton From, both from 1.").format(label))
			if cint(row.pcs_per_carton) <= 0:
				frappe.throw(_("{0}: Pcs / Carton must be greater than zero.").format(label))
			row.no_of_cartons = cint(row.carton_to) - cint(row.carton_from) + 1
			row.total_pcs = row.no_of_cartons * cint(row.pcs_per_carton)
			row.item_code = variants.get(key_of(row.colour, row.size))
			if not row.item_code:
				frappe.throw(
					_("{0}: {1} / {2} is not a colour and size of Style {3}.").format(
						label, row.colour, row.size, style
					)
				)
			ranges.append((cint(row.carton_from), cint(row.carton_to), _("row {0}").format(row.idx)))

		pl = frappe.qb.DocType("Packing List")
		plc = frappe.qb.DocType("Packing List Carton")
		others = (
			frappe.qb.from_(plc)
			.inner_join(pl)
			.on(pl.name == plc.parent)
			.select(plc.carton_from, plc.carton_to, pl.name)
			.where(
				(pl.garment_order == self.garment_order)
				& (pl.docstatus == 1)
				& (pl.name != self.name)
				& (plc.parenttype == "Packing List")
			)
			.run()
		)
		ranges += [(cint(a), cint(b), name) for a, b, name in others]
		ranges.sort()
		for (a1, b1, where1), (a2, b2, where2) in pairwise(ranges):
			if a2 <= b1:
				frappe.throw(
					_(
						"Carton numbers {0}-{1} ({2}) overlap with {3}-{4} ({5}) for Garment Order {6}."
					).format(a1, b1, where1, a2, b2, where2, self.garment_order),
					title=_("Overlapping Cartons"),
				)
		self.total_cartons = sum(cint(r.no_of_cartons) for r in self.cartons)
		self.total_pcs = sum(cint(r.total_pcs) for r in self.cartons)

	def packed_by_key(self) -> dict[Key, int]:
		packed: dict[Key, int] = defaultdict(int)
		for row in self.cartons:
			packed[key_of(row.colour, row.size)] += cint(row.total_pcs)
		return packed

	def validate_available(self) -> None:
		available: dict[Key, int] = defaultdict(int)
		for b in finished_bundles(self.garment_order):
			available[key_of(b.colour, b.size)] += cint(b.qty) - cint(b.packed_qty)
		for key, qty in self.packed_by_key().items():
			if qty > available.get(key, 0):
				colour, size = next(
					(r.colour, r.size) for r in self.cartons if key_of(r.colour, r.size) == key
				)
				frappe.throw(
					_(
						"{0} / {1}: {2} pieces are packed, but only {3} finished pieces received from {4} are not yet packed."
					).format(colour, size, qty, available.get(key, 0), flow.packing_source_process()),
					title=_("Not Enough Finished Pieces"),
				)

	def on_submit(self) -> None:
		from velocity_ctp.production import packing_cost

		fg_store = stock.get_finished_goods_store(self.company)
		need = self.packed_by_key()
		left_before = packing_cost.pieces_left_to_pack(self.garment_order)
		transfers = []
		self.set("packed_bundles", [])
		for b in finished_bundles(self.garment_order):
			key = key_of(b.colour, b.size)
			take = min(need.get(key, 0), cint(b.qty) - cint(b.packed_qty))
			if take <= 0:
				continue
			need[key] -= take
			bundle = frappe.get_doc("Bundle", b.name)
			self.append(
				"packed_bundles",
				{
					"bundle": b.name,
					"colour": b.colour,
					"size": b.size,
					"qty": take,
					"item_code": b.item_code,
					"before_packed_qty": cint(bundle.packed_qty),
					"before_status": bundle.status,
				},
			)
			transfers.append(
				{
					"item_code": b.item_code,
					"qty": take,
					"s_warehouse": b.current_warehouse,
					"t_warehouse": fg_store,
				}
			)
			bundle.packed_qty = cint(bundle.packed_qty) + take
			if bundle.packed_qty >= cint(bundle.qty):
				bundle.status = "Completed"
			flow.add_movement(bundle, bundle.current_process, flow.PACKING, self.doctype, self.name, take)
			flow.save_bundle(bundle)
		if any(need.values()):
			frappe.throw(
				_("Not enough finished bundles to pack the entered quantities. Please refresh and try again.")
			)
		for row in self.packed_bundles:
			row.db_insert()
		remarks = _("Packing List {0}").format(self.name)
		accessories = packing_cost.consumption(
			self.garment_order, sum(cint(t["qty"]) for t in transfers), left_before, exclude=self.name
		)
		if not accessories:
			self.db_set(
				"stock_entry", stock.make_transfer(self.company, self.packing_date, remarks, transfers)
			)
			return
		entry, values = packing_cost.make_packing_repack(
			self.company,
			self.packing_date,
			_("{0}: pieces and accessories consumed").format(remarks),
			transfers,
			accessories,
			fg_store,
		)
		self.db_set("stock_entry", entry)
		self.set("accessories", [])
		for index, a in enumerate(accessories):
			rate, amount = values.get(index, (0, 0))
			row = self.append("accessories", {**a, "rate": rate, "amount": amount})
			row.db_insert()
		self.db_set("accessory_amount", flt(sum(flt(r.amount) for r in self.accessories), 2))

	def before_cancel(self) -> None:
		# Shipping (a later phase) will add its own checks here.
		pass

	def on_cancel(self) -> None:
		from velocity_ctp.cutting.stock import cancel_stock_entry

		cancel_stock_entry(self.stock_entry)
		for row in self.packed_bundles:
			bundle = frappe.get_doc("Bundle", row.bundle)
			bundle.packed_qty = cint(row.before_packed_qty)
			bundle.status = row.before_status
			bundle.set(
				"history",
				[
					h
					for h in bundle.history
					if not (h.document_type == self.doctype and h.document_name == self.name)
				],
			)
			flow.save_bundle(bundle)
