# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Gate Outward: goods leaving the gate (no stock effect). See velocity_ctp.shipping.gate."""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from velocity_ctp.setup.install import get_default_company
from velocity_ctp.shipping import gate


class GateOutward(Document):
	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		gate.validate_outward(self)
		self.total_qty = flt(sum(flt(r.qty) for r in self.items), 3)
		if self.docstatus == 0:
			self.open_returnable_qty = sum(flt(r.qty) for r in self.items if r.returnable)

	def on_submit(self) -> None:
		gate.refresh_returned([self.name])

	def before_cancel(self) -> None:
		returned = frappe.db.sql(
			"""select gi.name from `tabGate Inward Item` gii join `tabGate Inward` gi on gi.name = gii.parent
			where gi.docstatus = 1 and gii.gate_outward = %s limit 1""",
			self.name,
		)
		if returned:
			frappe.throw(
				frappe._("Items of {0} have come back on Gate Inward {1}. Cancel that first.").format(
					frappe.bold(self.name), frappe.bold(returned[0][0])
				)
			)
