# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Gate Inward: goods entering the gate (no stock effect), including returnable items coming back."""

from __future__ import annotations

from frappe.model.document import Document
from frappe.utils import flt

from velocity_ctp.setup.install import get_default_company
from velocity_ctp.shipping import gate


class GateInward(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		gate.validate_inward(self)
		self.total_qty = flt(sum(flt(r.qty) for r in self.items), 3)

	def on_submit(self) -> None:
		gate.refresh_returned([r.gate_outward for r in self.items])

	def on_cancel(self) -> None:
		gate.refresh_returned([r.gate_outward for r in self.items])
