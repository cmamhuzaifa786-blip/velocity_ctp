# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WashType(Document):
	def validate(self) -> None:
		self.wash_type = (self.wash_type or "").strip()
