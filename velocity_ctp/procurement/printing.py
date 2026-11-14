"""Jinja helpers for the Velocity Purchase Order print."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, get_fullname

from velocity_ctp.procurement.common import APPROVED


def second_approval_limit() -> float:
	from velocity_ctp.cutting.settings import get_settings

	return flt(get_settings().po_second_approval_limit)


def get_po_approval(doc) -> dict:
	"""Approval block of the PO print: whether it is approved, and who approved it when."""
	approved = doc.docstatus == 1 and (doc.get("workflow_state") in (None, "", APPROVED))
	needs_second = flt(doc.base_grand_total) > second_approval_limit()

	def line(label, user, when, pending_text):
		if user:
			return {
				"label": label,
				"name": get_fullname(user),
				"date": frappe.format(when, {"fieldtype": "Datetime"}),
				"done": True,
			}
		return {"label": label, "name": pending_text, "date": "", "done": False}

	pending = _("Cancelled") if doc.docstatus == 2 else _("Pending")
	lines = [
		{
			"label": _("Prepared By"),
			"name": get_fullname(doc.owner),
			"date": frappe.format(doc.creation, {"fieldtype": "Datetime"}),
			"done": True,
		},
		line(_("1st Approval"), doc.get("l1_approved_by"), doc.get("l1_approved_on"), pending),
	]
	if needs_second or doc.get("l2_approved_by"):
		lines.append(line(_("2nd Approval"), doc.get("l2_approved_by"), doc.get("l2_approved_on"), pending))
	else:
		lines.append({"label": _("2nd Approval"), "name": _("Not required"), "date": "", "done": True})
	return {
		"approved": approved,
		"stamp": _("CANCELLED") if doc.docstatus == 2 else (None if approved else _("UNAPPROVED")),
		"state": doc.get("workflow_state") or (_("Approved") if approved else _("Draft")),
		"lines": lines,
	}
