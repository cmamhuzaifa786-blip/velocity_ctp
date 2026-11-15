# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from velocity_ctp.cutting import ledger, stock


class CuttingMarker(Document):
	def validate(self) -> None:
		self.validate_job_map_and_order()
		self.validate_sizes()
		self.calculate()
		self.validate_fabric()
		if self.docstatus == 0:
			self.status = "Planned"

	def on_cancel(self) -> None:
		self.db_set("status", "Planned")

	# ------------------------------------------------------------------

	def validate_job_map_and_order(self) -> None:
		status = frappe.db.get_value("Job Map", self.job_map, "status")
		if status != "Ready to Cut":
			frappe.throw(
				_("Markers can only be made for a Job Map that is Ready to Cut. Job Map {0} is {1}.").format(
					frappe.bold(self.job_map), frappe.bold(_(status or ""))
				)
			)
		in_job = frappe.db.exists(
			"Job Map Order",
			{"parent": self.job_map, "parenttype": "Job Map", "garment_order": self.garment_order},
		)
		if not in_job:
			frappe.throw(
				_("Garment Order {0} is not on Job Map {1}.").format(
					frappe.bold(self.garment_order), frappe.bold(self.job_map)
				)
			)
		colours = {
			c.lower(): c
			for c in frappe.get_all(
				"Garment Order Item",
				filters={"parent": self.garment_order, "parenttype": "Garment Order"},
				pluck="colour",
			)
		}
		colour = (self.colour or "").strip()
		if colour.lower() not in colours:
			frappe.throw(
				_("Colour {0} is not on Garment Order {1}. Order colours: {2}.").format(
					frappe.bold(colour),
					frappe.bold(self.garment_order),
					", ".join(sorted(set(colours.values()))),
				)
			)
		self.colour = colours[colour.lower()]
		from velocity_ctp.cutting.colours import cut_colour

		self.cut_colour = cut_colour(self.garment_order, self.colour)

	def validate_sizes(self) -> None:
		if not self.size_ratio:
			frappe.throw(_("Please enter the size ratio."))
		size_set = frappe.db.get_value("Garment Order", self.garment_order, "size_set")
		sizes = {
			s.lower(): s
			for s in frappe.get_all(
				"Size Set Item", filters={"parent": size_set, "parenttype": "Size Set"}, pluck="size"
			)
		}
		seen = set()
		for row in self.size_ratio:
			size = (row.size or "").strip()
			if size.lower() not in sizes:
				frappe.throw(
					_("Size Ratio row {0}: size {1} is not in Size Set {2}.").format(
						row.idx, frappe.bold(size), frappe.bold(size_set)
					)
				)
			if size.lower() in seen:
				frappe.throw(
					_("Size Ratio row {0}: size {1} is entered more than once.").format(row.idx, size)
				)
			seen.add(size.lower())
			if cint(row.ratio) <= 0:
				frappe.throw(_("Size Ratio row {0}: ratio must be greater than zero.").format(row.idx))
			row.size = sizes[size.lower()]

	def calculate(self) -> None:
		if flt(self.marker_length) <= 0:
			frappe.throw(_("Marker Length must be greater than zero."))
		if cint(self.no_of_plies) <= 0:
			frappe.throw(_("No. of Plies must be greater than zero."))
		for row in self.size_ratio:
			row.planned_pieces = cint(row.ratio) * cint(self.no_of_plies)
		self.total_planned_pieces = sum(cint(r.planned_pieces) for r in self.size_ratio)
		self.fabric_required = flt(
			flt(self.marker_length) * cint(self.no_of_plies) * (1 + flt(self.end_loss_percent) / 100),
			self.precision("fabric_required"),
		)

	def validate_fabric(self) -> None:
		stock.validate_fabric_batch(_("Fabric"), self.fabric_item, self.batch_no)
		values = ledger.job_fabric([self.job_map])[self.job_map].get(
			(self.fabric_item, self.batch_no), {"issued": 0, "returned": 0, "used": 0}
		)
		if not values["issued"]:
			frappe.throw(
				_(
					"Batch {0} of {1} has not been issued to Job Map {2}. Issue it with a Fabric Issue first."
				).format(
					frappe.bold(self.batch_no), frappe.bold(self.fabric_item), frappe.bold(self.job_map)
				),
				title=_("Batch Not Issued"),
			)
		available = ledger.fabric_balance(values)
		if self.fabric_required > available + 1e-9:
			frappe.throw(
				_(
					"Fabric required {0} m is more than the {1} m of batch {2} issued to Job Map {3} and not yet used."
				).format(
					self.fabric_required, available, frappe.bold(self.batch_no), frappe.bold(self.job_map)
				),
				title=_("Not Enough Fabric Issued"),
			)


@frappe.whitelist()
def get_issued_batches(job_map: str) -> list[dict]:
	"""Batches issued to a Job Map with their unused balance (for the batch picker)."""
	frappe.has_permission("Cutting Marker", "read", throw=True)
	rows = []
	for (item, batch), values in ledger.job_fabric([job_map])[job_map].items():
		if values["issued"]:
			rows.append({"fabric_item": item, "batch_no": batch, "balance": ledger.fabric_balance(values)})
	return rows


@frappe.whitelist()
def get_order_options(job_map: str | None = None, garment_order: str | None = None) -> dict:
	"""Orders on the Job Map, and the selected order's colours and sizes (for the pickers)."""
	frappe.has_permission("Cutting Marker", "read", throw=True)
	orders = (
		frappe.get_all(
			"Job Map Order", filters={"parent": job_map, "parenttype": "Job Map"}, pluck="garment_order"
		)
		if job_map
		else []
	)
	colours, sizes = [], []
	if garment_order:
		colours = sorted(
			set(
				frappe.get_all(
					"Garment Order Item",
					filters={"parent": garment_order, "parenttype": "Garment Order"},
					pluck="colour",
				)
			)
		)
		size_set = frappe.db.get_value("Garment Order", garment_order, "size_set")
		sizes = frappe.get_all(
			"Size Set Item",
			filters={"parent": size_set, "parenttype": "Size Set"},
			pluck="size",
			order_by="sequence asc, idx asc",
		)
	return {"orders": orders, "colours": colours, "sizes": sizes}
