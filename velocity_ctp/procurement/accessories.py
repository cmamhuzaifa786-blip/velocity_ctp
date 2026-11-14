"""Accessory balances from submitted Accessory Allocations and Accessory Issues.

There is no custom stock ledger: stock moves only by Stock Entries made by Accessory Issues. An
Accessory Allocation is a soft reservation (no stock movement) of store stock for one job (Job Map +
Garment Order). Issues for that job use up its allocations oldest first; the issued quantity is
kept on each allocation row so the unissued part is known.

Keys: (job_map, garment_order, item).
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import flt

Key = tuple[str, str, str]
EPS = 1e-9


def net_issued(
	keys: list[Key] | None = None,
	orders: list[str] | None = None,
	process: str | None = None,
	exclude_issue: str | None = None,
) -> dict[Key, float]:
	"""{(job_map, garment_order, item): issued - returned} from submitted Accessory Issues."""
	conditions = ["ai.docstatus = 1"]
	values: dict = {}
	if keys is not None:
		if not keys:
			return {}
		conditions.append("ai.garment_order in %(orders)s and aii.item in %(items)s")
		values.update(orders=list({k[1] for k in keys}), items=list({k[2] for k in keys}))
	if orders is not None:
		if not orders:
			return {}
		conditions.append("ai.garment_order in %(only_orders)s")
		values["only_orders"] = list(orders)
	if process:
		conditions.append("ai.to_process = %(process)s")
		values["process"] = process
	if exclude_issue:
		conditions.append("ai.name != %(exclude)s")
		values["exclude"] = exclude_issue
	rows = frappe.db.sql(
		f"""select ai.job_map, ai.garment_order, aii.item,
			sum(case when ai.issue_type = 'Return' then -aii.qty else aii.qty end)
		from `tabAccessory Issue Item` aii join `tabAccessory Issue` ai on ai.name = aii.parent
		where {" and ".join(conditions)} group by ai.job_map, ai.garment_order, aii.item""",
		values,
	)
	result = {(jm, order, item): flt(qty) for jm, order, item, qty in rows}
	if keys is not None:
		wanted = set(keys)
		result = {k: v for k, v in result.items() if k in wanted}
	return result


def issued_by_order(orders: list[str], items: list[str] | None = None) -> dict[tuple[str, str], float]:
	"""{(garment_order, item): net issued} over all Job Maps and processes."""
	result: dict[tuple[str, str], float] = defaultdict(float)
	for (_jm, order, item), qty in net_issued(orders=orders).items():
		if items is None or item in items:
			result[(order, item)] += qty
	return result


def allocation_rows(keys: list[Key], exclude: str | None = None) -> dict[Key, list[frappe._dict]]:
	"""Submitted allocation rows per key, oldest first."""
	if not keys:
		return {}
	rows = frappe.db.sql(
		"""select aa.name as parent, aa.job_map, aa.garment_order, aa.warehouse, aai.name, aai.item,
			aai.qty, aai.issued_qty, aai.released_qty
		from `tabAccessory Allocation Item` aai join `tabAccessory Allocation` aa on aa.name = aai.parent
		where aa.docstatus = 1 and aa.garment_order in %(orders)s and aai.item in %(items)s
			and aa.name != %(exclude)s
		order by aa.posting_date, aa.creation, aai.idx""",
		{"orders": list({k[1] for k in keys}), "items": list({k[2] for k in keys}), "exclude": exclude or ""},
		as_dict=True,
	)
	wanted = set(keys)
	result: dict[Key, list] = defaultdict(list)
	for row in rows:
		key = (row.job_map, row.garment_order, row.item)
		if key in wanted:
			result[key].append(row)
	return result


def unissued(row) -> float:
	return max(flt(row.qty) - flt(row.released_qty) - flt(row.issued_qty), 0.0)


def unissued_allocations(
	warehouse: str | None = None,
	items: list[str] | None = None,
	exclude_allocation: str | None = None,
) -> dict[Key, float]:
	"""{(job_map, garment_order, item): allocated and not yet issued or released} over submitted allocations."""
	conditions = ["aa.docstatus = 1", "aa.name != %(exclude)s"]
	values: dict = {"exclude": exclude_allocation or ""}
	if warehouse:
		conditions.append("aa.warehouse = %(warehouse)s")
		values["warehouse"] = warehouse
	if items is not None:
		if not items:
			return {}
		conditions.append("aai.item in %(items)s")
		values["items"] = list(items)
	rows = frappe.db.sql(
		f"""select aa.job_map, aa.garment_order, aai.item,
			sum(greatest(aai.qty - aai.released_qty - aai.issued_qty, 0))
		from `tabAccessory Allocation Item` aai join `tabAccessory Allocation` aa on aa.name = aai.parent
		where {" and ".join(conditions)} group by aa.job_map, aa.garment_order, aai.item""",
		values,
	)
	return {(jm, order, item): flt(qty) for jm, order, item, qty in rows if flt(qty) > EPS}


def allocated_by_order(orders: list[str], items: list[str] | None = None) -> dict[tuple[str, str], float]:
	"""{(garment_order, item): unissued allocated}."""
	result: dict[tuple[str, str], float] = defaultdict(float)
	for (_jm, order, item), qty in unissued_allocations(items=items).items():
		if order in orders:
			result[(order, item)] += qty
	return result


def refresh_allocations(keys: list[Key]) -> None:
	"""Spread each job's net issue over its allocations, oldest first, and update the issued quantity
	and status of the allocations. Issues beyond the allocations are not shown on them."""
	keys = list(set(keys))
	if not keys:
		return
	issued = net_issued(keys=keys)
	parents: set[str] = set()
	for key, rows in allocation_rows(keys).items():
		remaining = max(issued.get(key, 0.0), 0.0)
		for row in rows:
			capacity = max(flt(row.qty) - flt(row.released_qty), 0.0)
			share = min(capacity, remaining)
			remaining -= share
			if abs(share - flt(row.issued_qty)) > EPS:
				frappe.db.set_value(
					"Accessory Allocation Item", row.name, "issued_qty", share, update_modified=False
				)
				parents.add(row.parent)
	for parent in parents:
		update_allocation_status(parent)


def allocation_status(rows) -> str:
	total = sum(flt(r.qty) for r in rows)
	issued = sum(flt(r.issued_qty) for r in rows)
	released = sum(flt(r.released_qty) for r in rows)
	if total - issued - released > EPS:
		return "Partly Issued" if issued > EPS else "Allocated"
	return "Released" if released > EPS else "Issued"


def update_allocation_status(name: str) -> None:
	rows = frappe.get_all(
		"Accessory Allocation Item",
		filters={"parent": name, "parenttype": "Accessory Allocation"},
		fields=["qty", "issued_qty", "released_qty"],
	)
	if frappe.db.get_value("Accessory Allocation", name, "docstatus") == 1:
		frappe.db.set_value(
			"Accessory Allocation", name, "status", allocation_status(rows), update_modified=False
		)


def store_qty(items: list[str], warehouse: str) -> dict[str, float]:
	if not items:
		return {}
	return {
		item: flt(qty)
		for item, qty in frappe.db.sql(
			"select item_code, actual_qty from `tabBin` where warehouse = %s and item_code in %s",
			(warehouse, list(set(items))),
		)
	}
