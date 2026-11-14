# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Material Plan: fabric and accessory requirements of a Garment Order, availability and shortfall.

Quantities come from the order's cutting quantities (order qty + excess) per colour and size.
Shortfall = required - (free stock - reserved for other plans) - open purchase orders - open
material requests, never below zero. A Material Request (Purchase) is created for the shortfall.
"""

from __future__ import annotations

import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, nowdate

from velocity_ctp.cutting.stock import get_warehouse, is_fabric_group
from velocity_ctp.setup.install import WIP_WAREHOUSES, get_default_company

ACCESSORY_GROUP = "Accessories & Trims"
SIZE_BASES = ("Per Size", "Per Colour & Size")
COLOUR_BASES = ("Per Colour", "Per Colour & Size")
EXCLUDED_STORES = ("Rejection Store",)


def cutting_quantities(garment_order: str) -> dict:
	"""{"total", "by_colour", "by_size", "by_colour_size", "colours", "sizes"} from the order lines."""
	rows = frappe.get_all(
		"Garment Order Item",
		filters={"parent": garment_order, "parenttype": "Garment Order"},
		fields=["colour", "size", "cutting_qty"],
	)
	size_set = frappe.db.get_value("Garment Order", garment_order, "size_set")
	sizes = [s.size for s in frappe.get_cached_doc("Size Set", size_set).sizes] if size_set else []
	data = {
		"total": 0,
		"by_colour": defaultdict(int),
		"by_size": defaultdict(int),
		"by_colour_size": defaultdict(int),
	}
	colours = []
	for r in rows:
		qty = cint(r.cutting_qty)
		data["total"] += qty
		data["by_colour"][r.colour.lower()] += qty
		data["by_size"][r.size.lower()] += qty
		data["by_colour_size"][(r.colour.lower(), r.size.lower())] += qty
		if r.colour not in colours:
			colours.append(r.colour)
	used_sizes = {r.size.lower() for r in rows}
	data["sizes"] = [s for s in sizes if s.lower() in used_sizes]
	data["colours"] = colours
	return data


def is_whole_number(uom: str | None) -> bool:
	return bool(uom and frappe.get_cached_value("UOM", uom, "must_be_whole_number"))


def required(value: float, uom: str | None) -> float:
	"""Round up to whole units for whole-number UOMs, else keep 3 decimals."""
	value = flt(value, 6)
	return float(math.ceil(value - 1e-9)) if is_whole_number(uom) else flt(value, 3)


class MaterialPlan(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		order = frappe.db.get_value(
			"Garment Order", self.garment_order, ["docstatus", "status"], as_dict=True
		)
		if not order or order.docstatus != 1 or order.status == "Cancelled":
			frappe.throw(_("Garment Order {0} must be submitted.").format(frappe.bold(self.garment_order)))
		other = frappe.db.get_value(
			"Material Plan",
			{"garment_order": self.garment_order, "docstatus": ("<", 2), "name": ("!=", self.name)},
			"name",
		)
		if other:
			frappe.throw(
				_("Garment Order {0} already has Material Plan {1}. There is one plan per order.").format(
					frappe.bold(self.garment_order), frappe.bold(other)
				)
			)
		self.calculate()

	def calculate(self) -> None:
		qty = cutting_quantities(self.garment_order)
		self.cutting_qty_total = qty["total"]
		colours = {c.lower(): c for c in qty["colours"]}
		sizes = {s.lower(): s for s in qty["sizes"]}

		for row in self.fabrics or []:
			if not is_fabric_group(frappe.db.get_value("Item", row.fabric_item, "item_group")):
				frappe.throw(
					_("Fabric row {0}: {1} is not in the Fabric item group.").format(row.idx, row.fabric_item)
				)
			if row.colour and row.colour.lower() not in colours:
				frappe.throw(_("Fabric row {0}: colour {1} is not on the order.").format(row.idx, row.colour))
			row.colour = colours.get((row.colour or "").lower()) if row.colour else None
			row.uom = row.uom or frappe.db.get_value("Item", row.fabric_item, "stock_uom")
			row.cutting_qty = qty["by_colour"][row.colour.lower()] if row.colour else qty["total"]
			row.required_qty = required(
				row.cutting_qty * flt(row.consumption_per_pc) * (1 + flt(row.wastage_percent) / 100), row.uom
			)

		for row in self.accessories or []:
			label = _("Accessory row {0}").format(row.idx)
			if row.basis in SIZE_BASES and not row.size:
				frappe.throw(_("{0}: please select the size for basis {1}.").format(label, row.basis))
			if row.basis in COLOUR_BASES and not row.colour:
				frappe.throw(_("{0}: please select the colour for basis {1}.").format(label, row.basis))
			if row.size and row.size.lower() not in sizes:
				frappe.throw(_("{0}: size {1} is not on the order.").format(label, row.size))
			if row.colour and row.colour.lower() not in colours:
				frappe.throw(_("{0}: colour {1} is not on the order.").format(label, row.colour))
			if flt(row.consumption_per_unit) <= 0:
				frappe.throw(_("{0}: usage must be greater than zero.").format(label))
			if row.basis == "Per Carton" and cint(row.packing) <= 0:
				frappe.throw(_("{0}: please enter the pieces per carton.").format(label))
			if row.basis not in SIZE_BASES and row.basis != "Per Carton":
				row.size = None
			if row.basis not in COLOUR_BASES and row.basis != "Per Carton":
				row.colour = None
			row.size = sizes.get((row.size or "").lower()) if row.size else None
			row.colour = colours.get((row.colour or "").lower()) if row.colour else None
			row.uom = row.uom or frappe.db.get_value("Item", row.accessory_item, "stock_uom")
			row.units = self.units_for(row, qty)
			units = row.units / cint(row.packing) if row.basis == "Per Carton" else row.units
			row.required_qty = required(
				units * flt(row.consumption_per_unit) * (1 + flt(row.excess_percent) / 100), row.uom
			)

	@staticmethod
	def units_for(row, qty: dict) -> int:
		colour, size = (row.colour or "").lower(), (row.size or "").lower()
		if colour and size:
			return qty["by_colour_size"][(colour, size)]
		if size:
			return qty["by_size"][size]
		if colour:
			return qty["by_colour"][colour]
		return qty["total"]

	def requirements(self) -> dict[str, dict]:
		"""{item: {"required", "uom", "kind"}} summed over the plan."""
		items: dict[str, dict] = {}
		for row in self.fabrics or []:
			line = items.setdefault(row.fabric_item, {"required": 0.0, "uom": row.uom, "kind": "Fabric"})
			line["required"] += flt(row.required_qty)
		for row in self.accessories or []:
			line = items.setdefault(
				row.accessory_item, {"required": 0.0, "uom": row.uom, "kind": "Accessory"}
			)
			line["required"] += flt(row.required_qty)
		return items


# ----------------------------------------------------------------------------------------------
# Availability
# ----------------------------------------------------------------------------------------------


def free_warehouses(company: str) -> list[str]:
	"""Company warehouses whose stock is free to use: not process WIP, contractor or rejection."""
	excluded = set()
	for name in (*WIP_WAREHOUSES, *EXCLUDED_STORES):
		wh = frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": company}, "name")
		if wh:
			excluded.add(wh)
	contractor_group = frappe.db.get_value(
		"Warehouse", {"warehouse_name": "Contractor WIP", "company": company, "is_group": 1}, ["lft", "rgt"]
	)
	warehouses = frappe.get_all(
		"Warehouse", filters={"company": company, "is_group": 0}, fields=["name", "lft"]
	)
	return [
		w.name
		for w in warehouses
		if w.name not in excluded
		and not (contractor_group and contractor_group[0] < w.lft < contractor_group[1])
	]


def get_issued_accessory_qty(plan, item: str) -> float:
	"""Accessory quantity already issued for the plan's order.

	Accessory issues are built in Phase 6; until then nothing is issued, so the full requirement
	of other open plans stays reserved.
	"""
	return 0.0


def job_maps_of_orders(orders: list[str]) -> dict[str, str]:
	"""{garment_order: job map}, preferring a Job Map that is not closed (one query)."""
	if not orders:
		return {}
	jm = frappe.qb.DocType("Job Map")
	jmo = frappe.qb.DocType("Job Map Order")
	rows = (
		frappe.qb.from_(jmo)
		.inner_join(jm)
		.on(jm.name == jmo.parent)
		.select(jmo.garment_order, jm.name)
		.where((jmo.parenttype == "Job Map") & jmo.garment_order.isin(orders))
		.orderby(jm.job_closed)
		.orderby(jm.modified, order=frappe.qb.desc)
		.run()
	)
	result: dict[str, str] = {}
	for order, job_map in rows:
		result.setdefault(order, job_map)
	return result


def reserved_by_other_plans(plan, items: list[str]) -> dict[str, float]:
	"""Remaining requirement of other submitted plans of open orders, per item.

	Fabric: plans on the same Job Map are taken together and the fabric already issued to that
	Job Map (issued - returned) is deducted once, never below zero; plans without a Job Map keep
	their full requirement. Accessories: requirement - get_issued_accessory_qty(), never below zero.
	"""
	from velocity_ctp.cutting.ledger import job_fabric

	reserved: dict[str, float] = defaultdict(float)
	if not items:
		return reserved
	others = frappe.get_all(
		"Material Plan",
		filters={"docstatus": 1, "name": ("!=", plan.name or ""), "company": plan.company},
		fields=["name", "garment_order"],
	)
	open_orders = set(
		frappe.get_all(
			"Garment Order",
			filters={
				"name": ("in", [o.garment_order for o in others] or [""]),
				"status": ("not in", ("Completed", "Cancelled")),
			},
			pluck="name",
		)
	)
	others = [o for o in others if o.garment_order in open_orders]
	if not others:
		return reserved
	plan_order = {o.name: o.garment_order for o in others}
	job_maps = job_maps_of_orders(list(open_orders))

	# Fabric: requirement per (job map or plan without one, item), less the net issue to that Job Map.
	fabric_need: dict[tuple, float] = defaultdict(float)
	for parent, item, qty in frappe.db.sql(
		"""select parent, fabric_item, sum(required_qty) from `tabMaterial Plan Fabric`
		where parenttype = 'Material Plan' and parent in %(p)s and fabric_item in %(i)s group by parent, fabric_item""",
		{"p": list(plan_order), "i": items},
	):
		job_map = job_maps.get(plan_order[parent])
		fabric_need[(job_map or f"plan:{parent}", item)] += flt(qty)
	issued = job_fabric([k[0] for k in fabric_need if not k[0].startswith("plan:")])
	for (key, item), qty in fabric_need.items():
		net_issued = 0.0
		if not key.startswith("plan:"):
			net_issued = sum(
				v["issued"] - v["returned"]
				for (fabric, _batch), v in issued.get(key, {}).items()
				if fabric == item
			)
		reserved[item] += max(qty - net_issued, 0.0)

	# Accessories: requirement less what was issued for that plan's order.
	for parent, item, qty in frappe.db.sql(
		"""select parent, accessory_item, sum(required_qty) from `tabMaterial Plan Accessory`
		where parenttype = 'Material Plan' and parent in %(p)s and accessory_item in %(i)s group by parent, accessory_item""",
		{"p": list(plan_order), "i": items},
	):
		other = frappe._dict(name=parent, garment_order=plan_order[parent])
		reserved[item] += max(flt(qty) - flt(get_issued_accessory_qty(other, item)), 0.0)
	return reserved


def availability(plan) -> list[dict]:
	needs = plan.requirements()
	items = list(needs) or [""]
	warehouses = free_warehouses(plan.company) or [""]

	stock = dict(
		frappe.db.sql(
			"select item_code, sum(actual_qty) from `tabBin` where item_code in %(i)s and warehouse in %(w)s group by item_code",
			{"i": items, "w": warehouses},
		)
	)
	on_order = dict(
		frappe.db.sql(
			"""select poi.item_code, sum(greatest(poi.qty - ifnull(poi.received_qty, 0), 0) * ifnull(poi.conversion_factor, 1))
			from `tabPurchase Order Item` poi join `tabPurchase Order` po on po.name = poi.parent
			where po.docstatus = 1 and po.status not in ('Closed', 'Completed', 'On Hold') and po.company = %(c)s
			and poi.item_code in %(i)s group by poi.item_code""",
			{"i": items, "c": plan.company},
		)
	)
	requested = dict(
		frappe.db.sql(
			"""select mri.item_code, sum(greatest(mri.stock_qty - ifnull(mri.ordered_qty, 0), 0))
			from `tabMaterial Request Item` mri join `tabMaterial Request` mr on mr.name = mri.parent
			where mr.docstatus < 2 and mr.material_request_type = 'Purchase' and mr.company = %(c)s
			and ifnull(mr.status, '') not in ('Stopped', 'Cancelled', 'Ordered', 'Received')
			and mri.item_code in %(i)s group by mri.item_code""",
			{"i": items, "c": plan.company},
		)
	)
	reserved = reserved_by_other_plans(plan, list(needs))

	result = []
	for item, need in needs.items():
		row = {
			"item_code": item,
			"item_name": frappe.db.get_value("Item", item, "item_name"),
			"kind": need["kind"],
			"uom": need["uom"],
			"required": flt(need["required"], 3),
			"in_stock": flt(stock.get(item), 3),
			"on_order": flt(on_order.get(item), 3),
			"requested": flt(requested.get(item), 3),
			"reserved": flt(reserved.get(item), 3),
		}
		short = row["required"] - (row["in_stock"] - row["reserved"]) - row["on_order"] - row["requested"]
		row["shortfall"] = required(max(short, 0), need["uom"])
		result.append(row)
	return result


@frappe.whitelist()
def check_availability(material_plan: str | None = None, doc: str | dict | None = None) -> list[dict]:
	plan = frappe.get_doc(frappe.parse_json(doc)) if doc else frappe.get_doc("Material Plan", material_plan)
	frappe.has_permission("Material Plan", "read", throw=True)
	if not plan.company:
		plan.company = get_default_company()
	plan.calculate()
	return availability(plan)


def schedule_date(plan) -> str:
	"""Before the Job Map's cutting start date when it is set (and still ahead), else in 7 days."""
	from velocity_ctp.velocity_ctp.doctype.job_map.job_map import get_active_job_maps

	job_map = get_active_job_maps([plan.garment_order]).get(plan.garment_order)
	start = frappe.db.get_value("Job Map", job_map, "cutting_start_date") if job_map else None
	if start and getdate(add_days(start, -1)) >= getdate(nowdate()):
		return add_days(start, -1)
	return add_days(nowdate(), 7)


