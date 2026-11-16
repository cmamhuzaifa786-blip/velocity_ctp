# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Supplier Performance, per supplier, for Purchase Orders dated in the period.

- POs: submitted Purchase Orders; value in company currency
- On-time delivery %: receipt rows (submitted Purchase Receipts against those POs) posted on or before
  the PO row's required-by date, of all receipt rows
- Average delay: days late per receipt row (0 when on time), averaged over all receipt rows
- Overdue open rows: PO rows past their required-by date and not fully received
- Rejection % by value: rejected quantity of the submitted incoming Quality Inspections on those receipts,
  valued at the receipt rate, of the value received (received qty x receipt rate, plus the value of lots
  refused at inspection, which are not received). Quantities are never added across items or UOMs.
- Lots with rejection %: inspected lots with any rejection (partial or fully refused) of all inspected lots
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	frappe.has_permission("Purchase Order", "read", throw=True)
	message = _(
		"Rejection % by Value = rejected quantity on incoming inspections x receipt rate / value received. "
		"Lots with Rejection % = inspected lots with any rejection (partial or fully refused) / inspected lots."
	)
	return columns(), data(filters), message


def columns():
	return [
		{
			"fieldname": "supplier",
			"label": _("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 280,
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
		{
			"fieldname": "received_value",
			"label": _("Received Value"),
			"fieldtype": "Currency",
			"width": 130,
			"description": _(
				"Received quantity x receipt rate, plus lots refused at inspection (at their rate)."
			),
		},
		{
			"fieldname": "rejected_value",
			"label": _("Rejected Value"),
			"fieldtype": "Currency",
			"width": 125,
			"description": _(
				"Rejected quantity on submitted incoming inspections x the receipt rate of that row."
			),
		},
		{
			"fieldname": "rejection_value_pct",
			"label": _("Rejection % by Value"),
			"fieldtype": "Percent",
			"width": 145,
			"description": _(
				"Rejected Value / Received Value. Values, so items in different units are comparable."
			),
		},
		{
			"fieldname": "inspections",
			"label": _("Inspected Lots"),
			"fieldtype": "Int",
			"width": 110,
			"description": _("Submitted incoming Quality Inspections on this supplier's receipts."),
		},
		{
			"fieldname": "lots_with_rejection",
			"label": _("Lots with Rejection"),
			"fieldtype": "Int",
			"width": 140,
			"description": _(
				"Inspected lots with any rejection: a partial rejection or a fully refused lot."
			),
		},
		{
			"fieldname": "lots_with_rejection_pct",
			"label": _("Lots with Rejection %"),
			"fieldtype": "Percent",
			"width": 155,
			"description": _("Lots with Rejection / Inspected Lots."),
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
		f"""select po.supplier, pr.name as receipt, pr.posting_date, poi.schedule_date, pri.name as row_name,
			pri.item_code, pri.received_qty, pri.base_rate
		from `tabPurchase Receipt Item` pri
		join `tabPurchase Receipt` pr on pr.name = pri.parent
		join `tabPurchase Order Item` poi on poi.name = pri.purchase_order_item
		join `tabPurchase Order` po on po.name = poi.parent
		where pr.docstatus = 1 and pr.is_return = 0 and {where}""",
		values,
		as_dict=True,
	)
	receipt_supplier = {}
	row_rate: dict[str, float] = {}
	item_rate: dict[tuple[str, str], float] = {}
	for r in receipts:
		s = stats[r.supplier]
		delay = max(date_diff(r.posting_date, r.schedule_date), 0) if r.schedule_date else 0
		s["receipts"] += 1
		s["on_time"] += 1 if delay == 0 else 0
		s["delay_total"] += delay
		s["received_value"] += flt(r.received_qty) * flt(r.base_rate)
		receipt_supplier[r.receipt] = r.supplier
		row_rate[r.row_name] = flt(r.base_rate)
		item_rate[(r.receipt, r.item_code)] = flt(r.base_rate)

	if receipt_supplier:
		for qi in frappe.db.sql(
			"""select reference_name, child_row_reference, item_code, status, ifnull(rejected_qty, 0) as rejected
			from `tabQuality Inspection`
			where docstatus = 1 and reference_type = 'Purchase Receipt' and inspection_type = 'Incoming'
			and reference_name in %(r)s""",
			{"r": list(receipt_supplier)},
			as_dict=True,
		):
			s = stats[receipt_supplier[qi.reference_name]]
			s["inspections"] += 1
			if flt(qi.rejected) > 0 or qi.status == "Rejected":
				s["lots_with_rejection"] += 1
			rate = row_rate.get(qi.child_row_reference) or item_rate.get((qi.reference_name, qi.item_code))
			if rate is None:  # a refused lot whose row was removed from the receipt: last purchase rate
				rate = flt(frappe.get_cached_value("Item", qi.item_code, "last_purchase_rate"))
			s["rejected_value"] += flt(qi.rejected) * rate
			if qi.status == "Rejected" and qi.child_row_reference not in row_rate:
				s["received_value"] += flt(qi.rejected) * rate  # refused lot: not on the receipt

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
				"received_value": flt(s["received_value"], 2),
				"rejected_value": flt(s["rejected_value"], 2),
				"rejection_value_pct": flt(s["rejected_value"] / s["received_value"] * 100, 2)
				if s["received_value"]
				else None,
				"inspections": int(s["inspections"]),
				"lots_with_rejection": int(s["lots_with_rejection"]),
				"lots_with_rejection_pct": flt(s["lots_with_rejection"] / s["inspections"] * 100, 1)
				if s["inspections"]
				else None,
			}
		)
	return result
