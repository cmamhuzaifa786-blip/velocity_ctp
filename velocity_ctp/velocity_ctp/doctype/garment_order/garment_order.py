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
		self.validate_colour_map()
		self.set_item_codes()
		self.calculate_totals()
		self.validate_against_cut()
		self.validate_cost_sheet()
		self.set_title()
		if self.docstatus == 0:
			self.status = "Draft"

	def validate_ship_date(self) -> None:
		if self.ship_date and self.order_date and getdate(self.ship_date) < getdate(self.order_date):
			frappe.throw(_("Ship Date cannot be before the Order Date."))

	def before_update_after_submit(self) -> None:
		self.validate_cost_sheet()
		self.validate_colour_map()
		self.ensure_variants(self.cut_colour_keys())
		before = self.get_doc_before_save()
		if before and getdate(before.ship_date) != getdate(self.ship_date):
			check_hold_role(_("Only a System Manager or Velocity Merchandiser can change the ship date."))
			if self.status == "Cancelled":
				frappe.throw(_("The ship date of a cancelled Garment Order cannot be changed."))
			self.validate_ship_date()

	def on_update_after_submit(self) -> None:
		before = self.get_doc_before_save()
		if before and getdate(before.ship_date) != getdate(self.ship_date):
			# Keep the ship date shown on Job Maps in step with the order.
			frappe.db.set_value(
				"Job Map Order",
				{"garment_order": self.name},
				"ship_date",
				self.ship_date,
				update_modified=False,
			)
			self.sync_sales_order_delivery_date()

	def sync_sales_order_delivery_date(self) -> None:
		"""Move a draft Sales Order's delivery dates to the new ship date; never touch a submitted one.

		The user has already passed the ship date permission checks on this Garment Order, so the
		draft Sales Order is updated on their behalf (ignore_permissions).
		"""
		if not self.sales_order or not frappe.db.exists("Sales Order", self.sales_order):
			return

		sales_order = frappe.get_doc("Sales Order", self.sales_order)
		if sales_order.docstatus == 1:
			frappe.msgprint(
				_("The linked Sales Order {0} is already submitted. Please review its delivery date.").format(
					frappe.bold(sales_order.name)
				),
				title=_("Sales Order Not Updated"),
				indicator="orange",
			)
			return
		if sales_order.docstatus != 0:
			return

		new_date = getdate(self.ship_date)
		if new_date < getdate(sales_order.transaction_date):
			frappe.throw(
				_(
					"The new ship date {0} is before the date of the linked draft Sales Order {1} ({2}). "
					"Please choose a later ship date, or change the Sales Order date first."
				).format(
					frappe.format(new_date, "Date"),
					frappe.bold(sales_order.name),
					frappe.format(sales_order.transaction_date, "Date"),
				),
				title=_("Ship Date Before Sales Order Date"),
			)

		old_date = sales_order.delivery_date
		sales_order.delivery_date = new_date
		for item in sales_order.items:
			item.delivery_date = new_date
		sales_order.flags.ignore_permissions = True
		try:
			sales_order.save()
		except frappe.PermissionError:
			# ERPNext's Sales Order validation reads Item and other records with permission checks.
			if frappe.message_log:
				frappe.message_log.pop()  # drop the raw permission message
			frappe.throw(
				_(
					"The linked draft Sales Order {0} could not be updated to the new ship date because "
					"you do not have access to the records it uses (such as Item). The ship date was not "
					"changed. Please ask your administrator to give you a standard ERPNext role such as "
					"Sales User, or ask a sales user to change the ship date."
				).format(frappe.bold(sales_order.name)),
				frappe.PermissionError,
				title=_("Sales Order Not Updated"),
			)
		sales_order.add_comment(
			"Comment",
			_(
				"Delivery date changed from {0} to {1} because the ship date changed on Garment Order {2}."
			).format(frappe.format(old_date, "Date"), frappe.format(new_date, "Date"), self.name),
		)

	def on_submit(self) -> None:
		self.db_set("status", "Open")

	def validate_against_cut(self) -> None:
		"""Colour/size quantities cannot be reduced below what has already been cut."""
		if self.is_new():
			return
		from velocity_ctp.cutting.ledger import cut_quantities, piece_key

		before = self.get_doc_before_save()
		cut = cut_quantities([self.name])
		if not cut or not before:
			return
		old = {piece_key(self.name, r.colour, r.size): cint(r.cutting_qty) for r in before.items}
		lines = {piece_key(self.name, r.colour, r.size): cint(r.cutting_qty) for r in self.items}
		for key, values in cut.items():
			(_order, colour, size), new_qty = key, lines.get(key, 0)
			# Only a reduction counts: a cut within the over-cut tolerance may exceed the line already.
			if values["cut"] and new_qty < old.get(key, 0) and new_qty < values["cut"]:
				frappe.throw(
					_(
						"{0} / {1}: {2} pieces have already been cut, so the quantity cannot be reduced below that."
					).format(frappe.bold(colour), frappe.bold(size), values["cut"]),
					title=_("Already Cut"),
				)

	def before_cancel(self) -> None:
		from velocity_ctp.cutting.ledger import order_cut_totals
		from velocity_ctp.velocity_ctp.doctype.job_map.job_map import get_active_job_maps

		cut = order_cut_totals([self.name]).get(self.name, 0)
		if cut:
			frappe.throw(
				_("Garment Order {0} cannot be cancelled: {1} pieces have already been cut.").format(
					frappe.bold(self.name), cut
				),
				title=_("Already Cut"),
			)

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

	def validate_cost_sheet(self) -> None:
		"""A newly selected Cost Sheet must be Approved and for the same customer and style."""
		if not self.cost_sheet:
			return
		before = self.get_doc_before_save()
		if before and before.cost_sheet == self.cost_sheet:
			return  # an existing link may since have been superseded; the form offers to switch
		cs = frappe.db.get_value("Cost Sheet", self.cost_sheet, ["status", "customer", "style"], as_dict=True)
		if not cs or cs.status != "Approved":
			frappe.throw(
				_("Cost Sheet {0} is {1}. Only an Approved Cost Sheet can be linked.").format(
					frappe.bold(self.cost_sheet), _(cs.status) if cs else _("missing")
				)
			)
		if (cs.customer, cs.style) != (self.customer, self.style):
			frappe.throw(
				_("Cost Sheet {0} is for {1} / {2}, not {3} / {4}.").format(
					frappe.bold(self.cost_sheet), cs.customer, cs.style, self.customer, self.style
				)
			)

	def before_submit(self) -> None:
		from velocity_ctp.cutting.settings import get_settings

		if self.order_type == "Bulk" and not self.cost_sheet and cint(get_settings().require_cost_sheet):
			frappe.throw(
				_(
					"A Bulk Garment Order needs an approved Cost Sheet (Velocity Settings: Require Cost Sheet)."
				),
				title=_("Cost Sheet Required"),
			)

	def set_title(self) -> None:
		"""Form title: order number first, then the customer ("STJ-0001/26 · Test Buyer")."""
		customer = frappe.db.get_value("Customer", self.customer, "customer_name") or self.customer
		self.title = f"{self.name} · {customer}" if customer else self.name

	def validate_dates(self) -> None:
		self.validate_ship_date()
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

	def validate_colour_map(self) -> None:
		"""Cut Colours: each order colour once, a colour of the order; the cut colour a Style colour.
		A mapping cannot change once pieces of that order colour have been cut."""
		style = self.get_style_doc()
		style_colours = {c.colour.lower(): c.colour for c in style.colours}
		ordered = {row.colour.lower(): row.colour for row in self.items if row.colour}
		seen, rows = set(), []
		for row in self.get("colour_map") or []:
			order_colour = (row.order_colour or "").strip()
			cut_colour = (row.cut_colour or "").strip()
			label = _("Cut Colours row {0}").format(row.idx)
			if order_colour.lower() not in ordered:
				frappe.throw(
					_("{0}: {1} is not a colour of this order ({2}).").format(
						label, frappe.bold(order_colour), ", ".join(sorted(ordered.values()))
					)
				)
			if cut_colour.lower() not in style_colours:
				frappe.throw(
					_("{0}: cut colour {1} is not a colour of Style {2} ({3}).").format(
						label, frappe.bold(cut_colour), self.style, ", ".join(style_colours.values())
					)
				)
			if order_colour.lower() in seen:
				frappe.throw(_("{0}: {1} is mapped more than once.").format(label, frappe.bold(order_colour)))
			seen.add(order_colour.lower())
			row.order_colour, row.cut_colour = (
				ordered[order_colour.lower()],
				style_colours[cut_colour.lower()],
			)
			if row.cut_colour.lower() != row.order_colour.lower():
				rows.append(row)
		self.set("colour_map", rows)
		self.check_colour_map_after_cutting()

	def check_colour_map_after_cutting(self) -> None:
		before = self.get_doc_before_save()
		if not before or self.is_new():
			return
		old = {(r.order_colour or "").lower(): r.cut_colour for r in before.get("colour_map") or []}
		new = {(r.order_colour or "").lower(): r.cut_colour for r in self.get("colour_map") or []}
		names = {row.colour.lower(): row.colour for row in self.items if row.colour}
		changed = {c for c in set(old) | set(new) if (old.get(c) or "").lower() != (new.get(c) or "").lower()}
		if not changed:
			return
		from velocity_ctp.cutting.ledger import cut_quantities

		cut = {colour for (_order, colour, _size), v in cut_quantities([self.name]).items() if v["cut"]}
		locked = sorted(c for c in changed if c in cut)
		if locked:
			frappe.throw(
				_(
					"The cut colour of {0} cannot change: pieces of this order colour have already been cut."
				).format(", ".join(frappe.bold(names.get(c, c)) for c in locked)),
				title=_("Already Cut"),
			)

	def cut_colour_keys(self) -> list[tuple[str, str]]:
		"""(cut colour, size) in lower case for every mapped order colour."""
		cut_of = {(r.order_colour or "").lower(): r.cut_colour for r in self.get("colour_map") or []}
		return [
			(cut_of[row.colour.lower()].lower(), row.size.lower())
			for row in self.items
			if row.colour and row.colour.lower() in cut_of
		]

	def ensure_variants(self, keys: list[tuple[str, str]]):
		"""Create missing Style variants for the given (colour, size) keys; returns the variant map."""
		style = self.get_style_doc()
		variant_map = style.get_variant_map()
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
		return variant_map

	def set_item_codes(self) -> None:
		"""Link every row to the Style variant for its colour and size, creating variants if needed
		(also for the cut colours of mapped order colours)."""
		keys = [(row.colour.lower(), row.size.lower()) for row in self.items]
		variant_map = self.ensure_variants(keys + self.cut_colour_keys())

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

		if getdate(self.ship_date) < getdate(nowdate()):
			frappe.throw(
				_(
					"The ship date has passed. Please update the ship date on this Garment Order "
					"before creating a Sales Order."
				),
				title=_("Ship Date Has Passed"),
			)
		ship_date = self.ship_date
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


def check_hold_role(message: str | None = None) -> None:
	if not set(HOLD_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			message
			or _("Only a System Manager or Velocity Merchandiser can put orders on hold or resume them."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["POST"])
def update_ship_date(garment_order: str, ship_date: str, reason: str | None = None) -> str:
	"""Change the ship date of a submitted Garment Order (recorded in the timeline)."""
	check_hold_role(_("Only a System Manager or Velocity Merchandiser can change the ship date."))
	doc = frappe.get_doc("Garment Order", garment_order)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Use this option on submitted Garment Orders. Edit the Ship Date field on drafts."))
	if not ship_date:
		frappe.throw(_("Please enter the new ship date."))
	if getdate(ship_date) == getdate(doc.ship_date):
		frappe.throw(_("The new ship date is the same as the current one."))

	old = doc.ship_date
	doc.ship_date = ship_date
	doc.save()
	if reason and reason.strip():
		doc.add_comment(
			"Comment",
			_("Ship date changed from {0} to {1}. Reason: {2}").format(
				frappe.format(old, "Date"),
				frappe.format(doc.ship_date, "Date"),
				frappe.utils.escape_html(reason.strip()),
			),
		)
	return str(doc.ship_date)


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
