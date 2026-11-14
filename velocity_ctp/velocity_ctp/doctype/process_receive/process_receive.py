# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from velocity_ctp.production import flow, stock
from velocity_ctp.setup.install import get_default_company


class ProcessReceive(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		self._process_info = flow.validate_process_party(self.production_process, self.party)
		flow.posting_date_check(self.posting_date, _("Posting Date"))
		self.validate_bundles()
		self.calculate_totals()

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
				reason = flow.receive_block(bundle, self.production_process, self.party)
				if reason:
					frappe.throw(reason, title=_("Bundle Cannot Be Received"))
				row.process_issue = bundle.open_issue
				row.issued_qty = flow.outstanding_qty(bundle)
				row.from_warehouse = (
					bundle.repair_warehouse if cint(bundle.pending_repair_qty) else bundle.current_warehouse
				)
				row.item_code = bundle.item_code
				row.piece_rate = flt(frappe.db.get_value("Process Issue", bundle.open_issue, "piece_rate"))
			row.garment_order, row.colour, row.size = bundle.garment_order, bundle.colour, bundle.size
			self.validate_quantities(row)
			self.validate_colour(row, bundle)

	def validate_quantities(self, row) -> None:
		label = _("Bundle {0}").format(row.bundle)
		fresh, rejected, repair = cint(row.fresh_qty), cint(row.rejected_qty), cint(row.repair_qty)
		if min(fresh, rejected, repair) < 0:
			frappe.throw(_("{0}: quantities cannot be negative.").format(label))
		if fresh + rejected + repair != cint(row.issued_qty):
			frappe.throw(
				_("{0}: fresh {1} + rejected {2} + repair {3} = {4}, but {5} pieces are open on {6}.").format(
					label,
					fresh,
					rejected,
					repair,
					fresh + rejected + repair,
					row.issued_qty,
					row.process_issue,
				),
				title=_("Quantities Do Not Add Up"),
			)
		if rejected and not self._process_info.allow_rejection:
			frappe.throw(
				_("{0}: {1} does not allow rejection. Set the rejected quantity to zero.").format(
					label, self.production_process
				)
			)

	def validate_colour(self, row, bundle) -> None:
		row.new_item_code = None
		if not row.to_colour or row.to_colour == bundle.colour:
			row.to_colour = None
			return
		label = _("Bundle {0}").format(row.bundle)
		if not self._process_info.allow_colour_change:
			frappe.throw(_("{0}: {1} does not allow a colour change.").format(label, self.production_process))
		if cint(row.repair_qty):
			frappe.throw(
				_(
					"{0}: the colour can only change when no pieces are left for repair (all good pieces change colour together)."
				).format(label)
			)
		style = frappe.get_doc("Style", bundle.style)
		colours = {c.colour.lower(): c.colour for c in style.colours}
		if row.to_colour.lower() not in colours:
			frappe.throw(
				_("{0}: colour {1} is not a colour of Style {2}. Style colours: {3}.").format(
					label, frappe.bold(row.to_colour), bundle.style, ", ".join(colours.values())
				)
			)
		row.to_colour = colours[row.to_colour.lower()]
		variant = style.get_variant_map().get((row.to_colour.lower(), (bundle.size or "").lower()))
		if not variant:
			frappe.throw(
				_(
					"{0}: no item variant exists for {1} / {2} of Style {3}. Run Create Item Variants on the Style."
				).format(label, row.to_colour, bundle.size, bundle.style)
			)
		row.new_item_code = variant

	def calculate_totals(self) -> None:
		self.total_issued = sum(cint(r.issued_qty) for r in self.bundles)
		self.total_fresh = sum(cint(r.fresh_qty) for r in self.bundles)
		self.total_rejected = sum(cint(r.rejected_qty) for r in self.bundles)
		self.total_repair = sum(cint(r.repair_qty) for r in self.bundles)
		received = self.total_fresh + self.total_rejected
		self.rejection_percent = flt(self.total_rejected / received * 100, 2) if received else 0
		self.contractor_amount = flt(
			sum(cint(r.fresh_qty) * flt(r.piece_rate) for r in self.bundles),
			self.precision("contractor_amount"),
		)

	def before_submit(self) -> None:
		for row in self.bundles:
			bundle = frappe.get_doc("Bundle", row.bundle)
			reason = flow.receive_block(bundle, self.production_process, self.party)
			if (
				reason
				or row.process_issue != bundle.open_issue
				or cint(row.issued_qty) != flow.outstanding_qty(bundle)
			):
				frappe.throw(
					reason
					or _("Bundle {0} changed since this document was saved. Please save it again.").format(
						row.bundle
					),
					title=_("Bundle Cannot Be Received"),
				)

	def on_submit(self) -> None:
		wip = frappe.db.get_value("Process", self.production_process, "wip_warehouse")
		rejection = stock.get_rejection_store(self.company) if self.total_rejected else None
		transfers, changes = [], []
		for row in self.bundles:
			bundle = frappe.get_doc("Bundle", row.bundle)
			flow.snapshot(row, bundle)
			row.db_update()
			transfers.append(
				{
					"item_code": row.item_code,
					"qty": row.fresh_qty,
					"s_warehouse": row.from_warehouse,
					"t_warehouse": wip,
				}
			)
			if cint(row.rejected_qty):
				transfers.append(
					{
						"item_code": row.item_code,
						"qty": row.rejected_qty,
						"s_warehouse": row.from_warehouse,
						"t_warehouse": rejection,
					}
				)
			if row.new_item_code:
				# Every good piece of the bundle is in the process WIP after this receive.
				good = cint(bundle.qty) - cint(row.rejected_qty)
				changes.append(
					{"from_item": row.item_code, "to_item": row.new_item_code, "qty": good, "warehouse": wip}
				)
			flow.apply_receive(bundle, self, row, wip)

		remarks = _("Process Receive {0}: {1}{2}").format(
			self.name, self.production_process, f" ({self.party})" if self.party else ""
		)
		self.db_set("stock_entry", stock.make_transfer(self.company, self.posting_date, remarks, transfers))
		self.db_set(
			"repack_entry",
			stock.make_colour_repack(
				self.company, self.posting_date, _("Colour change on {0}").format(self.name), changes
			),
		)

	def before_cancel(self) -> None:
		used = flow.later_use([r.bundle for r in self.bundles], self.doctype, self.name, self.creation)
		if used:
			frappe.throw(
				_("Process Receive {0} cannot be cancelled: {1}. Cancel that first.").format(
					frappe.bold(self.name), used
				),
				title=_("Cannot Cancel"),
			)

	def on_cancel(self) -> None:
		from velocity_ctp.cutting.stock import cancel_stock_entry

		cancel_stock_entry(self.repack_entry)
		cancel_stock_entry(self.stock_entry)
		for row in self.bundles:
			flow.restore(frappe.get_doc("Bundle", row.bundle), row, self.doctype, self.name)


@frappe.whitelist()
def get_colour_options(bundles: list | str) -> dict:
	"""{bundle: [style colours]} for the To Colour picker."""
	frappe.has_permission("Process Receive", "read", throw=True)
	bundles = frappe.parse_json(bundles) if isinstance(bundles, str) else bundles
	styles = dict(
		frappe.get_all(
			"Bundle", filters={"name": ("in", bundles or [""])}, fields=["name", "style"], as_list=True
		)
	)
	colours = {}
	for style in set(styles.values()):
		colours[style] = frappe.get_all(
			"Style Colour", filters={"parent": style, "parenttype": "Style"}, pluck="colour"
		)
	return {b: colours.get(s, []) for b, s in styles.items()}
