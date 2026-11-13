# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from velocity_ctp.item_attributes import SIZE_ATTRIBUTE, ensure_attribute_values, size_abbreviation


class SizeSet(Document):
	def validate(self) -> None:
		self.size_set_name = (self.size_set_name or "").strip()
		self.validate_sizes()

	def validate_sizes(self) -> None:
		if not self.sizes:
			frappe.throw(_("Please add at least one size to the Size Set."))

		seen: set[str] = set()
		for row in self.sizes:
			row.size = (row.size or "").strip()
			if not row.size:
				frappe.throw(_("Row {0}: Size is required.").format(row.idx))
			if row.size.lower() in seen:
				frappe.throw(
					_("Row {0}: Size {1} is entered more than once.").format(row.idx, frappe.bold(row.size))
				)
			seen.add(row.size.lower())
			if not row.sequence:
				row.sequence = row.idx

	def on_update(self) -> None:
		# Every size must exist on the Item Attribute "Size" so that item variants can use it.
		ensure_attribute_values(SIZE_ATTRIBUTE, [row.size for row in self.sizes], size_abbreviation)

	def get_ordered_sizes(self) -> list[str]:
		return [row.size for row in sorted(self.sizes, key=lambda r: (r.sequence or 0, r.idx))]
