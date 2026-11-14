# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class Bundle(Document):
	"""A size-wise group of cut pieces. Created only by Cut Receive (see velocity_ctp.cutting.bundles)."""

	def before_insert(self) -> None:
		if not self.flags.ignore_permissions:
			frappe.throw(_("Bundles are created automatically when a Cut Receive is submitted."))
