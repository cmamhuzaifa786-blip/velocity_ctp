"""Standard ERPNext Stock Entries for cutting. No custom stock ledger: every movement is a Stock Entry.

- Fabric Issue / Return: "Material Transfer" between Fabric Store and Cutting WIP, batch on every row.
- Cut Receive: "Repack" that consumes fabric (by batch) from Cutting WIP and produces the style
  variants into Cutting WIP. ERPNext v16 only allows one finished item in "Manufacture", and in a
  Repack with several finished items it requires the basic rate to be set manually on each of
  them, so each marker's fabric value is distributed here over that marker's good pieces.
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


def _post(entry, distribute=None) -> str:
	"""Insert and submit on the user's behalf (their own document's submit right was checked).

	ERPNext still checks some permissions inside stock posting (for example on Serial and Batch
	Bundle), which need a standard ERPNext stock role; turn that into a clear message.
	"""
	try:
		entry.insert()
		if distribute:
			distribute(entry)
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


def make_cut_repack(
	doc, groups: list[dict], absorption: list[dict[str, float]] | None = None, charges: dict | None = None
) -> tuple[str, list[dict[str, dict]]]:
	"""Repack: consume fabric batches from Cutting WIP, produce the variants into Cutting WIP.

	`groups` come from Cut Receive.marker_groups(): per marker, its fabric rows and its good
	pieces. Each marker's fabric value (as ERPNext values that batch) is split only across that
	marker's good pieces, in proportion to quantity; the marker's last row takes the rounding.

	`absorption` (optional, per group {item_code: amount}) adds the cutting cost (good pieces x rate)
	to those pieces through the entry's Additional Costs, credited to `charges` ({account name:
	amount}); see velocity_ctp.production.absorption for how the amounts stay exact per variant.

	Returns (stock entry name, valuation): valuation[i] is {item_code: {"rate", "amount", "qty",
	"fabric", "absorbed"}} for groups[i], read from the posted rows, so the cost can be stored on the
	Cut Receive.
	"""
	from velocity_ctp.production.absorption import additional_cost_rows, set_finished_values

	absorption = absorption or [{} for _g in groups]
	wip = get_cutting_wip(doc.company)
	entry = _new_entry(
		"Repack",
		doc.company,
		doc.posting_date,
		_("Cut Receive {0} for Job Map {1}").format(doc.name, doc.job_map),
	)
	positions: list[tuple[list[int], list[int]]] = []  # per marker: (fabric row indexes, piece row indexes)
	for group in groups:
		fabric_rows, piece_rows = [], []
		for row in group["fabric"]:
			entry.append(
				"items",
				{
					"item_code": row["item_code"],
					"qty": row["qty"],
					"s_warehouse": wip,
					"use_serial_batch_fields": 1,
					"batch_no": row["batch_no"],
				},
			)
			fabric_rows.append(len(entry.items) - 1)
		for row in group["pieces"]:
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
			piece_rows.append(len(entry.items) - 1)
		positions.append((fabric_rows, piece_rows))
	if charges:
		entry.set("additional_costs", additional_cost_rows(doc.company, charges, doc.name))

	fabric_values: dict[int, float] = {}

	def distribute(e):
		# Fabric value per piece row (per marker), then the cutting cost on top, exact per row.
		distribute_fabric_value(e, positions)
		finished, targets = [], []
		for (_fabric, piece_rows), extra in zip(positions, absorption, strict=True):
			for i in piece_rows:
				fabric_values[i] = flt(e.items[i].basic_amount)
				finished.append(e.items[i])
				targets.append(fabric_values[i] + flt(extra.get(e.items[i].item_code)))
		if e.get("additional_costs"):
			set_finished_values(e, finished, targets)

	# The first save lets ERPNext value the consumed batches; then each marker's value is distributed.
	name = _post(entry, distribute=distribute)
	valuation = [
		{
			entry.items[i].item_code: {
				"rate": flt(entry.items[i].valuation_rate),
				"amount": flt(entry.items[i].amount),
				"qty": flt(entry.items[i].transfer_qty),
				"fabric": flt(fabric_values.get(i)),
				"absorbed": flt(extra.get(entry.items[i].item_code)),
			}
			for i in piece_rows
		}
		for (_fabric_rows, piece_rows), extra in zip(positions, absorption, strict=True)
	]
	return name, valuation


def distribute_fabric_value(entry, positions: list[tuple[list[int], list[int]]]) -> None:
	for fabric_rows, piece_rows in positions:
		finished = [entry.items[i] for i in piece_rows]
		consumed = sum(flt(entry.items[i].basic_amount) for i in fabric_rows)
		total_qty = sum(flt(r.transfer_qty) for r in finished)
		if not finished or not total_qty:
			continue
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
