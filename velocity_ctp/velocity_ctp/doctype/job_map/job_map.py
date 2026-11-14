# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

from collections.abc import Iterable

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate

# (check field, date field, approved-by field, stage label) in approval order.
APPROVALS: tuple[tuple[str, str, str, str], ...] = (
	("fit_sample_approved", "fit_sample_date", "fit_sample_by", "Fit"),
	("size_set_sample_approved", "size_set_sample_date", "size_set_sample_by", "Size Set"),
	("photo_sample_approved", "photo_sample_date", "photo_sample_by", "Photo"),
	("pp_sample_approved", "pp_sample_date", "pp_sample_by", "PP"),
	("ok_to_cut", "ok_to_cut_date", "ok_to_cut_by", "OK to Cut"),
)

PICKABLE_ORDER_STATUSES = ("Open", "On Hold")


def get_active_job_maps(garment_orders: Iterable[str], exclude: str | None = None) -> dict[str, str]:
	"""Return {garment_order: job_map} for Job Maps that are not closed (one query)."""
	garment_orders = list(garment_orders)
	if not garment_orders:
		return {}
	jm = frappe.qb.DocType("Job Map")
	jmo = frappe.qb.DocType("Job Map Order")
	query = (
		frappe.qb.from_(jmo)
		.inner_join(jm)
		.on(jm.name == jmo.parent)
		.select(jmo.garment_order, jm.name)
		.where((jmo.parenttype == "Job Map") & (jm.job_closed == 0) & jmo.garment_order.isin(garment_orders))
	)
	if exclude:
		query = query.where(jm.name != exclude)
	return {row[0]: row[1] for row in query.run()}


class JobMap(Document):
	def validate(self) -> None:
		self.validate_orders()
		self.validate_approvals()
		self.stamp_approvals()
		self.set_status()

	def on_update(self) -> None:
		self.sync_garment_order_status()

	def on_trash(self) -> None:
		if self.status == "Ready to Cut":
			self.set_orders_status(self.order_names(), from_status="In Production", to_status="Open")

	# ------------------------------------------------------------------

	def order_names(self) -> list[str]:
		return [row.garment_order for row in self.jobs if row.garment_order]

	def validate_orders(self) -> None:
		if not self.jobs:
			frappe.throw(_("Please add at least one Garment Order."))

		names = self.order_names()
		duplicates = {n for n in names if names.count(n) > 1}
		if duplicates:
			frappe.throw(
				_("Garment Order {0} is added more than once.").format(frappe.bold(", ".join(duplicates)))
			)

		orders = {
			row.name: row
			for row in frappe.get_all(
				"Garment Order", filters={"name": ("in", names)}, fields=["name", "docstatus", "status"]
			)
		}
		for row in self.jobs:
			order = orders.get(row.garment_order)
			if not order or order.docstatus != 1 or order.status == "Cancelled":
				frappe.throw(
					_("Row {0}: Garment Order {1} must be submitted and not cancelled.").format(
						row.idx, frappe.bold(row.garment_order)
					)
				)

		if not self.job_closed:
			taken = get_active_job_maps(names, exclude=self.name if not self.is_new() else None)
			if taken:
				order, job_map = next(iter(taken.items()))
				frappe.throw(
					_("Garment Order {0} is already on Job Map {1}, which is not closed.").format(
						frappe.bold(order), frappe.bold(job_map)
					)
				)

	def validate_approvals(self) -> None:
		if self.ok_to_cut and not self.pp_sample_approved:
			frappe.throw(
				_(
					"OK to Cut can only be given after the PP sample is approved. Please approve the PP sample first."
				),
				title=_("PP Sample Not Approved"),
			)

	def stamp_approvals(self) -> None:
		"""Set date and approver when an approval is ticked; clear them when it is unticked."""
		before = self.get_doc_before_save()
		for check, date_field, by_field, _label in APPROVALS:
			if self.get(check):
				was_checked = bool(before and before.get(check))
				if not was_checked or not self.get(date_field):
					self.set(date_field, nowdate())
					self.set(by_field, frappe.session.user)
			else:
				self.set(date_field, None)
				self.set(by_field, None)

	def set_status(self) -> None:
		if self.job_closed:
			self.status = "Closed"
		elif self.on_hold:
			self.status = "On Hold"
		elif self.ok_to_cut:
			self.status = "Ready to Cut"
		else:
			self.status = "Pending Approvals"

	def sync_garment_order_status(self) -> None:
		"""Ready to Cut moves linked orders to In Production; leaving it moves them back to Open.

		Orders that are On Hold, Completed or Cancelled are never changed here.
		"""
		before = self.get_doc_before_save()
		was_ready = bool(before and before.status == "Ready to Cut")
		names = self.order_names()

		if self.status == "Ready to Cut":
			self.set_orders_status(names, from_status="Open", to_status="In Production")
			if before:
				removed = set(before_names(before)) - set(names)
				self.set_orders_status(list(removed), from_status="In Production", to_status="Open")
		elif was_ready and self.status in ("Pending Approvals", "On Hold"):
			self.set_orders_status(before_names(before), from_status="In Production", to_status="Open")

	@staticmethod
	def set_orders_status(names: list[str], from_status: str, to_status: str) -> None:
		if not names:
			return
		changed = frappe.get_all(
			"Garment Order",
			filters={"name": ("in", names), "docstatus": 1, "status": from_status},
			pluck="name",
		)
		for name in changed:
			frappe.db.set_value("Garment Order", name, "status", to_status)


def before_names(doc) -> list[str]:
	return [row.garment_order for row in doc.jobs if row.garment_order]


@frappe.whitelist()
def get_unavailable_orders(job_map: str | None = None) -> list[str]:
	"""Garment Orders already on another Job Map that is not closed (used by Pick Orders)."""
	frappe.has_permission("Job Map", "read", throw=True)
	jm = frappe.qb.DocType("Job Map")
	jmo = frappe.qb.DocType("Job Map Order")
	query = (
		frappe.qb.from_(jmo)
		.inner_join(jm)
		.on(jm.name == jmo.parent)
		.select(jmo.garment_order)
		.where((jmo.parenttype == "Job Map") & (jm.job_closed == 0))
	)
	if job_map:
		query = query.where(jm.name != job_map)
	return [row[0] for row in query.run()]
