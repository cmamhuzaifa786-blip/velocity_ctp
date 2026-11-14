# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from velocity_ctp.cutting import bundles, ledger, stock
from velocity_ctp.cutting.settings import get_settings
from velocity_ctp.setup.install import get_default_company


class CutReceive(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		markers = self.validate_markers()
		self.sync_from_markers(markers)
		self.validate_pieces()
		self.validate_fabric()
		self.calculate_totals()

	def before_submit(self) -> None:
		if cint(self.total_good_qty) <= 0:
			frappe.throw(_("There are no good pieces to receive. Enter the cut quantities first."))
		if flt(self.total_fabric_used) <= 0:
			frappe.throw(_("Please enter the fabric used."))

	def on_submit(self) -> None:
		self.warn_on_wastage()
		self.db_set("stock_entry", stock.make_cut_repack(self, self.good_rows()))
		for row in self.markers:
			frappe.db.set_value("Cutting Marker", row.cutting_marker, "status", "Cut")
		self.db_set("bundle_count", bundles.create_bundles(self))

	def before_cancel(self) -> None:
		allowed, reason = bundles.can_cancel_cut_receive(self.name)
		if not allowed:
			frappe.throw(reason, title=_("Cannot Cancel"))

	def on_cancel(self) -> None:
		stock.cancel_stock_entry(self.stock_entry)
		bundles.delete_bundles(self.name)
		for row in self.markers:
			frappe.db.set_value("Cutting Marker", row.cutting_marker, "status", "Planned")
		self.db_set("bundle_count", 0)

	# ------------------------------------------------------------------
	# Markers -> pieces and fabric
	# ------------------------------------------------------------------

	def validate_markers(self) -> list[frappe._dict]:
		if not self.markers:
			frappe.throw(_("Please add at least one Cutting Marker."))
		names = [row.cutting_marker for row in self.markers]
		duplicates = sorted({n for n in names if names.count(n) > 1})
		if duplicates:
			frappe.throw(_("Cutting Marker {0} is added more than once.").format(", ".join(duplicates)))

		markers = {
			m.name: m
			for m in frappe.get_all(
				"Cutting Marker",
				filters={"name": ("in", names)},
				fields=["name", "docstatus", "status", "job_map", "garment_order", "colour", "fabric_item",
				        "batch_no", "fabric_required", "total_planned_pieces"],
			)
		}  # fmt: skip
		for row in self.markers:
			marker = markers.get(row.cutting_marker)
			if not marker or marker.docstatus != 1:
				frappe.throw(
					_("Markers row {0}: Cutting Marker {1} must be submitted.").format(
						row.idx, row.cutting_marker
					)
				)
			if marker.job_map != self.job_map:
				frappe.throw(
					_("Markers row {0}: Cutting Marker {1} belongs to Job Map {2}, not {3}.").format(
						row.idx, row.cutting_marker, marker.job_map, self.job_map
					)
				)
			if marker.status != "Planned":
				frappe.throw(
					_("Markers row {0}: Cutting Marker {1} has already been cut.").format(
						row.idx, row.cutting_marker
					)
				)
			row.garment_order, row.colour, row.batch_no = marker.garment_order, marker.colour, marker.batch_no
			row.total_planned_pieces, row.fabric_required = (
				marker.total_planned_pieces,
				marker.fabric_required,
			)
		return [markers[name] for name in names]

	@frappe.whitelist()
	def sync_from_markers(self, markers: list | None = None) -> None:
		"""Rebuild the piece and fabric rows from the markers, keeping quantities already entered."""
		if markers is None:
			markers = self.validate_markers() if self.markers else []
		marker_names = [m.name for m in markers]
		sizes = frappe.get_all(
			"Cutting Marker Size",
			filters={"parent": ("in", marker_names or [""]), "parenttype": "Cutting Marker"},
			fields=["parent", "size", "planned_pieces", "idx"],
			order_by="idx asc",
		)
		sizes_by_marker = defaultdict(list)
		for s in sizes:
			sizes_by_marker[s.parent].append(s)

		planned: dict[tuple, dict] = {}
		required: dict[tuple, float] = {}
		for marker in markers:
			for s in sizes_by_marker[marker.name]:
				key = ledger.piece_key(marker.garment_order, marker.colour, s.size)
				line = planned.setdefault(
					key,
					{
						"garment_order": marker.garment_order,
						"colour": marker.colour,
						"size": s.size,
						"qty": 0,
					},
				)
				line["qty"] += cint(s.planned_pieces)
			fabric_key = (marker.fabric_item, marker.batch_no)
			required[fabric_key] = required.get(fabric_key, 0.0) + flt(marker.fabric_required)

		item_codes = self.variant_codes(planned.values())
		existing_pieces = {ledger.piece_key(p.garment_order, p.colour, p.size): p for p in self.pieces}
		pieces = []
		for key, line in planned.items():
			old = existing_pieces.get(key)
			pieces.append(
				{
					"garment_order": line["garment_order"],
					"colour": line["colour"],
					"size": line["size"],
					"item_code": item_codes.get(key),
					"planned_qty": line["qty"],
					"cut_qty": cint(old.cut_qty) if old else line["qty"],
					"rejected_qty": cint(old.rejected_qty) if old else 0,
				}
			)
		self.set("pieces", pieces)

		existing_fabric = {(f.fabric_item, f.batch_no): f for f in self.fabric}
		wip = stock.get_cutting_wip(self.company or get_default_company())
		fabric = []
		for (item, batch), qty in required.items():
			old = existing_fabric.get((item, batch))
			fabric.append(
				{
					"fabric_item": item,
					"batch_no": batch,
					"required_qty": flt(qty, 3),
					"used_qty": flt(old.used_qty) if old else flt(qty, 3),
					"available_qty": stock.batch_qty(batch, wip),
				}
			)
		self.set("fabric", fabric)
		self.calculate_totals()

	@staticmethod
	def variant_codes(lines) -> dict[tuple, str]:
		"""{piece key: variant item code} using each order's Style variant map."""
		lines = list(lines)
		order_styles = dict(
			frappe.get_all(
				"Garment Order",
				filters={"name": ("in", list({line["garment_order"] for line in lines}) or [""])},
				fields=["name", "style"],
				as_list=True,
			)
		)
		maps = {
			style: frappe.get_doc("Style", style).get_variant_map() for style in set(order_styles.values())
		}
		codes = {}
		for line in lines:
			key = ledger.piece_key(line["garment_order"], line["colour"], line["size"])
			variant_map = maps.get(order_styles.get(line["garment_order"]), {})
			codes[key] = variant_map.get((line["colour"].lower(), line["size"].lower()))
		return codes

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_pieces(self) -> None:
		tolerance = flt(get_settings().cut_over_tolerance_percent)
		this_cut: dict[tuple, int] = defaultdict(int)
		for row in self.pieces:
			label = _("Cut Pieces row {0} ({1} / {2})").format(row.idx, row.colour, row.size)
			if not row.item_code:
				frappe.throw(_("{0}: no item variant exists for this colour and size.").format(label))
			if cint(row.cut_qty) < 0 or cint(row.rejected_qty) < 0:
				frappe.throw(_("{0}: quantities cannot be negative.").format(label))
			if cint(row.rejected_qty) > cint(row.cut_qty):
				frappe.throw(_("{0}: rejected quantity cannot be more than the cut quantity.").format(label))
			row.good_qty = cint(row.cut_qty) - cint(row.rejected_qty)
			this_cut[ledger.piece_key(row.garment_order, row.colour, row.size)] += cint(row.cut_qty)

		orders = list({k[0] for k in this_cut})
		lines = frappe.get_all(
			"Garment Order Item",
			filters={"parent": ("in", orders or [""]), "parenttype": "Garment Order"},
			fields=["parent", "colour", "size", "cutting_qty"],
		)
		cutting_qty = {ledger.piece_key(r.parent, r.colour, r.size): cint(r.cutting_qty) for r in lines}
		previous = ledger.cut_quantities(orders, exclude_cut_receive=self.name)

		for key, qty in this_cut.items():
			target = cutting_qty.get(key, 0)
			allowed = math.floor(target * (1 + tolerance / 100) + 1e-9)
			already = previous[key]["cut"] if key in previous else 0
			if already + qty > allowed:
				order = key[0]
				row = next(
					p for p in self.pieces if ledger.piece_key(p.garment_order, p.colour, p.size) == key
				)
				frappe.throw(
					_(
						"{0} / {1} on Garment Order {2}: cutting quantity is {3}, allowed with {4}% tolerance is {5}. "
						"Already cut {6} + this Cut Receive {7} = {8}, which is {9} over the limit."
					).format(
						frappe.bold(row.colour), frappe.bold(row.size), frappe.bold(order), target, tolerance,
						allowed, already, qty, already + qty, already + qty - allowed,
					),
					title=_("Over-Cut"),
				)  # fmt: skip

	def validate_fabric(self) -> None:
		wip = stock.get_cutting_wip(self.company)
		balances = ledger.job_fabric([self.job_map], exclude_cut_receive=self.name)[self.job_map]
		for row in self.fabric:
			label = _("Fabric row {0} (batch {1})").format(row.idx, row.batch_no)
			if flt(row.used_qty) < 0:
				frappe.throw(_("{0}: used quantity cannot be negative.").format(label))
			row.available_qty = stock.batch_qty(row.batch_no, wip)
			if flt(row.used_qty) > flt(row.available_qty) + 1e-9:
				frappe.throw(
					_("{0}: used {1} m, but only {2} m of this batch is in {3}.").format(
						label, flt(row.used_qty), flt(row.available_qty), frappe.bold(wip)
					),
					title=_("Not Enough Fabric in Cutting WIP"),
				)
			values = balances.get((row.fabric_item, row.batch_no), {"issued": 0, "returned": 0, "used": 0})
			job_balance = ledger.fabric_balance(values)
			if flt(row.used_qty) > job_balance + 1e-9:
				frappe.throw(
					_(
						"{0}: used {1} m, but only {2} m of this batch is issued to Job Map {3} and not yet used or returned."
					).format(label, flt(row.used_qty), max(job_balance, 0), frappe.bold(self.job_map)),
					title=_("Not Enough Fabric Issued"),
				)

	def calculate_totals(self) -> None:
		for row in self.pieces:
			row.good_qty = cint(row.cut_qty) - cint(row.rejected_qty)
		self.total_planned_qty = sum(cint(p.planned_qty) for p in self.pieces)
		self.total_cut_qty = sum(cint(p.cut_qty) for p in self.pieces)
		self.total_rejected_qty = sum(cint(p.rejected_qty) for p in self.pieces)
		self.total_good_qty = sum(cint(p.good_qty) for p in self.pieces)
		self.total_fabric_required = flt(sum(flt(f.required_qty) for f in self.fabric), 3)
		self.total_fabric_used = flt(sum(flt(f.used_qty) for f in self.fabric), 3)
		self.wastage_percent = (
			flt((self.total_fabric_used - self.total_fabric_required) / self.total_fabric_required * 100, 2)
			if self.total_fabric_required
			else 0
		)
		self.contractor_amount = flt(
			self.total_cut_qty * flt(self.piece_rate), self.precision("contractor_amount")
		)

	def good_rows(self) -> list[dict]:
		merged: dict[str, int] = defaultdict(int)
		for row in self.pieces:
			if cint(row.good_qty) > 0:
				merged[row.item_code] += cint(row.good_qty)
		return [{"item_code": item, "qty": qty} for item, qty in merged.items()]

	def warn_on_wastage(self) -> None:
		alert = flt(get_settings().fabric_wastage_alert_percent)
		if alert and flt(self.wastage_percent) > alert:
			message = _(
				"Fabric wastage is {0}% (used {1} m against {2} m required by the markers), above the alert level of {3}%."
			).format(flt(self.wastage_percent), self.total_fabric_used, self.total_fabric_required, alert)
			self.add_comment("Comment", _("Wastage warning: {0}").format(message))
			frappe.msgprint(message, title=_("High Fabric Wastage"), indicator="orange")


@frappe.whitelist()
def get_planned_markers(job_map: str) -> list[str]:
	"""Submitted markers of a Job Map that are not yet cut (for the marker picker)."""
	frappe.has_permission("Cut Receive", "read", throw=True)
	return frappe.get_all(
		"Cutting Marker", filters={"job_map": job_map, "docstatus": 1, "status": "Planned"}, pluck="name"
	)
