"""Cost absorption into stock value with standard ERPNext Stock Entries.

ERPNext v16 spreads a Stock Entry's Additional Costs over the incoming (finished) rows in proportion to
their basic amount. To add exactly qty x rate to each variant, the absorption is a Repack in the
process WIP: each variant is consumed at its value V and produced again with a manually set basic
amount of (V + a) x S / (S + A), where a = qty x rate of that variant, S = total value consumed and
A = total absorbed. ERPNext's own spread of A then gives every variant exactly V + a.

GL (per Repack): Dr process WIP A (net), Cr the charge account(s) A: "Contractor Charges Accrued"
for contractor work, "Production Overheads Absorbed" for in-house conversion. The Stock Adjustment
lines of the consumed and produced rows offset each other, as on every Repack.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

# Custom Stock Entry Type (purpose Repack) of the absorption entries: value only, no physical movement,
# so stock movement reports can leave these entries out.
ABSORPTION_ENTRY_TYPE = "Velocity Absorption"
CONTRACTOR_ACCRUAL = "Contractor Charges Accrued"
OVERHEADS_ABSORBED = "Production Overheads Absorbed"


def charge_account(company: str, name: str) -> str:
	account = frappe.db.get_value(
		"Account", {"company": company, "account_name": name, "is_group": 0}, "name"
	)
	if not account:
		frappe.throw(
			_("Account {0} does not exist for company {1}. Please run the Velocity CTP setup.").format(
				frappe.bold(name), frappe.bold(company)
			)
		)
	return account


def additional_cost_rows(company: str, charges: dict[str, float], remarks: str) -> list[dict]:
	"""Additional Costs rows ({account name: amount}), in company currency."""
	rows = []
	for name, amount in charges.items():
		amount = flt(amount, 2)
		if amount <= 0:
			continue
		rows.append(
			{
				"expense_account": charge_account(company, name),
				"description": f"{name}: {remarks}",
				"amount": amount,
				"base_amount": amount,
				"exchange_rate": 1,
			}
		)
	return rows


def set_finished_values(entry, finished_rows: list, targets: list[float]) -> None:
	"""Set the manual basic amount of each finished row so that, after ERPNext spreads the Additional
	Costs by basic amount, row i is valued at targets[i] (consumed value share + absorbed amount)."""
	consumed = sum(flt(r.basic_amount) for r in entry.items if r.s_warehouse and not r.t_warehouse)
	absorbed = sum(flt(t.base_amount) for t in entry.get("additional_costs") or [])
	factor = consumed / (consumed + absorbed) if consumed + absorbed else 0
	for row, target in zip(finished_rows, targets, strict=True):
		basic = flt(target) * factor
		row.basic_rate = basic / flt(row.transfer_qty) if flt(row.transfer_qty) else 0
		row.basic_amount = flt(basic, row.precision("basic_amount"))


def make_absorption_repack(
	company: str, posting_date, remarks: str, lines: list[dict], charges: dict[str, float]
) -> tuple[str | None, dict]:
	"""Add value to pieces in their warehouse.

	`lines`: {"item_code", "warehouse", "qty", "amount"} (amount = qty x rate to add); rows of the same
	item and warehouse are merged. `charges`: {account name: amount}; its total equals the lines' total.
	Returns (stock entry name, {(item, warehouse): posted value after absorption}).
	"""
	from velocity_ctp.cutting.stock import _new_entry, _post

	merged: dict[tuple[str, str], dict] = defaultdict(lambda: {"qty": 0.0, "amount": 0.0})
	for line in lines:
		if flt(line["qty"]) <= 0:
			continue
		key = (line["item_code"], line["warehouse"])
		merged[key]["qty"] += flt(line["qty"])
		merged[key]["amount"] += flt(line["amount"])
	if not merged or sum(flt(v) for v in charges.values()) <= 0:
		return None, {}

	entry = _new_entry("Repack", company, posting_date, remarks, entry_type=ABSORPTION_ENTRY_TYPE)
	pairs = []
	for (item, warehouse), v in merged.items():
		entry.append("items", {"item_code": item, "qty": v["qty"], "s_warehouse": warehouse})
		out_index = len(entry.items) - 1
		entry.append(
			"items",
			{
				"item_code": item,
				"qty": v["qty"],
				"t_warehouse": warehouse,
				"is_finished_item": 1,
				"set_basic_rate_manually": 1,
				"basic_rate": 0,
			},
		)
		pairs.append((out_index, len(entry.items) - 1, v["amount"]))
	entry.set("additional_costs", additional_cost_rows(company, charges, remarks))

	def distribute(e):
		set_finished_values(
			e,
			[e.items[i_in] for _o, i_in, _a in pairs],
			[flt(e.items[i_out].basic_amount) + flt(a) for i_out, _i, a in pairs],
		)

	name = _post(entry, distribute=distribute)
	posted = {
		(entry.items[i].item_code, entry.items[i].t_warehouse): flt(entry.items[i].amount)
		for _o, i, _a in pairs
	}
	return name, posted
