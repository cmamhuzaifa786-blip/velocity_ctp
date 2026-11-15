# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Contractor Bill Run: bills a contractor's unbilled work for a period with a standard Purchase Invoice.

Get Unbilled Work fills the rows (Cut Receive / Process Receive per garment order). On submit a draft
Purchase Invoice is created: one service item row per work document and garment order, expense account
"Contractor Charges Accrued" (so the invoice clears the accrual), each row linked to its source
(velocity_source_doctype / velocity_source_name). A source can be on one invoice only; cancelling the
invoice releases it.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from velocity_ctp.procurement import contractor_billing
from velocity_ctp.setup.install import get_default_company

# Service item per process when a work document has no Service Order row
PROCESS_SERVICE_ITEMS = {
	"Cutting": "Cutting Charges",
	"Stitching": "Stitching Charges (CMT)",
	"Washing": "Washing Charges",
	"Finishing": "Finishing Charges",
}


class ContractorBillRun(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date must be on or before To Date."))
		if not self.items:
			frappe.throw(_("There is no work to bill. Use Get Unbilled Work first."))
		self.check_rows()
		self.total_qty = sum(flt(r.fresh_qty) for r in self.items)
		self.total_amount = flt(sum(flt(r.amount) for r in self.items), self.precision("total_amount"))

	def check_rows(self) -> None:
		"""Every row must still be unbilled work of this contractor (fresh figures from the source)."""
		current = {
			(r.source_doctype, r.source_name, r.garment_order): r
			for r in contractor_billing.work_rows(supplier=self.supplier, company=self.company)
		}
		for row in self.items:
			work = current.get((row.source_doctype, row.source_name, row.garment_order))
			if not work:
				frappe.throw(
					_("Row {0}: {1} {2} is not contractor work of {3}.").format(
						row.idx, _(row.source_doctype), row.source_name, self.supplier
					)
				)
			if work.taken_by and work.taken_by != self.purchase_invoice:
				frappe.throw(
					_("Row {0}: {1} {2} is already billed on Purchase Invoice {3}.").format(
						row.idx,
						_(row.source_doctype),
						frappe.bold(row.source_name),
						frappe.bold(work.taken_by),
					),
					title=_("Already Billed"),
				)
			row.update(
				{
					"posting_date": work.posting_date,
					"production_process": work.process,
					"fresh_qty": work.fresh_qty,
					"rate": work.rate,
					"amount": work.amount,
					"service_order": work.service_order,
					"service_order_item": work.service_order_item,
				}
			)

	def on_submit(self) -> None:
		self.db_set("purchase_invoice", self.make_invoice())

	def make_invoice(self) -> str:
		from velocity_ctp.production.absorption import CONTRACTOR_ACCRUAL, charge_account

		accrual = charge_account(self.company, CONTRACTOR_ACCRUAL)
		po_required = frappe.db.get_single_value("Buying Settings", "po_required") == "Yes"
		without_po = [r for r in self.items if not r.service_order]
		if (
			po_required
			and without_po
			and not frappe.db.get_value(
				"Supplier", self.supplier, "allow_purchase_invoice_creation_without_purchase_order"
			)
		):
			frappe.throw(
				_(
					"Rows {0} have no Service Order, and Buying Settings require a Purchase Order on every invoice row. "
					"Tick 'Allow Purchase Invoice Creation Without Purchase Order' on Supplier {1}, or use Service Orders."
				).format(", ".join(str(r.idx) for r in without_po), frappe.bold(self.supplier)),
				title=_("Purchase Order Required"),
			)
		so_items = {
			r.service_order_item: frappe.db.get_value(
				"Purchase Order Item", r.service_order_item, "item_code"
			)
			for r in self.items
			if r.service_order_item
		}
		invoice = frappe.new_doc("Purchase Invoice")
		invoice.update(
			{
				"supplier": self.supplier,
				"company": self.company,
				"posting_date": self.posting_date,
				"set_posting_time": 1,
				"contractor_bill_run": self.name,
				"remarks": _("Contractor work {0} to {1} (Contractor Bill Run {2})").format(
					frappe.format(self.from_date, {"fieldtype": "Date"}),
					frappe.format(self.to_date, {"fieldtype": "Date"}),
					self.name,
				),
			}
		)
		for row in self.items:
			item = so_items.get(row.service_order_item) or PROCESS_SERVICE_ITEMS.get(row.production_process)
			if not item or not frappe.db.exists("Item", item):
				frappe.throw(
					_(
						"Row {0}: no service item for process {1}. Use a Service Order or create the item {2}."
					).format(row.idx, row.production_process, item or "-")
				)
			invoice.append(
				"items",
				{
					"item_code": item,
					"qty": row.fresh_qty,
					"rate": row.rate,
					"expense_account": accrual,
					"purchase_order": row.service_order,  # header link only: no po_detail
					"garment_order": row.garment_order,
					"production_process": row.production_process,
					"description": _("{0} for {1}: {2} pieces ({3} {4})").format(
						row.production_process,
						row.garment_order,
						int(flt(row.fresh_qty)),
						_(row.source_doctype),
						row.source_name,
					),
					"velocity_source_doctype": row.source_doctype,
					"velocity_source_name": row.source_name,
				},
			)
		invoice.flags.ignore_permissions = True  # the user's Bill Run submit right was checked
		invoice.insert()
		self.add_comment("Info", _("Draft Purchase Invoice {0} created.").format(invoice.name))
		return invoice.name

	def before_cancel(self) -> None:
		if (
			self.purchase_invoice
			and frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "docstatus") != 2
		):
			frappe.throw(
				_(
					"Purchase Invoice {0} is not cancelled. Cancel it first (a draft invoice has to be submitted and "
					"cancelled, or deleted by an accounts user)."
				).format(frappe.bold(self.purchase_invoice)),
				title=_("Invoice Still Active"),
			)


@frappe.whitelist()
def get_unbilled_work(supplier: str, from_date: str, to_date: str, company: str | None = None) -> list[dict]:
	frappe.has_permission("Contractor Bill Run", "create", throw=True)
	rows = contractor_billing.work_rows(
		supplier=supplier, from_date=from_date, to_date=to_date, company=company
	)
	return [
		{
			"source_doctype": r.source_doctype,
			"source_name": r.source_name,
			"posting_date": r.posting_date,
			"production_process": r.process,
			"garment_order": r.garment_order,
			"fresh_qty": r.fresh_qty,
			"rate": r.rate,
			"amount": r.amount,
			"service_order": r.service_order,
			"service_order_item": r.service_order_item,
		}
		for r in rows
		if not r.taken_by
	]


def get_statement(bill_run: str) -> list[dict]:
	"""Contractor statement for the print: rows grouped by garment order and process."""
	doc = frappe.get_doc("Contractor Bill Run", bill_run)
	groups: dict[tuple[str, str], dict] = {}
	for row in doc.items:
		g = groups.setdefault(
			(row.garment_order, row.production_process),
			{
				"garment_order": row.garment_order,
				"process": row.production_process,
				"rows": [],
				"qty": 0,
				"amount": 0.0,
			},
		)
		g["rows"].append(row)
		g["qty"] += flt(row.fresh_qty)
		g["amount"] += flt(row.amount)
	return list(groups.values())
