# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

from velocity_ctp.setup.install import get_default_company

HOLD_ROLES = ("System Manager", "Velocity Merchandiser")
CLOSED_STATUSES = ("Completed", "Cancelled")


def excess_for(order_qty: int, excess_percent: float) -> int:
	"""Excess pieces for a row, rounded half up (2.5 -> 3)."""
	return math.floor(cint(order_qty) * flt(excess_percent) / 100 + 0.5)


class GarmentOrder(Document):
	def validate(self) -> None:
		self.set_defaults()
		self.validate_dates()
		self.validate_style()
		self.validate_items()
		self.set_item_codes()
		self.calculate_totals()
		if self.docstatus == 0:
			self.status = "Draft"

	def on_submit(self) -> None:
		self.db_set("status", "Open")

	def before_cancel(self) -> None:
		from velocity_ctp.velocity_ctp.doctype.job_map.job_map import get_active_job_maps

		job_map = get_active_job_maps([self.name]).get(self.name)
		if job_map:
			frappe.throw(
				_(
					"Garment Order {0} is on Job Map {1}. Remove it from the Job Map or close the Job Map first."
				).format(frappe.bold(self.name), frappe.bold(job_map))
			)

	def on_cancel(self) -> None:
		self.db_set("status", "Cancelled")

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def set_defaults(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if not self.currency:
			self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		if not self.merchandiser:
			self.merchandiser = frappe.session.user

	def validate_dates(self) -> None:
		if self.ship_date and self.order_date and getdate(self.ship_date) < getdate(self.order_date):
			frappe.throw(_("Ship Date cannot be before the Order Date."))
		if flt(self.excess_percent) < 0 or flt(self.excess_percent) > 100:
			frappe.throw(_("Excess % must be between 0 and 100."))

	def validate_style(self) -> None:
		style_customer = frappe.db.get_value("Style", self.style, "customer")
		if style_customer and style_customer != self.customer:
			frappe.throw(
				_("Style {0} belongs to customer {1}, not {2}.").format(
					frappe.bold(self.style), frappe.bold(style_customer), frappe.bold(self.customer)
				)
			)

	def get_style_doc(self):
		if not getattr(self, "_style_doc", None):
			self._style_doc = frappe.get_doc("Style", self.style)
		return self._style_doc

	def validate_items(self) -> None:
		if not self.items:
			frappe.throw(_("Please enter quantities for at least one colour and size."))

		style = self.get_style_doc()
		colours = {row.colour.lower(): row.colour for row in style.colours}
		sizes = {size.lower(): size for size in style.get_sizes()}

		seen: set[tuple[str, str]] = set()
		for row in self.items:
			colour = (row.colour or "").strip()
			size = (row.size or "").strip()
			if colour.lower() not in colours:
				frappe.throw(
					_("Row {0}: Colour {1} is not a colour of Style {2}.").format(
						row.idx, frappe.bold(colour), frappe.bold(self.style)
					)
				)
			if size.lower() not in sizes:
				frappe.throw(
					_("Row {0}: Size {1} is not in Size Set {2}.").format(
						row.idx, frappe.bold(size), frappe.bold(style.size_set)
					)
				)
			row.colour, row.size = colours[colour.lower()], sizes[size.lower()]

			key = (row.colour.lower(), row.size.lower())
			if key in seen:
				frappe.throw(
					_("Row {0}: Colour {1} and size {2} are entered more than once.").format(
						row.idx, frappe.bold(row.colour), frappe.bold(row.size)
					)
				)
			seen.add(key)

			if cint(row.order_qty) <= 0:
				frappe.throw(
					_("Row {0}: Order Qty for {1} / {2} must be greater than zero.").format(
						row.idx, row.colour, row.size
					)
				)

	def set_item_codes(self) -> None:
		"""Link every row to the Style variant for its colour and size, creating variants if needed."""
		style = self.get_style_doc()
		variant_map = style.get_variant_map()
		keys = [(row.colour.lower(), row.size.lower()) for row in self.items]

		if any(key not in variant_map for key in keys):
			if not frappe.has_permission("Style", "write", style):
				frappe.throw(
					_(
						"Some colour and size combinations of Style {0} have no item variant yet. "
						"Creating them needs write permission on the Style; please ask a merchandiser "
						"to run Create Item Variants on the Style."
					).format(frappe.bold(style.name)),
					frappe.PermissionError,
				)
			style.create_item_variants()
			style.reload()
			variant_map = style.get_variant_map()

		for row, key in zip(self.items, keys, strict=True):
			row.item_code = variant_map.get(key)
			if not row.item_code:
				frappe.throw(
					_("Row {0}: No item variant found for {1} / {2}.").format(row.idx, row.colour, row.size)
				)

	def calculate_totals(self) -> None:
		totals = {"order": 0, "excess": 0, "cutting": 0, "amount": 0.0}
		for row in self.items:
			row.order_qty = cint(row.order_qty)
			row.excess_qty = excess_for(row.order_qty, self.excess_percent)
			row.cutting_qty = row.order_qty + row.excess_qty
			row.amount = flt(row.order_qty * flt(row.rate), row.precision("amount"))
			totals["order"] += row.order_qty
			totals["excess"] += row.excess_qty
			totals["cutting"] += row.cutting_qty
			totals["amount"] += row.amount

		self.total_order_qty = totals["order"]
		self.total_excess_qty = totals["excess"]
		self.total_cutting_qty = totals["cutting"]
		self.total_amount = flt(totals["amount"], self.precision("total_amount"))

	# ------------------------------------------------------------------
	# Actions
	# ------------------------------------------------------------------

	def get_resume_status(self) -> str:
		from velocity_ctp.velocity_ctp.doctype.job_map.job_map import get_active_job_maps

		job_map = get_active_job_maps([self.name]).get(self.name)
		if job_map and frappe.db.get_value("Job Map", job_map, "status") == "Ready to Cut":
			return "In Production"
		return "Open"

	def set_hold(self, hold: bool) -> None:
		if self.docstatus != 1:
			frappe.throw(_("Only submitted Garment Orders can be put on hold or resumed."))
		if hold:
			if self.status in CLOSED_STATUSES or self.status == "On Hold":
				frappe.throw(_("Garment Order with status {0} cannot be put on hold.").format(self.status))
			self.db_set("status", "On Hold")
		else:
			if self.status != "On Hold":
				frappe.throw(_("Garment Order is not on hold."))
			self.db_set("status", self.get_resume_status())
		self.add_comment("Info", _("Status changed to {0}").format(self.status))

	def make_sales_order(self) -> str:
		if self.docstatus != 1:
			frappe.throw(_("Please submit the Garment Order before creating a Sales Order."))
		if self.status == "Cancelled":
			frappe.throw(_("A Sales Order cannot be created for a cancelled Garment Order."))
		if self.sales_order and frappe.db.exists("Sales Order", self.sales_order):
			frappe.throw(_("Sales Order {0} already exists for this Garment Order.").format(self.sales_order))
		if not frappe.has_permission("Sales Order", "create"):
			frappe.throw(_("You do not have permission to create a Sales Order."), frappe.PermissionError)

		ship_date = max(getdate(self.ship_date), getdate(nowdate()))
		sales_order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": self.customer,
				"currency": self.currency,
				"transaction_date": nowdate(),
				"delivery_date": ship_date,
				"po_no": self.buyer_po_no,
				"garment_order": self.name,
				"items": [
					{
						"item_code": row.item_code,
						"qty": row.order_qty,
						"rate": row.rate,
						"delivery_date": ship_date,
					}
					for row in self.items
				],
			}
		)
		sales_order.insert()
		self.db_set("sales_order", sales_order.name)
		return sales_order.name


def check_hold_role() -> None:
	if not set(HOLD_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Only a System Manager or Velocity Merchandiser can put orders on hold or resume them."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["POST"])
def set_hold(garment_order: str, hold: int | str) -> str:
	check_hold_role()
	doc = frappe.get_doc("Garment Order", garment_order)
	doc.check_permission("write")
	doc.set_hold(bool(cint(hold)))
	return doc.status


@frappe.whitelist(methods=["POST"])
def make_sales_order(garment_order: str) -> str:
	doc = frappe.get_doc("Garment Order", garment_order)
	doc.check_permission("write")
	return doc.make_sales_order()


def clear_sales_order_link(doc, method: str | None = None) -> None:
	"""Sales Order hook: when a linked Sales Order is cancelled or deleted, free the Garment Order."""
	garment_order = doc.get("garment_order")
	if garment_order and frappe.db.get_value("Garment Order", garment_order, "sales_order") == doc.name:
		frappe.db.set_value("Garment Order", garment_order, "sales_order", None)
