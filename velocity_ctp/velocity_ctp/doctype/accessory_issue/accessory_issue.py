# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Accessory Issue: accessories from the store to a process's WIP warehouse for one job.

Issue: Material Transfer store -> process WIP (accessories stay accessory items in WIP). Return:
the reverse. The quantity issued may not exceed the job's unissued allocation (when it has one) or
the stock not allocated to other jobs; a return may not exceed what was issued less what was
returned for that job, item and process.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from velocity_ctp.cutting import stock
from velocity_ctp.procurement import accessories
from velocity_ctp.procurement.common import ACCESSORY_GROUP, validate_items_in_group
from velocity_ctp.setup.install import get_default_company
from velocity_ctp.velocity_ctp.doctype.accessory_allocation.accessory_allocation import (
	TRIM_STORE,
	validate_job,
)


class AccessoryIssue(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if not self.store:
			self.store = stock.get_warehouse(TRIM_STORE, self.company)
		self.wip_warehouse = frappe.db.get_value("Process", self.to_process, "wip_warehouse")
		if not self.wip_warehouse:
			frappe.throw(_("Process {0} has no WIP warehouse.").format(frappe.bold(self.to_process)))
		if self.issue_type == "Issue":
			validate_job(
				self.job_map,
				self.garment_order,
				_("Job Map {0} is closed. Accessories cannot be issued to it."),
			)
		else:
			self.validate_order_on_job()  # returns are allowed after the Job Map is closed
		if not self.items:
			frappe.throw(_("Please add at least one accessory row."))
		validate_items_in_group(self.items, ACCESSORY_GROUP, "Accessory Issue")
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be greater than zero.").format(row.idx))
		if self.issue_type == "Issue":
			self.validate_issue()
		else:
			self.validate_return()
		self.total_qty = flt(sum(flt(r.qty) for r in self.items), self.precision("total_qty"))

	def validate_order_on_job(self) -> None:
		if not frappe.db.exists(
			"Job Map Order",
			{"parent": self.job_map, "parenttype": "Job Map", "garment_order": self.garment_order},
		):
			frappe.throw(
				_("Garment Order {0} is not on Job Map {1}.").format(
					frappe.bold(self.garment_order), frappe.bold(self.job_map)
				)
			)

	def requested(self) -> dict[str, float]:
		totals: dict[str, float] = defaultdict(float)
		for row in self.items:
			totals[row.item] += flt(row.qty)
		return totals

	def validate_issue(self) -> None:
		balances = issue_balances(self.job_map, self.garment_order, [r.item for r in self.items], self.store)
		for row in self.items:
			b = balances[row.item]
			row.allocated_balance = b["allocated"] if b["has_allocation"] else None
			row.available_qty = b["available"]
		for item, qty in self.requested().items():
			b = balances[item]
			if b["has_allocation"] and qty > b["allocated"] + accessories.EPS:
				frappe.throw(
					_(
						"{0}: the allocation for Job Map {1} / {2} has {3} left to issue; {4} is entered. "
						"Allocate more first, or issue less."
					).format(frappe.bold(item), self.job_map, self.garment_order, b["allocated"], qty),
					title=_("Exceeds Allocation"),
				)
			if qty > b["available"] + accessories.EPS:
				frappe.throw(
					_(
						"{0}: only {1} is available in {2} for this job (stock less the quantity allocated to "
						"other jobs); {3} is entered."
					).format(frappe.bold(item), b["available"], frappe.bold(self.store), qty),
					title=_("Not Enough Stock"),
				)

	def validate_return(self) -> None:
		returnable = returnable_qty(self.job_map, self.garment_order, self.to_process, exclude=self.name)
		wip = accessories.store_qty([r.item for r in self.items], self.wip_warehouse)
		for row in self.items:
			row.allocated_balance = None
			row.available_qty = flt(returnable.get(row.item), 3)
		for item, qty in self.requested().items():
			can_return = flt(returnable.get(item), 6)
			if qty > can_return + accessories.EPS:
				frappe.throw(
					_(
						"{0}: only {1} can be returned from {2} for Job Map {3} / {4} (issued less already returned); "
						"{5} is entered."
					).format(
						frappe.bold(item),
						max(can_return, 0),
						self.to_process,
						self.job_map,
						self.garment_order,
						qty,
					),
					title=_("Return Exceeds Issue"),
				)
			if qty > flt(wip.get(item)) + accessories.EPS:
				frappe.throw(
					_("{0}: only {1} is in {2}; {3} is entered.").format(
						frappe.bold(item), flt(wip.get(item)), frappe.bold(self.wip_warehouse), qty
					),
					title=_("Not Enough Stock"),
				)

	def on_submit(self) -> None:
		source, target = (self.store, self.wip_warehouse)
		if self.issue_type == "Return":
			source, target = target, source
		from velocity_ctp.production.stock import make_transfer

		entry = make_transfer(
			self.company,
			self.posting_date,
			_("Accessory {0} {1} for Job Map {2} / {3} ({4})").format(
				_(self.issue_type), self.name, self.job_map, self.garment_order, self.to_process
			),
			[
				{"item_code": r.item, "qty": r.qty, "s_warehouse": source, "t_warehouse": target}
				for r in self.items
			],
		)
		self.db_set("stock_entry", entry)
		self.refresh_allocations()

	def before_cancel(self) -> None:
		if self.issue_type != "Issue":
			return
		# Returns already made against this issue must stay within what is left issued.
		left = returnable_qty(self.job_map, self.garment_order, self.to_process, exclude=self.name)
		for item in self.requested():
			if flt(left.get(item)) < -accessories.EPS:
				frappe.throw(
					_(
						"{0} cannot be cancelled: {1} has already been returned from {2} for this job. "
						"Cancel the return first."
					).format(frappe.bold(self.name), frappe.bold(item), self.to_process),
					title=_("Returned Already"),
				)

	def on_cancel(self) -> None:
		stock.cancel_stock_entry(self.stock_entry)
		self.refresh_allocations()

	def refresh_allocations(self) -> None:
		accessories.refresh_allocations([(self.job_map, self.garment_order, r.item) for r in self.items])


def issue_balances(job_map: str, garment_order: str, items: list[str], store: str) -> dict[str, dict]:
	"""Per item: unissued allocation of this job, whether it has one, and the stock available to it."""
	items = list(set(items))
	key_rows = accessories.allocation_rows([(job_map, garment_order, i) for i in items])
	stock_qty = accessories.store_qty(items, store)
	others: dict[str, float] = defaultdict(float)
	mine: dict[str, float] = defaultdict(float)
	for (jm, order, item), qty in accessories.unissued_allocations(warehouse=store, items=items).items():
		if (jm, order) == (job_map, garment_order):
			mine[item] += qty
		else:
			others[item] += qty
	result = {}
	for item in items:
		rows = key_rows.get((job_map, garment_order, item), [])
		result[item] = {
			"has_allocation": any(flt(r.qty) - flt(r.released_qty) > accessories.EPS for r in rows),
			"allocated": flt(mine[item], 3),
			"available": flt(stock_qty.get(item, 0.0) - others[item], 3),
		}
	return result


def returnable_qty(
	job_map: str, garment_order: str, process: str, exclude: str | None = None
) -> dict[str, float]:
	"""{item: issued - returned} for the job and process (submitted issues, except `exclude`)."""
	result: dict[str, float] = defaultdict(float)
	for (jm, _order, item), qty in accessories.net_issued(
		orders=[garment_order], process=process, exclude_issue=exclude
	).items():
		if jm == job_map:
			result[item] += qty
	return result


@frappe.whitelist()
def get_balances(
	job_map: str,
	garment_order: str,
	issue_type: str,
	to_process: str | None,
	items: str | list,
	store: str | None = None,
	company: str | None = None,
) -> dict[str, dict]:
	frappe.has_permission("Accessory Issue", "read", throw=True)
	items = frappe.parse_json(items) or []
	if issue_type == "Return":
		left = returnable_qty(job_map, garment_order, to_process) if to_process else {}
		return {i: {"allocated": None, "available": flt(left.get(i), 3)} for i in items}
	store = store or stock.get_warehouse(TRIM_STORE, company or get_default_company())
	return issue_balances(job_map, garment_order, items, store)
