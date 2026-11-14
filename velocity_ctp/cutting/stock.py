"""Standard ERPNext Stock Entries for cutting. No custom stock ledger: every movement is a Stock Entry.

- Fabric Issue / Return: "Material Transfer" between Fabric Store and Cutting WIP, batch on every row.
- Cut Receive: "Repack" that consumes fabric (by batch) from Cutting WIP and produces the style
  variants into Cutting WIP. ERPNext v16 only allows one finished item in "Manufacture", and in a
  Repack with several finished items it requires the basic rate to be set manually on each of
  them, so the fabric value is distributed here in proportion to the good quantity.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowtime

FABRIC_GROUP = "Fabric"
FABRIC_STORE = "Fabric Store"
CUTTING_WIP = "Cutting WIP"
CUTTING_PROCESS = "Cutting"


def get_warehouse(warehouse_name: str, company: str) -> str:
	name = frappe.db.get_value("Warehouse", {"warehouse_name": warehouse_name, "company": company}, "name")
	if not name:
		frappe.throw(
			_("Warehouse {0} does not exist for company {1}. Please run the Velocity CTP setup.").format(
				frappe.bold(warehouse_name), frappe.bold(company)
			)
		)
	return name


def get_fabric_store(company: str) -> str:
	return get_warehouse(FABRIC_STORE, company)


def get_cutting_wip(company: str) -> str:
	"""The Cutting process's WIP warehouse when it belongs to the company, else "Cutting WIP"."""
	wip = frappe.db.get_value("Process", CUTTING_PROCESS, "wip_warehouse")
	if wip and frappe.db.get_value("Warehouse", wip, "company") == company:
		return wip
	return get_warehouse(CUTTING_WIP, company)


def batch_qty(batch_no: str, warehouse: str) -> float:
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	return flt(get_batch_qty(batch_no=batch_no, warehouse=warehouse))


def is_fabric_item(item_code: str) -> bool:
	"""True when the item is in the Fabric item group or one of its sub-groups."""
	return is_fabric_group(frappe.db.get_value("Item", item_code, "item_group"))


def is_fabric_group(group: str | None) -> bool:
	if not group:
		return False
	if group == FABRIC_GROUP:
		return True
	bounds = frappe.db.get_value("Item Group", FABRIC_GROUP, ["lft", "rgt"])
	if not bounds:
		return False
	lft = frappe.db.get_value("Item Group", group, "lft")
	return bool(lft and bounds[0] < lft < bounds[1])


def validate_fabric_batch(row_label: str, item_code: str, batch_no: str) -> None:
	if not is_fabric_item(item_code):
		frappe.throw(
			_("{0}: Item {1} is not in the Fabric item group.").format(row_label, frappe.bold(item_code))
		)
	if frappe.db.get_value("Batch", batch_no, "item") != item_code:
		frappe.throw(
			_("{0}: Batch {1} does not belong to item {2}.").format(
				row_label, frappe.bold(batch_no), frappe.bold(item_code)
			)
		)


def _new_entry(purpose: str, company: str, posting_date, remarks: str):
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = purpose
	entry.purpose = purpose
	entry.company = company
	entry.set_posting_time = 1
	entry.posting_date = posting_date
	entry.posting_time = nowtime()
	entry.remarks = remarks
	entry.flags.ignore_permissions = True
	return entry


def _post(entry, distribute: bool = False) -> str:
	"""Insert and submit on the user's behalf (their own document's submit right was checked).

	ERPNext still checks some permissions inside stock posting (for example on Serial and Batch
	Bundle), which need a standard ERPNext stock role; turn that into a clear message.
	"""
	try:
		entry.insert()
		if distribute:
			distribute_fabric_value(entry)
			entry.save()
		entry.submit()
	except frappe.PermissionError:
		if frappe.message_log:
			frappe.message_log.pop()
		frappe.throw(
			_(
				"The stock entry could not be posted because your roles do not include stock access in ERPNext. "
				"Please ask your administrator to add a standard stock role such as Stock User."
			),
			frappe.PermissionError,
			title=_("Stock Access Needed"),
		)
	return entry.name


def make_fabric_transfer(doc) -> str:
	"""Material Transfer for a Fabric Issue (Fabric Store -> Cutting WIP) or Return (reverse)."""
	store, wip = get_fabric_store(doc.company), get_cutting_wip(doc.company)
	source, target = (store, wip) if doc.issue_type == "Issue" else (wip, store)
	entry = _new_entry(
		"Material Transfer",
		doc.company,
		doc.posting_date,
		_("Fabric {0} {1} for Job Map {2}").format(_(doc.issue_type), doc.name, doc.job_map),
	)
	for row in doc.items:
		entry.append(
			"items",
			{
				"item_code": row.fabric_item,
				"qty": row.qty,
				"s_warehouse": source,
				"t_warehouse": target,
				"use_serial_batch_fields": 1,
				"batch_no": row.batch_no,
			},
		)
	return _post(entry)


def make_cut_repack(doc, good_rows: list[dict]) -> str:
	"""Repack: consume fabric batches from Cutting WIP, produce the variants into Cutting WIP.

	`good_rows` are {"item_code", "qty"} for good pieces. The consumed fabric value (as ERPNext
	values the batches) is split across the pieces in proportion to quantity; the last row takes
	any rounding difference so that pieces value == fabric value.
	"""
	wip = get_cutting_wip(doc.company)
	entry = _new_entry(
		"Repack",
		doc.company,
		doc.posting_date,
		_("Cut Receive {0} for Job Map {1}").format(doc.name, doc.job_map),
	)
	for row in doc.fabric:
		if flt(row.used_qty) <= 0:
			continue
		entry.append(
			"items",
			{
				"item_code": row.fabric_item,
				"qty": row.used_qty,
				"s_warehouse": wip,
				"use_serial_batch_fields": 1,
				"batch_no": row.batch_no,
			},
		)
	for row in good_rows:
		entry.append(
			"items",
			{
				"item_code": row["item_code"],
				"qty": row["qty"],
				"t_warehouse": wip,
				"is_finished_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": 0,
			},
		)

	# The first save lets ERPNext value the consumed batches; then that value is distributed.
	return _post(entry, distribute=True)


def distribute_fabric_value(entry) -> None:
	consumed = sum(flt(r.basic_amount) for r in entry.items if r.s_warehouse and not r.t_warehouse)
	finished = [r for r in entry.items if r.is_finished_item]
	total_qty = sum(flt(r.transfer_qty) for r in finished)
	if not finished or not total_qty:
		return
	rate = consumed / total_qty
	allocated = 0.0
	for row in finished[:-1]:
		row.basic_rate = rate
		row.basic_amount = flt(flt(row.transfer_qty) * rate, row.precision("basic_amount"))
		allocated += row.basic_amount
	last = finished[-1]
	last.basic_rate = (consumed - allocated) / flt(last.transfer_qty)
	last.basic_amount = flt(consumed - allocated, last.precision("basic_amount"))


def cancel_stock_entry(name: str | None) -> None:
	if not name or not frappe.db.exists("Stock Entry", name):
		return
	entry = frappe.get_doc("Stock Entry", name)
	if entry.docstatus == 1:
		entry.flags.ignore_permissions = True
		entry.cancel()
