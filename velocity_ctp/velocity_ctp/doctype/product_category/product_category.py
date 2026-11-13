# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ProductCategory(Document):
	def validate(self) -> None:
		self.category_name = (self.category_name or "").strip()
