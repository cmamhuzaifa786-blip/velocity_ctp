# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Accessory Allocation: a soft reservation of store stock for one job (no stock movement).

The quantity of each item may not exceed the stock in the warehouse less what other jobs have
allocated and not yet received. Issues for the job use the allocation up (see
procurement.accessories). Cancel is allowed only while nothing has been issued against it; after
that, "Release Unissued" frees the part not yet issued.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from velocity_ctp.cutting.stock import get_warehouse
from velocity_ctp.procurement import accessories
from velocity_ctp.procurement.common import ACCESSORY_GROUP, validate_items_in_group
from velocity_ctp.setup.install import get_default_company

TRIM_STORE = "Trim Store"


def validate_job(job_map: str, garment_order: str, closed_message: str) -> None:
	"""The Garment Order must be on the Job Map, and the Job Map must not be closed."""
	if not frappe.db.exists(
		"Job Map Order", {"parent": job_map, "parenttype": "Job Map", "garment_order": garment_order}
	):
		frappe.throw(
			_("Garment Order {0} is not on Job Map {1}.").format(
				frappe.bold(garment_order), frappe.bold(job_map)
			)
		)
	if frappe.db.get_value("Job Map", job_map, "job_closed"):
		frappe.throw(closed_message.format(frappe.bold(job_map)))


class AccessoryAllocation(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if not self.warehouse:
			self.warehouse = get_warehouse(TRIM_STORE, self.company)
		validate_job(
			self.job_map,
			self.garment_order,
			_("Job Map {0} is closed. Accessories cannot be allocated to it."),
		)
		if not self.items:
			frappe.throw(_("Please add at least one accessory row."))
		validate_items_in_group(self.items, ACCESSORY_GROUP, "Accessory Allocation")
		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be greater than zero.").format(row.idx))
		self.validate_quantities()
		self.total_qty = flt(sum(flt(r.qty) for r in self.items), self.precision("total_qty"))
		if self.docstatus == 0:
			self.status = "Draft"

	def validate_quantities(self) -> None:
		available = available_unallocated([r.item for r in self.items], self.warehouse, exclude=self.name)
		requested: dict[str, float] = defaultdict(float)
		for row in self.items:
			row.available_unallocated = available.get(row.item, 0.0)
			requested[row.item] += flt(row.qty)
		for item, qty in requested.items():
			if qty > available.get(item, 0.0) + accessories.EPS:
				frappe.throw(
					_(
						"{0}: only {1} can be allocated in {2} (stock less the quantity allocated to other jobs "
						"and not yet issued); {3} is entered."
					).format(
						frappe.bold(item), flt(available.get(item), 3), frappe.bold(self.warehouse), qty
					),
					title=_("Not Enough Unallocated Stock"),
				)

	def on_submit(self) -> None:
		self.db_set("status", "Allocated")
		# Issues already made for this job count against the new allocation as well.
		accessories.refresh_allocations([(self.job_map, self.garment_order, r.item) for r in self.items])

	def before_cancel(self) -> None:
		issued = [r for r in self.items if flt(r.issued_qty) > accessories.EPS]
		if issued:
			frappe.throw(
				_(
					"{0} cannot be cancelled because {1} has already been issued against it. "
					"Use Release Unissued to cancel the part that is not yet issued."
				).format(
					frappe.bold(self.name),
					", ".join(
						f"{flt(r.issued_qty, 3):g} {r.uom or ''} {r.item}".replace("  ", " ") for r in issued
					),
				),
				title=_("Already Issued"),
			)

	def on_cancel(self) -> None:
		self.db_set("status", "Cancelled")
		accessories.refresh_allocations([(self.job_map, self.garment_order, r.item) for r in self.items])


def available_unallocated(items: list[str], warehouse: str, exclude: str | None = None) -> dict[str, float]:
	"""{item: stock in the warehouse - unissued allocations of submitted allocations (except `exclude`)}."""
	stock = accessories.store_qty(items, warehouse)
	allocated: dict[str, float] = defaultdict(float)
	for (_jm, _order, item), qty in accessories.unissued_allocations(
		warehouse=warehouse, items=list(set(items)), exclude_allocation=exclude
	).items():
		allocated[item] += qty
	return {item: flt(stock.get(item, 0.0) - allocated[item], 3) for item in set(items)}


@frappe.whitelist()
def get_available_unallocated(items: str | list, warehouse: str, name: str | None = None) -> dict[str, float]:
	frappe.has_permission("Accessory Allocation", "read", throw=True)
	return available_unallocated(frappe.parse_json(items) or [], warehouse, exclude=name)


@frappe.whitelist(methods=["POST"])
def release_unissued(name: str) -> str:
	"""Cancel the part of a submitted allocation that is not yet issued."""
	doc = frappe.get_doc("Accessory Allocation", name)
	doc.check_permission("submit")
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted allocation can be released."))
	accessories.refresh_allocations([(doc.job_map, doc.garment_order, r.item) for r in doc.items])
	doc.reload()
	released = []
	for row in doc.items:
		free = accessories.unissued(row)
		if free > accessories.EPS:
			row.db_set("released_qty", flt(row.released_qty) + free, update_modified=False)
			released.append(f"{flt(free, 3)} {row.item}")
	if not released:
		frappe.throw(_("Nothing to release: the allocation is fully issued or already released."))
	accessories.update_allocation_status(doc.name)
	doc.add_comment("Info", _("Released the unissued quantity: {0}.").format(", ".join(released)))
	return frappe.db.get_value("Accessory Allocation", doc.name, "status")


@frappe.whitelist()
def get_job_options(job_map: str | None = None, garment_order: str | None = None) -> dict:
	"""Garment Orders on the Job Map and the order's colours and sizes."""
	frappe.has_permission("Accessory Allocation", "read", throw=True)
	result = {"orders": [], "colours": [], "sizes": []}
	if job_map:
		result["orders"] = frappe.get_all(
			"Job Map Order",
			filters={"parent": job_map, "parenttype": "Job Map"},
			pluck="garment_order",
			order_by="idx",
		)
	if garment_order:
		from velocity_ctp.velocity_ctp.doctype.material_plan.material_plan import cutting_quantities

		qty = cutting_quantities(garment_order)
		result["colours"], result["sizes"] = qty["colours"], qty["sizes"]
	return result
