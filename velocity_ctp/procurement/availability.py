"""Material availability and shortfall for Material Plans, computed for many plans at once.

Used by the Material Plan form, the Order Tracker "Material" chip and the Job Accessory Balance report,
so they always agree. Per plan and item:

- issued     : already issued to the order (fabric: net issue to the order's Job Map, shared between
               the plans on that Job Map in name order; accessories: net Accessory Issues of the order)
- still needed = max(required - issued, 0)
- allocated  : this order's accessory allocations not yet issued (soft reservation of store stock)
- reserved   : what other open orders hold on the free stock = their unissued allocations + the rest of
               their remaining requirement that their allocations do not cover
- available  = allocated + max(in stock - all unissued allocations - other orders' uncovered requirement, 0)
- shortfall  = max(still needed - available - open purchase orders - open requests, 0)

Open purchase orders and requests are company-wide per item (as in Phase 5). Rejected requests do not count.
"""

from __future__ import annotations

import math
from collections import defaultdict

import frappe
from frappe.utils import flt

from velocity_ctp.procurement import accessories

CLOSED_ORDER_STATUSES = ("Completed", "Cancelled")
EPS = 1e-9


def is_whole_number(uom: str | None) -> bool:
	return bool(uom and frappe.get_cached_value("UOM", uom, "must_be_whole_number"))


def round_qty(value: float, uom: str | None) -> float:
	value = flt(value, 6)
	return float(math.ceil(value - EPS)) if is_whole_number(uom) else flt(value, 3)


def plan_requirements(plans: list[str]) -> dict[str, dict[str, dict]]:
	"""{plan: {item: {"required", "uom", "kind"}}} from the plans' fabric and accessory rows (two queries)."""
	result: dict[str, dict[str, dict]] = defaultdict(dict)
	if not plans:
		return result
	for table, field, kind in (
		("Material Plan Fabric", "fabric_item", "Fabric"),
		("Material Plan Accessory", "accessory_item", "Accessory"),
	):
		for parent, item, uom, qty in frappe.db.sql(
			f"""select parent, {field}, max(uom), sum(required_qty) from `tab{table}`
			where parenttype = 'Material Plan' and parent in %(p)s group by parent, {field}""",
			{"p": plans},
		):
			line = result[parent].setdefault(item, {"required": 0.0, "uom": uom, "kind": kind})
			line["required"] += flt(qty)
	return result


def open_plans(company: str) -> dict[str, str]:
	"""{plan: garment_order} for submitted plans of orders that are not completed or cancelled."""
	plans = frappe.get_all(
		"Material Plan", filters={"docstatus": 1, "company": company}, fields=["name", "garment_order"]
	)
	if not plans:
		return {}
	closed = set(
		frappe.get_all(
			"Garment Order",
			filters={
				"name": ("in", [p.garment_order for p in plans]),
				"status": ("in", CLOSED_ORDER_STATUSES),
			},
			pluck="name",
		)
	)
	return {p.name: p.garment_order for p in plans if p.garment_order not in closed}


def fabric_issued_shares(
	needs: dict[str, dict[str, dict]], plan_order: dict[str, str]
) -> dict[tuple[str, str], float]:
	"""{(plan, fabric item): issued} - each Job Map's net fabric issue shared between its plans in name order."""
	from velocity_ctp.cutting.ledger import job_fabric
	from velocity_ctp.velocity_ctp.doctype.material_plan.material_plan import job_maps_of_orders

	job_maps = job_maps_of_orders(list(set(plan_order.values())))
	issued = job_fabric(list(set(job_maps.values()))) if job_maps else {}
	net: dict[tuple[str, str], float] = defaultdict(float)
	for job_map, batches in issued.items():
		for (fabric, _batch), v in batches.items():
			net[(job_map, fabric)] += v["issued"] - v["returned"]

	shares: dict[tuple[str, str], float] = {}
	for plan in sorted(needs):
		job_map = job_maps.get(plan_order.get(plan))
		if not job_map:
			continue
		for item, line in needs[plan].items():
			if line["kind"] != "Fabric":
				continue
			left = max(net.get((job_map, item), 0.0), 0.0)
			share = min(left, line["required"])
			shares[(plan, item)] = share
			net[(job_map, item)] = left - share
	return shares


def company_quantities(company: str, items: list[str]) -> tuple[dict, dict, dict]:
	"""(free stock, open purchase orders, open requests) per item."""
	from velocity_ctp.velocity_ctp.doctype.material_plan.material_plan import free_warehouses

	items = items or [""]
	warehouses = free_warehouses(company) or [""]
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
			{"i": items, "c": company},
		)
	)
	rejected = (
		"and ifnull(mr.workflow_state, '') != 'Rejected'"
		if frappe.get_meta("Material Request").has_field("workflow_state")
		else ""
	)
	requested = dict(
		frappe.db.sql(
			f"""select mri.item_code, sum(greatest(mri.stock_qty - ifnull(mri.ordered_qty, 0), 0))
			from `tabMaterial Request Item` mri join `tabMaterial Request` mr on mr.name = mri.parent
			where mr.docstatus < 2 and mr.material_request_type = 'Purchase' and mr.company = %(c)s
			and ifnull(mr.status, '') not in ('Stopped', 'Cancelled', 'Ordered', 'Received') {rejected}
			and mri.item_code in %(i)s group by mri.item_code""",
			{"i": items, "c": company},
		)
	)
	return stock, on_order, requested


