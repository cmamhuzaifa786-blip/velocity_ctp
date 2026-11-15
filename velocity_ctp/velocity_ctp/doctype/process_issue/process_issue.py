# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from velocity_ctp.production import flow, stock
from velocity_ctp.setup.install import get_default_company


class ProcessIssue(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		info = flow.validate_process_party(self.production_process, self.party)
		flow.posting_date_check(self.posting_date, _("Posting Date"))
		if self.piece_rate is None or (not flt(self.piece_rate) and self.is_new()):
			self.piece_rate = flt(info.default_piece_rate)
		self.validate_bundles()
		self.total_bundles = len(self.bundles)
		self.total_qty = sum(cint(r.qty) for r in self.bundles)
		self.set_service_order(info)
		self.amount = flt(self.total_qty * flt(self.piece_rate), self.precision("amount"))

	def set_service_order(self, info) -> None:
		"""Outsourced work needs an approved Service Order row for this process and garment order;
		the piece rate comes from that row."""
		from velocity_ctp.procurement.services import find_row

		if not flow.is_outsourced(info.process_type, self.party):
			self.service_order = self.service_order_item = None
			return
		if not self.service_order:
			frappe.throw(
				_(
					"{0} is outsourced to {1}: please select the approved Service Order (Purchase Order with "
					"category Service) for this work."
				).format(self.production_process, frappe.bold(self.party)),
				title=_("Service Order Required"),
			)
		orders = sorted({r.garment_order for r in self.bundles if r.garment_order})
		if len(orders) > 1:
			frappe.throw(
				_(
					"With a Service Order, issue the bundles of one Garment Order per Process Issue. This issue has "
					"{0}."
				).format(", ".join(orders))
			)
		row = find_row(self.service_order, self.party, self.production_process, orders[0])
		self.service_order_item = row.name
		self.piece_rate = flt(row.base_rate)
		self._service_row = row

	def validate_bundles(self) -> None:
		if not self.bundles:
			frappe.throw(_("Please add at least one bundle."))
		names = [r.bundle for r in self.bundles]
		duplicates = sorted({n for n in names if names.count(n) > 1})
		if duplicates:
			frappe.throw(_("Bundle {0} is added more than once.").format(", ".join(duplicates)))
		for row in self.bundles:
			bundle = frappe.get_doc("Bundle", row.bundle)
			if self.docstatus == 0:
				reason = flow.issue_block(bundle, self.production_process)
				if reason:
					frappe.throw(reason, title=_("Bundle Cannot Be Issued"))
			row.update(
				{
					"garment_order": bundle.garment_order,
					"style": bundle.style,
					"colour": bundle.colour,
					"size": bundle.size,
					"qty": bundle.qty,
					"item_code": bundle.item_code,
					"source_warehouse": bundle.current_warehouse,
				}
			)

	def before_submit(self) -> None:
		if self.service_order_item:
			from velocity_ctp.procurement.services import validate_capacity

			row = getattr(self, "_service_row", None) or frappe._dict(
				frappe.db.get_value(
					"Purchase Order Item", self.service_order_item, ["name", "qty", "idx"], as_dict=True
				)
			)
			validate_capacity(row, self.total_qty, (self.doctype, self.name), _("Process Issue"))
		# Bundle states may have changed since the draft was saved: check again.
		for row in self.bundles:
			bundle = frappe.get_doc("Bundle", row.bundle)
			reason = flow.issue_block(bundle, self.production_process)
			if reason:
				frappe.throw(reason, title=_("Bundle Cannot Be Issued"))
		self.target_warehouse = self.get_target_warehouse()

	def get_target_warehouse(self) -> str:
		process_type, wip = frappe.db.get_value(
			"Process", self.production_process, ["process_type", "wip_warehouse"]
		)
		if flow.is_outsourced(process_type, self.party):
			return stock.get_contractor_warehouse(self.party, self.company)
		return wip

	def on_submit(self) -> None:
		rows = []
		for row in self.bundles:
			bundle = frappe.get_doc("Bundle", row.bundle)
			flow.snapshot(row, bundle)
			row.db_update()
			rows.append(
				{"item_code": bundle.item_code, "qty": bundle.qty, "s_warehouse": bundle.current_warehouse,
				 "t_warehouse": self.target_warehouse}
			)  # fmt: skip
			flow.apply_issue(bundle, self, self.target_warehouse)
		remarks = _("Process Issue {0}: {1}{2}").format(
			self.name, self.production_process, f" ({self.party})" if self.party else ""
		)
		self.db_set("stock_entry", stock.make_transfer(self.company, self.posting_date, remarks, rows))
		self.db_set("target_warehouse", self.target_warehouse)

	def before_cancel(self) -> None:
		received = flow.receives_against_issue(self.name)
		if received:
			frappe.throw(
				_(
					"Process Issue {0} cannot be cancelled: its bundles have been received on {1}. Cancel that first."
				).format(frappe.bold(self.name), ", ".join(received)),
				title=_("Cannot Cancel"),
			)
		used = flow.later_use([r.bundle for r in self.bundles], self.doctype, self.name, self.creation)
		if used:
			frappe.throw(
				_("Process Issue {0} cannot be cancelled: {1}.").format(frappe.bold(self.name), used)
			)

	def on_cancel(self) -> None:
		from velocity_ctp.cutting.stock import cancel_stock_entry

		cancel_stock_entry(self.stock_entry)
		for row in self.bundles:
			flow.restore(frappe.get_doc("Bundle", row.bundle), row, self.doctype, self.name)
