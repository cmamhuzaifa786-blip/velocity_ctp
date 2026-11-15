# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Supplier Performance, per supplier, for Purchase Orders dated in the period.

- POs: submitted Purchase Orders; value in company currency
- On-time delivery %: receipt rows (submitted Purchase Receipts against those POs) posted on or before
  the PO row's required-by date, of all receipt rows
- Average delay: days late per receipt row (0 when on time), averaged over all receipt rows
- Overdue open rows: PO rows past their required-by date and not fully received
- Rejected qty comes from the submitted incoming Quality Inspections on those receipts (rejected_qty):
  Accepted inspections reject part of a lot, Rejected inspections refuse the whole lot (which is then not
  received). Rejection % = rejected qty / (received qty + refused lots)
- Lots refused %: Rejected inspections of all submitted incoming inspections on those receipts
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Purchase Order", "read", throw=True)
	return columns(), data(filters)


def columns():
	return [
		{
			"fieldname": "supplier",
			"label": _("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 180,
		},
		{"fieldname": "pos", "label": _("POs"), "fieldtype": "Int", "width": 60},
		{"fieldname": "po_value", "label": _("PO Value"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "receipts", "label": _("Receipt Rows"), "fieldtype": "Int", "width": 100},
		{"fieldname": "on_time_pct", "label": _("On-time Delivery %"), "fieldtype": "Percent", "width": 135},
		{
			"fieldname": "avg_delay",
			"label": _("Average Delay (Days)"),
			"fieldtype": "Float",
			"precision": 1,
			"width": 140,
		},
		{"fieldname": "overdue_rows", "label": _("Overdue Open Rows"), "fieldtype": "Int", "width": 130},
		{"fieldname": "received_qty", "label": _("Received Qty"), "fieldtype": "Float", "width": 110},
		{
			"fieldname": "rejected_qty",
			"label": _("Rejected Qty (Inspections)"),
			"fieldtype": "Float",
			"width": 175,
		},
		{"fieldname": "rejection_pct", "label": _("Rejection %"), "fieldtype": "Percent", "width": 100},
		{"fieldname": "inspections", "label": _("Inspected Lots"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "rejected_inspections",
			"label": _("Lots Refused"),
			"fieldtype": "Int",
			"width": 140,
		},
		{
			"fieldname": "inspection_rejection_pct",
			"label": _("Lots Refused %"),
			"fieldtype": "Percent",
			"width": 155,
		},
	]


def data(filters):
	from_date = filters.from_date or add_months(nowdate(), -6)
	to_date = filters.to_date or nowdate()
	conditions = ["po.docstatus = 1", "po.transaction_date between %(from_date)s and %(to_date)s"]
	values = {"from_date": from_date, "to_date": to_date}
	for field in ("supplier", "po_category", "company"):
		if filters.get(field):
			conditions.append(f"po.{field} = %({field})s")
			values[field] = filters.get(field)
	allowed = frappe.get_list("Purchase Order", filters={"docstatus": 1}, pluck="name")
	if not allowed:
		return []
	values["allowed"] = allowed
	conditions.append("po.name in %(allowed)s")
	where = " and ".join(conditions)

	stats: dict[str, dict] = defaultdict(lambda: defaultdict(float))
	for supplier, count, value in frappe.db.sql(
		f"select po.supplier, count(*), sum(po.base_grand_total) from `tabPurchase Order` po where {where} group by po.supplier",
		values,
	):
		stats[supplier]["pos"] = count
		stats[supplier]["po_value"] = flt(value)

	today = getdate(nowdate())
	for supplier, schedule_date, qty, received, status in frappe.db.sql(
		f"""select po.supplier, poi.schedule_date, poi.qty, poi.received_qty, po.status
		from `tabPurchase Order Item` poi join `tabPurchase Order` po on po.name = poi.parent where {where}""",
		values,
	):
		if (
			status not in ("Closed", "Completed")
			and flt(received) < flt(qty)
			and schedule_date
			and getdate(schedule_date) < today
		):
			stats[supplier]["overdue_rows"] += 1

	receipts = frappe.db.sql(
		f"""select po.supplier, pr.name as receipt, pr.posting_date, poi.schedule_date, pri.received_qty, pri.rejected_qty
		from `tabPurchase Receipt Item` pri
		join `tabPurchase Receipt` pr on pr.name = pri.parent
		join `tabPurchase Order Item` poi on poi.name = pri.purchase_order_item
		join `tabPurchase Order` po on po.name = poi.parent
		where pr.docstatus = 1 and pr.is_return = 0 and {where}""",
		values,
		as_dict=True,
	)
	receipt_supplier = {}
	for r in receipts:
		s = stats[r.supplier]
		delay = max(date_diff(r.posting_date, r.schedule_date), 0) if r.schedule_date else 0
		s["receipts"] += 1
		s["on_time"] += 1 if delay == 0 else 0
		s["delay_total"] += delay
		s["received_qty"] += flt(r.received_qty)
		receipt_supplier[r.receipt] = r.supplier

	if receipt_supplier:
		for receipt, status, rejected in frappe.db.sql(
			"""select reference_name, status, ifnull(rejected_qty, 0) from `tabQuality Inspection`
			where docstatus = 1 and reference_type = 'Purchase Receipt' and inspection_type = 'Incoming'
			and reference_name in %(r)s""",
			{"r": list(receipt_supplier)},
		):
			s = stats[receipt_supplier[receipt]]
			s["inspections"] += 1
			s["rejected_qty"] += flt(rejected)
			if status == "Rejected":
				s["rejected_inspections"] += 1
				s["refused_qty"] += flt(rejected)  # the whole lot was refused, so it is not in received_qty

	result = []
	for supplier, s in sorted(stats.items()):
		receipts_count = int(s["receipts"])
		result.append(
			{
				"supplier": supplier,
				"pos": int(s["pos"]),
				"po_value": s["po_value"],
				"receipts": receipts_count,
				"on_time_pct": flt(s["on_time"] / receipts_count * 100, 1) if receipts_count else None,
				"avg_delay": flt(s["delay_total"] / receipts_count, 1) if receipts_count else None,
				"overdue_rows": int(s["overdue_rows"]),
				"received_qty": s["received_qty"],
				"rejected_qty": s["rejected_qty"],
				"rejection_pct": flt(s["rejected_qty"] / (s["received_qty"] + s["refused_qty"]) * 100, 2)
				if s["received_qty"] + s["refused_qty"]
				else None,
				"inspections": int(s["inspections"]),
				"rejected_inspections": int(s["rejected_inspections"]),
				"inspection_rejection_pct": flt(s["rejected_inspections"] / s["inspections"] * 100, 1)
				if s["inspections"]
				else None,
			}
		)
	return result
