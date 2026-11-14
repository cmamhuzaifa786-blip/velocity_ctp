"""Stock Entries for production movements (standard ERPNext documents only).

- Issue in-house:   Material Transfer  bundle's current warehouse -> process WIP
- Issue outsourced: Material Transfer  bundle's current warehouse -> contractor warehouse
- Receive fresh:    Material Transfer  contractor warehouse -> process WIP (in-house: already there)
- Receive rejected: Material Transfer  where the pieces are -> Rejection Store
- Colour change:    Repack inside the process WIP, old variant -> new variant at the same value
- Packing:          Material Transfer  Finishing WIP -> Finished Goods Store

No value is added in this phase: transfers move stock at its valuation.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from velocity_ctp.cutting.stock import _new_entry, _post, distribute_fabric_value, get_warehouse

CONTRACTOR_GROUP = "Contractor WIP"
REJECTION_STORE = "Rejection Store"
FINISHED_GOODS_STORE = "Finished Goods Store"
WIP_ACCOUNT_NAME = "Work In Progress"


def wip_account(company: str) -> str | None:
	return frappe.db.get_value(
		"Account", {"company": company, "account_name": WIP_ACCOUNT_NAME, "is_group": 0}, "name"
	)


def get_contractor_warehouse(supplier: str, company: str) -> str:
	""" "<Supplier name> - <abbr>" under "Contractor WIP - <abbr>", on the Work In Progress account.

	Created on first use (on the user's behalf, as part of the movement they are submitting).
	"""
	supplier_name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier
	existing = frappe.db.get_value("Warehouse", {"warehouse_name": supplier_name, "company": company}, "name")
	if existing:
		return existing

	account = wip_account(company)
	group = frappe.db.get_value(
		"Warehouse", {"warehouse_name": CONTRACTOR_GROUP, "company": company, "is_group": 1}, "name"
	)
	if not group:
		root = frappe.db.get_value(
			"Warehouse", {"company": company, "is_group": 1}, "name", order_by="lft asc"
		)
		doc = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": CONTRACTOR_GROUP,
				"company": company,
				"is_group": 1,
				"parent_warehouse": root,
				"account": account,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		group = doc.name

	doc = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": supplier_name,
			"company": company,
			"is_group": 0,
			"parent_warehouse": group,
			"account": account,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def get_rejection_store(company: str) -> str:
	return get_warehouse(REJECTION_STORE, company)


def get_finished_goods_store(company: str) -> str:
	return get_warehouse(FINISHED_GOODS_STORE, company)


def make_transfer(company: str, posting_date, remarks: str, rows: list[dict]) -> str | None:
	"""Material Transfer; rows with the same item, source and target are merged."""
	merged: dict[tuple[str, str, str], float] = defaultdict(float)
	for row in rows:
		if flt(row["qty"]) > 0 and row["s_warehouse"] != row["t_warehouse"]:
			merged[(row["item_code"], row["s_warehouse"], row["t_warehouse"])] += flt(row["qty"])
	if not merged:
		return None
	entry = _new_entry("Material Transfer", company, posting_date, remarks)
	for (item_code, source, target), qty in merged.items():
		entry.append(
			"items", {"item_code": item_code, "qty": qty, "s_warehouse": source, "t_warehouse": target}
		)
	return _post(entry)


def make_colour_repack(company: str, posting_date, remarks: str, changes: list[dict]) -> str | None:
	"""Repack old colour variants into new colour variants inside the same warehouse at the same value.

	`changes`: {"from_item", "to_item", "qty", "warehouse"}; each pair is valued on its own.
	"""
	changes = [c for c in changes if flt(c["qty"]) > 0]
	if not changes:
		return None
	entry = _new_entry("Repack", company, posting_date, remarks)
	positions = []
	for change in changes:
		entry.append(
			"items",
			{"item_code": change["from_item"], "qty": change["qty"], "s_warehouse": change["warehouse"]},
		)
		out_row = len(entry.items) - 1
		entry.append(
			"items",
			{
				"item_code": change["to_item"],
				"qty": change["qty"],
				"t_warehouse": change["warehouse"],
				"is_finished_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": 0,
			},
		)
		positions.append(([out_row], [len(entry.items) - 1]))
	return _post(entry, distribute=lambda e: distribute_fabric_value(e, positions))
