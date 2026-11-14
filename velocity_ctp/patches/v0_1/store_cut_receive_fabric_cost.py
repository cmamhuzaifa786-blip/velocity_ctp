"""Backfill Fabric Cost / Pc and Fabric Cost Amount on pieces of Cut Receives submitted before they
were stored. The Repack posted, per marker, its fabric rows followed by its good-piece rows, so
the posted rows are matched to the markers in that order (done once here; new Cut Receives store
the values when they are submitted).
"""

import frappe
from frappe.utils import flt


def execute():
	for name in frappe.get_all(
		"Cut Receive", filters={"docstatus": 1, "stock_entry": ("is", "set")}, pluck="name"
	):
		receive = frappe.get_doc("Cut Receive", name)
		if any(flt(p.fabric_cost_amount) for p in receive.pieces):
			continue
		rows = sorted(frappe.get_doc("Stock Entry", receive.stock_entry).items, key=lambda r: r.idx)
		groups = receive.marker_groups()
		valuation = []
		position = 0
		for group in groups:
			position += len(group["fabric"])
			values = {}
			for _piece in group["pieces"]:
				row = rows[position]
				position += 1
				values[row.item_code] = {
					"rate": flt(row.basic_rate),
					"amount": flt(row.basic_amount),
					"qty": flt(row.transfer_qty),
				}
			valuation.append(values)
		receive.store_fabric_cost(groups, valuation)
