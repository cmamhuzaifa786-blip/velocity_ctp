# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Process(Document):
	def validate(self) -> None:
		self.process_name = (self.process_name or "").strip()
		self.validate_sequence()
		self.validate_next_process()
		self.validate_wip_warehouse()

	def validate_sequence(self) -> None:
		if not self.sequence or self.sequence < 1:
			frappe.throw(_("Sequence must be a whole number greater than zero."))

		if not self.is_active:
			return

		duplicate = frappe.db.get_value(
			"Process",
			{"sequence": self.sequence, "is_active": 1, "name": ("!=", self.name or "")},
			"name",
		)
		if duplicate:
			frappe.throw(
				_(
					"Sequence {0} is already used by the active process {1}. Please choose a different sequence."
				).format(self.sequence, frappe.bold(duplicate))
			)

	def validate_next_process(self) -> None:
		if self.next_process and self.next_process in (self.name, self.process_name):
			frappe.throw(_("Next Process cannot be the same as this process."))

	def validate_wip_warehouse(self) -> None:
		if self.wip_warehouse and frappe.db.get_value("Warehouse", self.wip_warehouse, "is_group"):
			frappe.throw(
				_(
					"WIP Warehouse {0} is a group warehouse. Please select a warehouse that is not a group."
				).format(frappe.bold(self.wip_warehouse))
			)
