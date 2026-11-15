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
		self.validate_row_markers(markers)
		self.sync_from_markers(markers)
		self.validate_pieces()
		self.validate_fabric()
		self.set_rates()
		self.calculate_totals()

	# ------------------------------------------------------------------
	# Cutting cost: contractor (service order or piece rate) or in-house absorption
	# ------------------------------------------------------------------

	def set_rates(self) -> None:
		"""Rate per garment order: from the Service Order row when one is given, else the piece rate.
		Without a cutting party the Cutting process's absorption rate is used (in-house)."""
		from velocity_ctp.procurement.services import find_row

		self._rates: dict[str, float] = {}
		self._rows: dict[str, frappe._dict] = {}
		orders = sorted({p.garment_order for p in self.pieces if p.garment_order})
		if self.service_order:
			if not self.cutting_party:
				frappe.throw(_("A Service Order needs a cutting party (the contractor)."))
			for order in orders:
				row = find_row(self.service_order, self.cutting_party, stock.CUTTING_PROCESS, order)
				self._rows[order] = row
				self._rates[order] = flt(row.base_rate)
			rates = set(self._rates.values())
			if len(rates) == 1:
				self.piece_rate = rates.pop()
			self.service_order_item = self._rows[orders[0]].name if len(orders) == 1 else None
		else:
			self.service_order_item = None
			rate = (
				flt(self.piece_rate)
				if self.cutting_party
				else flt(frappe.db.get_value("Process", stock.CUTTING_PROCESS, "absorption_rate_per_pc"))
			)
			self._rates = {order: rate for order in orders}

	def rate_for(self, garment_order: str) -> float:
		if not hasattr(self, "_rates"):
			self.set_rates()
		return flt(self._rates.get(garment_order))

	def validate_service_quantities(self) -> None:
		from velocity_ctp.procurement.services import validate_capacity

		if not self.service_order:
			return
		good: dict[str, int] = defaultdict(int)
		for p in self.pieces:
			good[p.garment_order] += cint(p.good_qty)
		for order, qty in good.items():
			validate_capacity(
				self._rows[order], qty, (self.doctype, self.name), _("Garment Order {0}").format(order)
			)

	def absorption(self, groups: list[dict]) -> tuple[list[dict[str, float]], dict[str, float]]:
		"""Per marker group {item: good qty x rate}, and the charge per account."""
		from velocity_ctp.production.absorption import CONTRACTOR_ACCRUAL, OVERHEADS_ABSORBED

		per_group = []
		for group in groups:
			amounts: dict[str, float] = defaultdict(float)
			for p in self.pieces:
				if p.cutting_marker == group["marker"] and cint(p.good_qty) > 0:
					amounts[p.item_code] += cint(p.good_qty) * self.rate_for(p.garment_order)
			per_group.append(dict(amounts))
		total = flt(sum(sum(g.values()) for g in per_group), 2)
		account = CONTRACTOR_ACCRUAL if self.cutting_party else OVERHEADS_ABSORBED
		return per_group, ({account: total} if total > 0 else {})

	def before_submit(self) -> None:
		self.set_rates()
		self.validate_service_quantities()
		if cint(self.total_good_qty) <= 0:
			frappe.throw(_("There are no good pieces to receive. Enter the cut quantities first."))
		if flt(self.total_fabric_used) <= 0:
			frappe.throw(_("Please enter the fabric used."))
		for group in self.marker_groups():
			if group["fabric"] and not group["pieces"]:
				frappe.throw(
					_(
						"Marker {0} has fabric used but no good pieces. Its fabric cost would have no pieces to go to."
					).format(frappe.bold(group["marker"]))
				)
			if group["pieces"] and not group["fabric"]:
				frappe.throw(
					_(
						"Marker {0} has good pieces but no fabric used. Enter the fabric used for this marker."
					).format(frappe.bold(group["marker"]))
				)

	def on_submit(self) -> None:
		self.warn_on_wastage()
		groups = self.marker_groups()
		absorption, charges = self.absorption(groups)
		entry, valuation = stock.make_cut_repack(self, groups, absorption, charges)
		self.db_set("stock_entry", entry)
		self.store_fabric_cost(groups, valuation)
		self.store_absorbed_cost()
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
		for row in self.pieces:
			row.db_set(
				{
					"fabric_cost_per_pc": 0,
					"fabric_cost_amount": 0,
					"contractor_cost_amount": 0,
					"conversion_cost_amount": 0,
				},
				update_modified=False,
			)
		self.db_set("absorbed_amount", 0)

	def store_fabric_cost(self, groups: list[dict], valuation: list[dict[str, dict]]) -> None:
		"""Store the fabric value posted to each piece row (marker + variant) by the Repack."""
		by_marker = {group["marker"]: values for group, values in zip(groups, valuation, strict=True)}
		for row in self.pieces:
			posted = by_marker.get(row.cutting_marker, {}).get(row.item_code)
			if posted and cint(row.good_qty):
				fabric = flt(posted.get("fabric", posted["amount"]))
				row.db_set(
					{
						"fabric_cost_per_pc": flt(fabric / flt(posted["qty"]), 2)
						if flt(posted["qty"])
						else 0,
						"fabric_cost_amount": flt(fabric, 2),
					},
					update_modified=False,
				)

	def store_absorbed_cost(self) -> None:
		"""Cutting cost per piece row: contractor charges or in-house conversion (good pieces x rate)."""
		field = "contractor_cost_amount" if self.cutting_party else "conversion_cost_amount"
		total = 0.0
		for row in self.pieces:
			amount = flt(cint(row.good_qty) * self.rate_for(row.garment_order), 2)
			total += amount
			row.db_set(field, amount, update_modified=False)
		self.db_set("absorbed_amount", flt(total, 2))

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

		# One piece row per marker and size, one fabric row per marker: fabric cost stays with its marker.
		lines = [
			{
				"cutting_marker": marker.name,
				"garment_order": marker.garment_order,
				"colour": marker.colour,
				"size": s.size,
				"qty": cint(s.planned_pieces),
			}
			for marker in markers
			for s in sizes_by_marker[marker.name]
		]
		item_codes = self.variant_codes(lines)
		existing_pieces = {(p.cutting_marker, (p.size or "").lower()): p for p in self.pieces}
		pieces = []
		for line in lines:
			old = existing_pieces.get((line["cutting_marker"], line["size"].lower()))
			pieces.append(
				{
					"cutting_marker": line["cutting_marker"],
					"garment_order": line["garment_order"],
					"colour": line["colour"],
					"size": line["size"],
					"item_code": item_codes.get(
						ledger.piece_key(line["garment_order"], line["colour"], line["size"])
					),
					"planned_qty": line["qty"],
					"cut_qty": cint(old.cut_qty) if old else line["qty"],
					"rejected_qty": cint(old.rejected_qty) if old else 0,
				}
			)
		self.set("pieces", pieces)

		existing_fabric = {f.cutting_marker: f for f in self.fabric}
		wip = stock.get_cutting_wip(self.company or get_default_company())
		fabric = []
		for marker in markers:
			old = existing_fabric.get(marker.name)
			fabric.append(
				{
					"cutting_marker": marker.name,
					"fabric_item": marker.fabric_item,
					"batch_no": marker.batch_no,
					"required_qty": flt(marker.fabric_required, 3),
					"used_qty": flt(old.used_qty) if old else flt(marker.fabric_required, 3),
					"available_qty": stock.batch_qty(marker.batch_no, wip),
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

	def validate_row_markers(self, markers: list[frappe._dict]) -> None:
		"""Each fabric row belongs to exactly one marker of this Cut Receive (its cost goes to that marker)."""
		by_name = {m.name: m for m in markers}
		seen: dict[str, int] = {}
		for row in self.fabric:
			if not row.cutting_marker:
				frappe.throw(
					_(
						"Fabric row {0} (batch {1}) is not linked to a Cutting Marker. Each fabric row must belong to "
						"one marker; a fabric row cannot be shared by several markers."
					).format(row.idx, row.batch_no),
					title=_("Fabric Row Without Marker"),
				)
			marker = by_name.get(row.cutting_marker)
			if not marker:
				frappe.throw(
					_(
						"Fabric row {0} belongs to Cutting Marker {1}, which is not in the Markers table."
					).format(row.idx, frappe.bold(row.cutting_marker))
				)
			if (row.fabric_item, row.batch_no) != (marker.fabric_item, marker.batch_no):
				frappe.throw(
					_("Fabric row {0}: Cutting Marker {1} uses batch {2}, not {3}.").format(
						row.idx,
						frappe.bold(marker.name),
						frappe.bold(marker.batch_no),
						frappe.bold(row.batch_no),
					)
				)
			if row.cutting_marker in seen:
				frappe.throw(
					_(
						"Fabric rows {0} and {1} both belong to Cutting Marker {2}. Each marker has one fabric row; "
						"enter its total fabric used there."
					).format(seen[row.cutting_marker], row.idx, frappe.bold(row.cutting_marker)),
					title=_("Shared Fabric Row"),
				)
			seen[row.cutting_marker] = row.idx
		for row in self.pieces:
			if row.cutting_marker and row.cutting_marker not in by_name:
				frappe.throw(
					_(
						"Cut Pieces row {0} belongs to Cutting Marker {1}, which is not in the Markers table."
					).format(row.idx, frappe.bold(row.cutting_marker))
				)

	def validate_fabric(self) -> None:
		"""Rows of the same batch (different markers) are checked together against stock and the job."""
		wip = stock.get_cutting_wip(self.company)
		balances = ledger.job_fabric([self.job_map], exclude_cut_receive=self.name)[self.job_map]
		used_by_batch: dict[tuple[str, str], float] = defaultdict(float)
		for row in self.fabric:
			if flt(row.used_qty) < 0:
				frappe.throw(_("Fabric row {0}: used quantity cannot be negative.").format(row.idx))
			used_by_batch[(row.fabric_item, row.batch_no)] += flt(row.used_qty)
		available = {key: stock.batch_qty(key[1], wip) for key in used_by_batch}
		for row in self.fabric:
			row.available_qty = available[(row.fabric_item, row.batch_no)]

		for (item, batch), used in used_by_batch.items():
			label = _("Batch {0}").format(frappe.bold(batch))
			if used > available[(item, batch)] + 1e-9:
				frappe.throw(
					_("{0}: used {1} m in total, but only {2} m of this batch is in {3}.").format(
						label, flt(used, 3), available[(item, batch)], frappe.bold(wip)
					),
					title=_("Not Enough Fabric in Cutting WIP"),
				)
			values = balances.get((item, batch), {"issued": 0, "returned": 0, "used": 0})
			job_balance = ledger.fabric_balance(values)
			if used > job_balance + 1e-9:
				frappe.throw(
					_(
						"{0}: used {1} m in total, but only {2} m of this batch is issued to Job Map {3} and not yet used or returned."
					).format(label, flt(used, 3), max(job_balance, 0), frappe.bold(self.job_map)),
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
		self.contractor_amount = (
			flt(
				sum(cint(p.good_qty) * self.rate_for(p.garment_order) for p in self.pieces),
				self.precision("contractor_amount"),
			)
			if self.cutting_party
			else 0
		)

	def marker_groups(self) -> list[dict]:
		"""Per marker: its fabric (item, batch, used) and its good pieces (item, qty), in marker order.

		The Repack values each marker's fabric only into that marker's pieces.
		"""
		groups = []
		for marker_row in self.markers:
			name = marker_row.cutting_marker
			fabric = [
				{"item_code": f.fabric_item, "batch_no": f.batch_no, "qty": flt(f.used_qty)}
				for f in self.fabric
				if f.cutting_marker == name and flt(f.used_qty) > 0
			]
			pieces: dict[str, int] = defaultdict(int)
			for p in self.pieces:
				if p.cutting_marker == name and cint(p.good_qty) > 0:
					pieces[p.item_code] += cint(p.good_qty)
			groups.append(
				{
					"marker": name,
					"fabric": fabric,
					"pieces": [{"item_code": item, "qty": qty} for item, qty in pieces.items()],
				}
			)
		return groups

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