@frappe.whitelist(methods=["POST"])
def create_material_request(material_plan: str) -> str:
	plan = frappe.get_doc("Material Plan", material_plan)
	plan.check_permission("write")
	if plan.docstatus != 1:
		frappe.throw(_("Please submit the Material Plan before creating a Material Request."))
	lines = [r for r in availability(plan) if flt(r["shortfall"]) > 0]
	if not lines:
		frappe.throw(_("There is no shortfall: stock, open purchase orders and requests cover this plan."))
	date = schedule_date(plan)
	fabric_store = get_warehouse("Fabric Store", plan.company)
	trim_store = get_warehouse("Trim Store", plan.company)
	mr = frappe.get_doc(
		{
			"doctype": "Material Request",
			"material_request_type": "Purchase",
			"company": plan.company,
			"transaction_date": nowdate(),
			"schedule_date": date,
			"material_plan": plan.name,
			"items": [
				{
					"item_code": r["item_code"],
					"qty": r["shortfall"],
					"uom": r["uom"],
					"schedule_date": date,
					"warehouse": fabric_store if r["kind"] == "Fabric" else trim_store,
				}
				for r in lines
			],
		}
	)
	mr.flags.ignore_permissions = True
	try:
		mr.insert()
	except frappe.PermissionError:
		if frappe.message_log:
			frappe.message_log.pop()
		frappe.throw(
			_(
				"The Material Request could not be created because your roles do not include purchasing or stock "
				"access in ERPNext. Please ask your administrator for a standard role such as Purchase User or Stock User."
			),
			frappe.PermissionError,
		)
	plan.db_set("material_request", mr.name)
	plan.add_comment("Info", _("Material Request {0} created for the shortfall.").format(mr.name))
	return mr.name


