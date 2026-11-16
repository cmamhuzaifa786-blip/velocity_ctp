# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Accrued Contractor Charges: unbilled contractor work by contractor and age (0-15, 16-30, 31+ days).

The total equals the GL balance of "Contractor Charges Accrued": work credits the account when it is
received, and the submitted contractor Purchase Invoice debits it. When an invoice was billed at a rate
different from the accrued rate (within the tolerance), the difference stays in the account and is
listed as "Rate difference on billed work" until it is adjusted. The message above the report compares
the total with the GL balance.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from velocity_ctp.procurement import contractor_billing
from velocity_ctp.setup.install import get_default_company

PKR = "Company:company:default_currency"
BUCKETS = ("0-15", "16-30", "31+")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Purchase Invoice", "read", throw=True)
	company = filters.company or get_default_company()
	as_of = getdate(filters.as_of or nowdate())
	rows = data(company, as_of, filters.supplier)
	total = flt(sum(flt(r["amount"]) for r in rows), 2)
	message = None
	if not filters.supplier:
		balance = contractor_billing.accrual_gl_balance(company)
		ok = abs(total - balance) < 0.01
		message = _("Total {0} {1} the GL balance of Contractor Charges Accrued ({2}).").format(
			frappe.format(total, {"fieldtype": "Currency"}),
			_("equals") if ok else _("does NOT equal"),
			frappe.format(balance, {"fieldtype": "Currency"}),
		)
	return columns(), rows, message


def columns():
	def money(fieldname, label, width=120):
		return {
			"fieldname": fieldname,
			"label": label,
			"fieldtype": "Currency",
			"options": PKR,
			"width": width,
		}

	return [
		{
			"fieldname": "supplier",
			"label": _("Contractor"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 280,
		},
		{"fieldname": "source_doctype", "label": _("Type"), "fieldtype": "Data", "width": 140},
		{
			"fieldname": "source_name",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "source_doctype",
			"width": 140,
		},
		{"fieldname": "posting_date", "label": _("Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "process", "label": _("Process"), "fieldtype": "Data", "width": 95},
		{
			"fieldname": "garment_order",
			"label": _("Garment Order"),
			"fieldtype": "Link",
			"options": "Garment Order",
			"width": 120,
		},
		{"fieldname": "fresh_qty", "label": _("Pieces"), "fieldtype": "Float", "precision": 0, "width": 105},
		{"fieldname": "age", "label": _("Age (Days)"), "fieldtype": "Int", "width": 90},
		money("range_0_15", _("0-15 Days")),
		money("range_16_30", _("16-30 Days")),
		money("range_31", _("31+ Days")),
		money("amount", _("Total"), 130),
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 230},
	]


def data(company: str, as_of, supplier: str | None = None) -> list[dict]:
	rows = []
	work = contractor_billing.unbilled(
		contractor_billing.work_rows(supplier=supplier, to_date=as_of, company=company)
	)
	differences = [
		d
		for d in contractor_billing.billed_rate_differences(company)
		if not supplier or d.supplier == supplier
	]
	for r in work:
		rows.append(line(r, as_of, _("Unbilled work")))
	for d in differences:
		rows.append(line(d, as_of, _("Rate difference on billed work ({0})").format(d.purchase_invoice)))
	return rows


def line(r, as_of, note: str) -> dict:
	bucket = contractor_billing.age_bucket(r.posting_date, as_of)
	amount = flt(r.amount, 2)
	return {
		"supplier": r.supplier,
		"source_doctype": r.source_doctype,
		"source_name": r.source_name,
		"posting_date": r.posting_date,
		"process": r.process,
		"garment_order": r.garment_order,
		"fresh_qty": r.get("fresh_qty"),
		"age": date_diff(as_of, r.posting_date),
		"range_0_15": amount if bucket == BUCKETS[0] else 0,
		"range_16_30": amount if bucket == BUCKETS[1] else 0,
		"range_31": amount if bucket == BUCKETS[2] else 0,
		"amount": amount,
		"note": note,
	}