def compute(company: str, targets: list[dict]) -> dict[str, list[dict]]:
	"""Availability rows for each target plan.

	`targets`: [{"name", "garment_order", "needs": {item: {"required", "uom", "kind"}} or None}]. With
	needs None the submitted requirement is read; a draft passes its calculated needs.
	"""
	if not targets:
		return {}
	plan_order = open_plans(company)
	for t in targets:
		plan_order[t["name"]] = t["garment_order"]
	needs = plan_requirements(
		[p for p in plan_order if not any(t["name"] == p and t.get("needs") is not None for t in targets)]
	)
	for t in targets:
		if t.get("needs") is not None:
			needs[t["name"]] = t["needs"]

	items = sorted({item for t in targets for item in needs.get(t["name"], {})})
	if not items:
		return {t["name"]: [] for t in targets}
	item_set = set(items)
	for plan in list(needs):
		needs[plan] = {i: v for i, v in needs[plan].items() if i in item_set}

	orders = list(set(plan_order.values()))
	fabric_issued = fabric_issued_shares(needs, plan_order)
	accessory_issued = accessories.issued_by_order(orders, items)
	allocated = defaultdict(float)
	for (_jm, order, item), qty in accessories.unissued_allocations(items=items).items():
		allocated[(order, item)] += qty

	issued: dict[tuple[str, str], float] = {}
	uncovered: dict[
		tuple[str, str], float
	] = {}  # (plan, item): remaining requirement not covered by allocation
	for plan, lines in needs.items():
		order = plan_order.get(plan)
		for item, line in lines.items():
			done = (
				fabric_issued.get((plan, item), 0.0)
				if line["kind"] == "Fabric"
				else max(accessory_issued.get((order, item), 0.0), 0.0)
			)
			issued[(plan, item)] = done
			remaining = max(line["required"] - done, 0.0)
			uncovered[(plan, item)] = max(remaining - allocated.get((order, item), 0.0), 0.0)

	total_alloc: dict[str, float] = defaultdict(float)
	for (_order, item), qty in allocated.items():
		total_alloc[item] += qty
	total_uncovered: dict[str, float] = defaultdict(float)
	for (_plan, item), qty in uncovered.items():
		total_uncovered[item] += qty

	stock, on_order, requested = company_quantities(company, items)
	names = dict(
		frappe.get_all("Item", filters={"name": ("in", items)}, fields=["name", "item_name"], as_list=True)
	)

	result: dict[str, list[dict]] = {}
	for t in targets:
		plan, order = t["name"], t["garment_order"]
		rows = []
		for item, line in needs.get(plan, {}).items():
			own_alloc = allocated.get((order, item), 0.0)
			own_uncovered = uncovered.get((plan, item), 0.0)
			reserved = (total_alloc[item] - own_alloc) + (total_uncovered[item] - own_uncovered)
			in_stock = flt(stock.get(item))
			available = own_alloc + max(
				in_stock - total_alloc[item] - (total_uncovered[item] - own_uncovered), 0.0
			)
			still_needed = max(line["required"] - issued[(plan, item)], 0.0)
			short = still_needed - available - flt(on_order.get(item)) - flt(requested.get(item))
			rows.append(
				{
					"item_code": item,
					"item_name": names.get(item),
					"kind": line["kind"],
					"uom": line["uom"],
					"required": flt(line["required"], 3),
					"issued": flt(issued[(plan, item)], 3),
					"allocated": flt(own_alloc, 3),
					"in_stock": flt(in_stock, 3),
					"reserved": flt(reserved, 3),
					"on_order": flt(on_order.get(item), 3),
					"requested": flt(requested.get(item), 3),
					"shortfall": round_qty(max(short, 0.0), line["uom"]),
				}
			)
		result[plan] = rows
	return result


def coverage(rows: list[dict]) -> dict:
	"""Coverage % per kind (required less shortfall, of required) and the Material chip state."""
	summary = {}
	for kind in ("Fabric", "Accessory"):
		lines = [r for r in rows if r["kind"] == kind]
		required = sum(r["required"] for r in lines)
		covered = sum(max(r["required"] - r["shortfall"], 0.0) for r in lines)
		summary[kind] = round(covered / required * 100) if required else None
	if rows and all(r["issued"] >= r["required"] - EPS for r in rows):
		state = "Issued"
	elif any(r["shortfall"] > EPS for r in rows):
		state = "Planned"
	else:
		state = "Covered"
	return {"state": state, "fabric": summary["Fabric"], "accessory": summary["Accessory"]}
