# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from velocity_ctp.cutting import ledger, stock
from velocity_ctp.setup.install import get_default_company


class FabricIssue(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		self.validate_job_map()
		self.validate_items()
		self.total_qty = flt(sum(flt(r.qty) for r in self.items), self.precision("total_qty"))

	def on_submit(self) -> None:
		self.db_set("stock_entry", stock.make_fabric_transfer(self))

	def on_cancel(self) -> None:
		if self.issue_type == "Issue":
			self.validate_cancel_issue()
		stock.cancel_stock_entry(self.stock_entry)

	# ------------------------------------------------------------------

	def validate_job_map(self) -> None:
		status = frappe.db.get_value("Job Map", self.job_map, "status")
		if self.issue_type == "Issue" and status != "Ready to Cut":
			frappe.throw(
				_("Fabric can only be issued to a Job Map that is Ready to Cut. Job Map {0} is {1}.").format(
					frappe.bold(self.job_map), frappe.bold(_(status or ""))
				)
			)

	def source_warehouse(self) -> str:
		if self.issue_type == "Issue":
			return stock.get_fabric_store(self.company)
		return stock.get_cutting_wip(self.company)

	def validate_items(self) -> None:
		if not self.items:
			frappe.throw(_("Please add at least one fabric row."))

		source = self.source_warehouse()
		requested: dict[tuple[str, str], float] = defaultdict(float)
		for row in self.items:
			label = _("Row {0}").format(row.idx)
			stock.validate_fabric_batch(label, row.fabric_item, row.batch_no)
			if flt(row.qty) <= 0:
				frappe.throw(_("{0}: Qty must be greater than zero.").format(label))
			requested[(row.fabric_item, row.batch_no)] += flt(row.qty)

		if self.issue_type == "Return":
			balances = ledger.job_fabric([self.job_map], exclude_fabric_issue=self.name)[self.job_map]
			for (item, batch), qty in requested.items():
				values = balances.get((item, batch), {"issued": 0, "returned": 0, "used": 0})
				returnable = ledger.fabric_balance(values)
				if qty > returnable + 1e-9:
					frappe.throw(
						_(
							"Batch {0} of {1}: only {2} can be returned for Job Map {3} "
							"(issued {4}, used {5}, already returned {6}); {7} is entered."
						).format(
							frappe.bold(batch),
							frappe.bold(item),
							max(returnable, 0),
							frappe.bold(self.job_map),
							values["issued"],
							values["used"],
							values["returned"],
							qty,
						),
						title=_("Return Exceeds Balance"),
					)

		available = {key: stock.batch_qty(key[1], source) for key in requested}
		for row in self.items:
			row.available_qty = available[(row.fabric_item, row.batch_no)]

		for (item, batch), qty in requested.items():
			if qty > available[(item, batch)] + 1e-9:
				frappe.throw(
					_("Batch {0} of {1} has only {2} available in {3}; {4} is requested.").format(
						frappe.bold(batch),
						frappe.bold(item),
						available[(item, batch)],
						frappe.bold(source),
						qty,
					),
					title=_("Not Enough Fabric"),
				)

	def validate_cancel_issue(self) -> None:
		"""An issue cannot be cancelled if the fabric left for the Job Map would become negative."""
		balances = ledger.job_fabric([self.job_map], exclude_fabric_issue=self.name)[self.job_map]
		for row in self.items:
			values = balances.get((row.fabric_item, row.batch_no), {"issued": 0, "returned": 0, "used": 0})
			if ledger.fabric_balance(values) < -1e-9:
				frappe.throw(
					_(
						"Fabric Issue {0} cannot be cancelled: batch {1} has already been used or returned "
						"for Job Map {2}. Cancel those documents first."
					).format(frappe.bold(self.name), frappe.bold(row.batch_no), frappe.bold(self.job_map))
				)


@frappe.whitelist()
def get_available_qty(fabric_item: str, batch_no: str, issue_type: str, company: str | None = None) -> float:
	"""Batch quantity in the source warehouse of an Issue (Fabric Store) or Return (Cutting WIP)."""
	frappe.has_permission("Fabric Issue", "read", throw=True)
	company = company or get_default_company()
	warehouse = stock.get_fabric_store(company) if issue_type == "Issue" else stock.get_cutting_wip(company)
	return stock.batch_qty(batch_no, warehouse)


@frappe.whitelist()
def get_source_warehouse(issue_type: str, company: str | None = None) -> str:
	frappe.has_permission("Fabric Issue", "read", throw=True)
	company = company or get_default_company()
	return stock.get_fabric_store(company) if issue_type == "Issue" else stock.get_cutting_wip(company)
