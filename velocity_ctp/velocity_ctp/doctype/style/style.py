# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from erpnext.controllers.item_variant import create_variant
from frappe import _
from frappe.model.document import Document

from velocity_ctp.item_attributes import (
	COLOUR_ATTRIBUTE,
	SIZE_ATTRIBUTE,
	colour_abbreviation,
	ensure_attribute_values,
	size_abbreviation,
)

FINISHED_GOODS_GROUP = "Finished Goods"
STOCK_UOM_PREFERENCE = ("Pcs", "Nos")


class Style(Document):
	def onload(self) -> None:
		self.set_onload("variants_complete", bool(self.template_item) and not self.get_missing_combinations())

	def validate(self) -> None:
		self.style_no = (self.style_no or "").strip()
		self.validate_colours()
		self.validate_active_masters()

	def validate_colours(self) -> None:
		if not self.colours:
			frappe.throw(_("Please add at least one colour to the Style."))

		seen: set[str] = set()
		for row in self.colours:
			row.colour = (row.colour or "").strip()
			if not row.colour:
				frappe.throw(_("Row {0}: Colour is required.").format(row.idx))
			if row.colour.lower() in seen:
				frappe.throw(
					_("Row {0}: Colour {1} is entered more than once.").format(
						row.idx, frappe.bold(row.colour)
					)
				)
			seen.add(row.colour.lower())

	def validate_active_masters(self) -> None:
		if self.size_set and not frappe.db.get_value("Size Set", self.size_set, "is_active"):
			frappe.throw(_("Size Set {0} is not active.").format(frappe.bold(self.size_set)))
		if self.product_category and not frappe.db.get_value(
			"Product Category", self.product_category, "is_active"
		):
			frappe.throw(_("Product Category {0} is not active.").format(frappe.bold(self.product_category)))

	# ------------------------------------------------------------------
	# Item variants
	# ------------------------------------------------------------------

	def get_sizes(self) -> list[str]:
		return frappe.get_doc("Size Set", self.size_set).get_ordered_sizes()

	def get_required_combinations(self) -> list[tuple[str, str]]:
		sizes = self.get_sizes()
		return [(row.colour, size) for row in self.colours for size in sizes]

	def get_variant_map(self, template: str | None = None) -> dict[tuple[str, str], str]:
		"""Map of (colour, size) in lower case to the variant Item code of the template."""
		template = template or self.template_item
		if not template:
			return {}
		rows = frappe.db.sql(
			"""
			select va.parent, va.attribute, va.attribute_value
			from `tabItem Variant Attribute` va
			inner join `tabItem` i on i.name = va.parent
			where i.variant_of = %s and va.attribute in (%s, %s)
			""",
			(template, COLOUR_ATTRIBUTE, SIZE_ATTRIBUTE),
			as_dict=True,
		)
		by_item: dict[str, dict[str, str]] = {}
		for row in rows:
			by_item.setdefault(row.parent, {})[row.attribute] = (row.attribute_value or "").lower()

		return {
			(attrs[COLOUR_ATTRIBUTE], attrs[SIZE_ATTRIBUTE]): item
			for item, attrs in by_item.items()
			if COLOUR_ATTRIBUTE in attrs and SIZE_ATTRIBUTE in attrs
		}

	def get_existing_combinations(self, template: str) -> set[tuple[str, str]]:
		"""Colour/size pairs (lower case) that already have a variant of the template."""
		return set(self.get_variant_map(template))

	def get_missing_combinations(self) -> list[tuple[str, str]]:
		if not self.template_item or not self.size_set:
			return self.get_required_combinations() if self.size_set else []
		existing = self.get_existing_combinations(self.template_item)
		return [
			(colour, size)
			for colour, size in self.get_required_combinations()
			if (colour.lower(), size.lower()) not in existing
		]

	def get_or_create_template_item(self) -> str:
		if frappe.db.exists("Item", self.style_no):
			item = frappe.get_doc("Item", self.style_no)
			if not item.has_variants:
				frappe.throw(
					_(
						"Item {0} already exists but is not a template item (Has Variants is not set). "
						"Please rename that Item or enable Has Variants on it before creating variants."
					).format(frappe.bold(self.style_no))
				)
			current = {row.attribute for row in item.attributes}
			missing = [a for a in (COLOUR_ATTRIBUTE, SIZE_ATTRIBUTE) if a not in current]
			if missing:
				for attribute in missing:
					item.append("attributes", {"attribute": attribute})
				item.save()
			return item.name

		if not frappe.db.exists("Item Group", FINISHED_GOODS_GROUP):
			frappe.throw(
				_("Item Group {0} does not exist. Please run the Velocity CTP setup first.").format(
					frappe.bold(FINISHED_GOODS_GROUP)
				)
			)

		stock_uom = next((uom for uom in STOCK_UOM_PREFERENCE if frappe.db.exists("UOM", uom)), None)
		if not stock_uom:
			frappe.throw(_("Neither UOM Pcs nor UOM Nos exists. Please create one of them first."))

		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": self.style_no,
				"item_name": self.style_name or self.style_no,
				"item_group": FINISHED_GOODS_GROUP,
				"stock_uom": stock_uom,
				"is_stock_item": 1,
				"has_variants": 1,
				"variant_based_on": "Item Attribute",
				"description": self.description or self.style_name or self.style_no,
				"image": self.image,
				"attributes": [{"attribute": COLOUR_ATTRIBUTE}, {"attribute": SIZE_ATTRIBUTE}],
			}
		)
		item.insert()
		return item.name

	def create_item_variants(self) -> dict:
		if self.is_new():
			frappe.throw(_("Please save the Style before creating item variants."))
		if not frappe.has_permission("Item", "create"):
			frappe.throw(
				_("You do not have permission to create Items, so item variants cannot be created."),
				frappe.PermissionError,
			)
		self.validate_colours()
		self.validate_active_masters()

		sizes = self.get_sizes()
		if not sizes:
			frappe.throw(_("Size Set {0} has no sizes.").format(frappe.bold(self.size_set)))

		colour_values = ensure_attribute_values(
			COLOUR_ATTRIBUTE, [row.colour for row in self.colours], colour_abbreviation
		)
		size_values = ensure_attribute_values(SIZE_ATTRIBUTE, sizes, size_abbreviation)

		template = self.get_or_create_template_item()
		existing = self.get_existing_combinations(template)

		created: list[str] = []
		for row in self.colours:
			for size in sizes:
				key = (row.colour.lower(), size.lower())
				if key in existing:
					continue
				variant = create_variant(
					template,
					{
						COLOUR_ATTRIBUTE: colour_values[row.colour.lower()],
						SIZE_ATTRIBUTE: size_values[size.lower()],
					},
				)
				variant.insert()
				existing.add(key)
				created.append(variant.name)

		if self.template_item != template:
			self.db_set("template_item", template)

		total = len(self.colours) * len(sizes)
		if created:
			message = _(
				"{0} item variant(s) created for template {1}. {2} of {3} variants now exist."
			).format(len(created), frappe.bold(template), total, total)
		else:
			message = _("All {0} item variants already exist for template {1}. Nothing was created.").format(
				total, frappe.bold(template)
			)
		frappe.msgprint(message, title=_("Item Variants"), indicator="green")

		return {"template_item": template, "created": created, "total": total}


@frappe.whitelist(methods=["POST"])
def create_item_variants(style: str) -> dict:
	"""Create the template Item and all colour x size variants for a Style (safe to run again)."""
	doc = frappe.get_doc("Style", style)
	doc.check_permission("write")
	return doc.create_item_variants()


@frappe.whitelist()
def get_matrix_layout(style: str) -> dict:
	"""Colours and sizes (in sequence order) used to draw the quantity matrix for a Style."""
	doc = frappe.get_doc("Style", style)
	doc.check_permission("read")
	return {
		"colours": [row.colour for row in doc.colours],
		"sizes": doc.get_sizes() if doc.size_set else [],
		"customer": doc.customer,
	}
