# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Gate Balance: returnable items still out (Gate Outward rows not fully back on Gate Inwards), by party
and age; rows past their expected return date are overdue."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, nowdate

from velocity_ctp.shipping.gate import open_returnables


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Gate Outward", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{
			"fieldname": "party",
			"label": _("Party"),
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 215,
		},
		{
			"fieldname": "gate_outward",
			"label": _("Gate Outward"),
			"fieldtype": "Link",
			"options": "Gate Outward",
			"width": 135,
		},
		{"fieldname": "gate_pass_type", "label": _("Type"), "fieldtype": "Data", "width": 95},
		{"fieldname": "entry_date", "label": _("Out On"), "fieldtype": "Date", "width": 110},
		{"fieldname": "item", "label": _("Item / Description"), "fieldtype": "Data", "width": 360},
		{"fieldname": "qty", "label": _("Sent Out"), "fieldtype": "Float", "width": 90},
		{"fieldname": "returned", "label": _("Returned"), "fieldtype": "Float", "width": 90},
		{"fieldname": "open_qty", "label": _("Still Out"), "fieldtype": "Float", "width": 90},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 65},
		{"fieldname": "expected_return_date", "label": _("Expected Back"), "fieldtype": "Date", "width": 115},
		{"fieldname": "age", "label": _("Age (Days)"), "fieldtype": "Int", "width": 90},
		{"fieldname": "overdue_days", "label": _("Overdue (Days)"), "fieldtype": "Int", "width": 115},
		{"fieldname": "party_type", "label": _("Party Type"), "fieldtype": "Data", "hidden": 1},
	]


def data(filters):
	today = getdate(nowdate())
	rows = []
	for r in open_returnables():
		if filters.party and r.party != filters.party:
			continue
		overdue = (
			date_diff(today, r.expected_return_date)
			if r.expected_return_date and getdate(r.expected_return_date) < today
			else 0
		)
		if filters.only_overdue and not overdue:
			continue
		rows.append(
			{
				"party_type": r.party_type,
				"party": r.party,
				"gate_outward": r.gate_outward,
				"gate_pass_type": _(r.gate_pass_type),
				"entry_date": r.entry_date,
				"item": r.item_code or r.description,
				"qty": r.qty,
				"returned": r.returned,
				"open_qty": r.open_qty,
				"uom": r.uom,
				"expected_return_date": r.expected_return_date,
				"age": date_diff(today, r.entry_date),
				"overdue_days": overdue,
			}
		)
	return rows
