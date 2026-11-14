# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Department Issue: non-product consumables (chemicals, needles, stationery) charged to a department.

Issue: Stock Entry "Material Issue" from the store; the value goes to the Department Consumption
Account (Velocity Settings) on the department's cost center (Velocity Settings mapping, else the
company's default). Return: Stock Entry "Material Receipt" back into the store at the rate of the
original issue, credited to the same account and cost center.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from velocity_ctp.cutting import stock
from velocity_ctp.procurement.common import NON_PRODUCT_GROUP, validate_items_in_group
from velocity_ctp.setup.install import get_default_company

CHEMICAL_STORE = "Chemical Store"
EPS = 1e-9


def department_cost_center(department: str, company: str) -> str | None:
	from velocity_ctp.cutting.settings import get_settings

	for row in get_settings().get("department_cost_centers") or []:
		if (
			row.department == department
			and frappe.db.get_value("Cost Center", row.cost_center, "company") == company
		):
			return row.cost_center
	return frappe.get_cached_value("Company", company, "cost_center")


def consumption_account(company: str) -> str:
	from velocity_ctp.cutting.settings import get_settings

	account = get_settings().get("department_consumption_account")
	if not account:
		frappe.throw(
			_("Please set the Department Consumption Account in Velocity Settings."),
			title=_("Account Missing"),
		)
	if frappe.db.get_value("Account", account, "company") != company:
		frappe.throw(
			_(
				"The Department Consumption Account {0} in Velocity Settings does not belong to company {1}."
			).format(frappe.bold(account), frappe.bold(company))
		)
	return account


