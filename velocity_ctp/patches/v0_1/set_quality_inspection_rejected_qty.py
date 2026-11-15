import frappe
from frappe.utils import flt


def execute():
	"""Fill rejected_qty on submitted incoming inspections made before the field existed.

	Accepted: the rejected quantity recorded on the receipt row (partial rejection). Rejected: the row's
	received quantity (whole lot) when the row still exists. The reason comes from the inspection's remarks.
	"""
	if not frappe.get_meta("Quality Inspection").has_field("rejected_qty"):
		return
	for qi in frappe.get_all(
		"Quality Inspection",
		filters={"docstatus": 1, "reference_type": "Purchase Receipt", "rejected_qty": ("in", (0, None))},
		fields=["name", "status", "reference_name", "child_row_reference", "remarks", "rejection_reason"],
	):
		row = frappe.db.get_value(
			"Purchase Receipt Item",
			{"name": qi.child_row_reference, "parent": qi.reference_name},
			["received_qty", "rejected_qty"],
			as_dict=True,
		)
		if not row:
			continue
		qty = flt(row.rejected_qty) if qi.status == "Accepted" else flt(row.received_qty)
		if qty <= 0:
			continue
		reason = (
			qi.rejection_reason
			or frappe.utils.strip_html(qi.remarks or "").strip()
			or f"Recorded on {qi.reference_name}"
		)
		frappe.db.set_value(
			"Quality Inspection",
			qi.name,
			{"rejected_qty": qty, "rejection_reason": reason},
			update_modified=False,
		)
