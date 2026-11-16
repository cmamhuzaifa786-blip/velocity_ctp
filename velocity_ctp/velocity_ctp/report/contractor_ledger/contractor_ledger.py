# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Contractor Ledger: per contractor, work received and accrued, billed, unbilled, paid and outstanding.

- Work received: Cut Receives (contractor) and outsourced Process Receives; value = the contractor charge
  accrued at submit (Contractor Charges Accrued)
- Billed: submitted Purchase Invoice rows linked to that work (Contractor Bill Run)
- Unbilled: work not on a submitted invoice (still in Contractor Charges Accrued)
- Paid / Outstanding: of those invoices (grand total - outstanding / outstanding, from Payment Entries)
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from velocity_ctp.procurement import contractor_billing

PKR = "Company:company:default_currency"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Purchase Invoice", "read", throw=True)
	return columns(), data(filters)


def columns():
	def money(fieldname, label, width=140):
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
		{"fieldname": "documents", "label": _("Work Documents"), "fieldtype": "Int", "width": 125},
		{
			"fieldname": "qty",
			"label": _("Pieces Received"),
			"fieldtype": "Float",
			"precision": 0,
			"width": 125,
		},
		money("accrued", _("Work Value (Accrued)"), 165),
		money("billed", _("Billed"), 130),
		money("unbilled", _("Unbilled"), 130),
		money("paid", _("Paid"), 120),
		money("outstanding", _("Outstanding"), 130),
	]


def data(filters):
	rows = contractor_billing.work_rows(
		supplier=filters.supplier,
		from_date=filters.from_date,
		to_date=filters.to_date,
		company=filters.company,
	)
	stats: dict[str, dict] = defaultdict(lambda: defaultdict(float))
	invoices: dict[str, set] = defaultdict(set)
	for r in rows:
		s = stats[r.supplier]
		s["documents"] += 1
		s["qty"] += flt(r.fresh_qty)
		s["accrued"] += flt(r.amount)
		if not r.billed_on:
			s["unbilled"] += flt(r.amount)
		else:
			invoices[r.supplier].add(r.billed_on)

	all_invoices = {i for v in invoices.values() for i in v}
	if all_invoices:
		amounts = {
			name: (flt(billed), flt(total), flt(outstanding))
			for name, billed, total, outstanding in frappe.db.sql(
				"""select pi.name, sum(pii.base_amount), max(pi.base_grand_total), max(pi.outstanding_amount)
				from `tabPurchase Invoice` pi join `tabPurchase Invoice Item` pii on pii.parent = pi.name
				where pi.name in %(i)s and ifnull(pii.velocity_source_name, '') != '' group by pi.name""",
				{"i": list(all_invoices)},
			)
		}
		for supplier, names in invoices.items():
			for name in names:
				billed, total, outstanding = amounts.get(name, (0, 0, 0))
				stats[supplier]["billed"] += billed
				stats[supplier]["paid"] += total - outstanding
				stats[supplier]["outstanding"] += outstanding

	return [
		{
			"supplier": supplier,
			"documents": int(s["documents"]),
			"qty": s["qty"],
			"accrued": flt(s["accrued"], 2),
			"billed": flt(s["billed"], 2),
			"unbilled": flt(s["unbilled"], 2),
			"paid": flt(s["paid"], 2),
			"outstanding": flt(s["outstanding"], 2),
		}
		for supplier, s in sorted(stats.items())
	]