class DepartmentIssue(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if self.issue_type == "Return":
			self.load_from_issue()
		elif not self.warehouse:
			self.warehouse = stock.get_warehouse(CHEMICAL_STORE, self.company)
		if not self.items:
			frappe.throw(_("Please add at least one item."))
		validate_items_in_group(self.items, NON_PRODUCT_GROUP, "Department Issue")
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be greater than zero.").format(row.idx))
			if not frappe.get_cached_value("Item", row.item, "is_stock_item"):
				frappe.throw(_("Row {0}: {1} is not a stock item.").format(row.idx, frappe.bold(row.item)))
		self.expense_account = consumption_account(self.company)
		self.cost_center = department_cost_center(self.department, self.company)
		if self.issue_type == "Issue":
			self.validate_issue()
		else:
			self.validate_return()
		self.total_amount = flt(sum(flt(r.amount) for r in self.items), self.precision("total_amount"))

	def requested(self) -> dict[str, float]:
		totals: dict[str, float] = defaultdict(float)
		for row in self.items:
			totals[row.item] += flt(row.qty)
		return totals

	def validate_issue(self) -> None:
		items = list(self.requested())
		bins = {
			r.item_code: r
			for r in frappe.get_all(
				"Bin",
				filters={"warehouse": self.warehouse, "item_code": ("in", items)},
				fields=["item_code", "actual_qty", "valuation_rate"],
			)
		}
		for row in self.items:
			b = bins.get(row.item) or frappe._dict(actual_qty=0, valuation_rate=0)
			row.available_qty = flt(b.actual_qty)
			if self.docstatus == 0:  # estimate; the posted rate is stored on submit
				row.rate = flt(b.valuation_rate)
				row.amount = flt(row.rate * flt(row.qty), row.precision("amount"))
		for item, qty in self.requested().items():
			available = flt((bins.get(item) or {}).get("actual_qty"))
			if qty > available + EPS:
				frappe.throw(
					_("{0}: only {1} is in {2}; {3} is entered.").format(
						frappe.bold(item), available, frappe.bold(self.warehouse), qty
					),
					title=_("Not Enough Stock"),
				)

	def load_from_issue(self) -> None:
		if not self.against_issue:
			frappe.throw(_("Please select the Department Issue the items are returned against."))
		issue = frappe.db.get_value(
			"Department Issue",
			self.against_issue,
			["docstatus", "issue_type", "department", "warehouse", "company", "job_map"],
			as_dict=True,
		)
		if not issue or issue.docstatus != 1 or issue.issue_type != "Issue":
			frappe.throw(
				_("{0} is not a submitted Department Issue.").format(frappe.bold(self.against_issue))
			)
		if issue.company != self.company:
			frappe.throw(_("{0} belongs to another company.").format(frappe.bold(self.against_issue)))
		self.department = issue.department
		self.job_map = self.job_map or issue.job_map
		self.warehouse = self.warehouse or issue.warehouse

	def validate_return(self) -> None:
		issued = issue_rows(self.against_issue)
		returned = returned_qty(self.against_issue, exclude=self.name)
		for row in self.items:
			src = issued.get(row.item)
			if not src:
				frappe.throw(
					_("Row {0}: {1} was not issued on {2}.").format(
						row.idx, frappe.bold(row.item), self.against_issue
					)
				)
			row.available_qty = flt(src["qty"] - returned.get(row.item, 0.0), 6)
			row.rate = src["rate"]
			row.amount = flt(row.rate * flt(row.qty), row.precision("amount"))
		for item, qty in self.requested().items():
			left = issued[item]["qty"] - returned.get(item, 0.0)
			if qty > left + EPS:
				frappe.throw(
					_(
						"{0}: only {1} can be returned against {2} (issued {3}, returned {4}); {5} is entered."
					).format(
						frappe.bold(item),
						flt(left, 3),
						self.against_issue,
						flt(issued[item]["qty"], 3),
						flt(returned.get(item, 0.0), 3),
						qty,
					),
					title=_("Return Exceeds Issue"),
				)

	def on_submit(self) -> None:
		purpose = "Material Issue" if self.issue_type == "Issue" else "Material Receipt"
		entry = stock._new_entry(
			purpose,
			self.company,
			self.posting_date,
			_("Department {0} {1}: {2}").format(_(self.issue_type), self.name, self.department),
		)
		for row in self.items:
			values = {
				"item_code": row.item,
				"qty": row.qty,
				"expense_account": self.expense_account,
				"cost_center": self.cost_center,
			}
			if self.issue_type == "Issue":
				values["s_warehouse"] = self.warehouse
			else:
				values.update(t_warehouse=self.warehouse, basic_rate=row.rate, set_basic_rate_manually=1)
			entry.append("items", values)
		name = stock._post(entry)
		self.db_set("stock_entry", name)
		if self.issue_type == "Issue":
			for row, posted in zip(self.items, entry.items, strict=True):
				row.db_set(
					{
						"rate": flt(posted.valuation_rate),
						"amount": flt(posted.amount, row.precision("amount")),
					},
					update_modified=False,
				)
			self.db_set(
				"total_amount", flt(sum(flt(r.amount) for r in self.items), self.precision("total_amount"))
			)

	def before_cancel(self) -> None:
		if self.issue_type == "Issue":
			returns = frappe.get_all(
				"Department Issue", filters={"against_issue": self.name, "docstatus": 1}, pluck="name"
			)
			if returns:
				frappe.throw(
					_("{0} cannot be cancelled: returns {1} are made against it. Cancel them first.").format(
						frappe.bold(self.name), ", ".join(returns)
					)
				)

	def on_cancel(self) -> None:
		stock.cancel_stock_entry(self.stock_entry)


def issue_rows(issue: str) -> dict[str, dict]:
	"""{item: {"qty", "rate"}} of a submitted Department Issue (rate weighted by quantity)."""
	totals: dict[str, dict] = {}
	for row in frappe.get_all(
		"Department Issue Item",
		filters={"parent": issue, "parenttype": "Department Issue"},
		fields=["item", "qty", "amount"],
	):
		t = totals.setdefault(row.item, {"qty": 0.0, "amount": 0.0})
		t["qty"] += flt(row.qty)
		t["amount"] += flt(row.amount)
	return {
		item: {"qty": t["qty"], "rate": flt(t["amount"] / t["qty"], 9) if t["qty"] else 0.0}
		for item, t in totals.items()
	}


def returned_qty(issue: str, exclude: str | None = None) -> dict[str, float]:
	rows = frappe.db.sql(
		"""select dii.item, sum(dii.qty) from `tabDepartment Issue Item` dii
		join `tabDepartment Issue` di on di.name = dii.parent
		where di.docstatus = 1 and di.issue_type = 'Return' and di.against_issue = %s and di.name != %s
		group by dii.item""",
		(issue, exclude or ""),
	)
	return {item: flt(qty) for item, qty in rows}


@frappe.whitelist()
def get_return_items(against_issue: str) -> list[dict]:
	"""Items of an issue with the quantity that can still be returned."""
	frappe.has_permission("Department Issue", "read", throw=True)
	issued = issue_rows(against_issue)
	returned = returned_qty(against_issue)
	return [
		{"item": item, "qty": flt(v["qty"] - returned.get(item, 0.0), 6), "rate": v["rate"]}
		for item, v in issued.items()
		if v["qty"] - returned.get(item, 0.0) > EPS
	]


@frappe.whitelist()
def get_defaults(department: str | None = None, company: str | None = None) -> dict:
	frappe.has_permission("Department Issue", "read", throw=True)
	company = company or get_default_company()
	from velocity_ctp.cutting.settings import get_settings

	return {
		"warehouse": frappe.db.get_value(
			"Warehouse", {"warehouse_name": CHEMICAL_STORE, "company": company}, "name"
		),
		"expense_account": get_settings().get("department_consumption_account"),
		"cost_center": department_cost_center(department, company) if department else None,
	}