@frappe.whitelist()
def get_order_options(garment_order: str) -> dict:
	frappe.has_permission("Material Plan", "read", throw=True)
	qty = cutting_quantities(garment_order)
	return {
		"colours": qty["colours"],
		"sizes": qty["sizes"],
		"total": qty["total"],
		"by_size": dict(qty["by_size"]),
		"by_colour": dict(qty["by_colour"]),
		"by_colour_size": {f"{c}|{s}": v for (c, s), v in qty["by_colour_size"].items()},
	}


@frappe.whitelist()
def get_cost_sheet_lines(garment_order: str) -> dict:
	"""Fabric and accessory lines of the order's Cost Sheet that have linked items."""
	frappe.has_permission("Material Plan", "read", throw=True)
	cost_sheet = frappe.db.get_value("Garment Order", garment_order, "cost_sheet")
	if not cost_sheet:
		frappe.throw(_("Garment Order {0} has no Cost Sheet.").format(frappe.bold(garment_order)))
	cs = frappe.get_doc("Cost Sheet", cost_sheet)
	return {
		"cost_sheet": cost_sheet,
		"fabrics": [
			{"placement": r.placement, "fabric_item": r.fabric_item, "consumption_per_pc": r.usage_per_pc}
			for r in cs.fabrics
			if r.fabric_item
		],
		"accessories": [
			{"accessory_item": r.accessory_item, "basis": "Per Piece", "consumption_per_unit": r.usage_per_pc}
			for r in cs.accessories
			if r.accessory_item
		],
		"skipped": len([r for r in cs.fabrics if not r.fabric_item])
		+ len([r for r in cs.accessories if not r.accessory_item]),
	}
