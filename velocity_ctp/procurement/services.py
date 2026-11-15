"""Service Orders: standard Purchase Orders with po_category "Service" for contractor work.

A Service Order row names the process (Cutting, Stitching, Washing, ...) and the Garment Order it pays
for. Process Issue (outsourced) and Cut Receive (contractor) take the piece rate from that row, and the
quantity issued or cut against a row may not exceed its ordered quantity plus the over-receipt allowance
in Stock Settings.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from velocity_ctp.procurement.common import APPROVED

SERVICE_CATEGORY = "Service"
EPS = 1e-9


def get_service_order(service_order: str, supplier: str | None) -> frappe._dict:
	po = frappe.db.get_value(
		"Purchase Order",
		service_order,
		["name", "docstatus", "supplier", "po_category", "status", "workflow_state"],
		as_dict=True,
	)
	if not po:
		frappe.throw(_("Service Order {0} does not exist.").format(frappe.bold(service_order)))
	if po.docstatus != 1 or (po.workflow_state and po.workflow_state != APPROVED):
		frappe.throw(_("Service Order {0} is not approved yet.").format(frappe.bold(service_order)))
	if po.po_category != SERVICE_CATEGORY:
		frappe.throw(
			_("Purchase Order {0} is not a Service order (category {1}).").format(
				frappe.bold(service_order), _(po.po_category or "-")
			)
		)
	if supplier and po.supplier != supplier:
		frappe.throw(
			_("Service Order {0} is for {1}, not for {2}.").format(
				frappe.bold(service_order), frappe.bold(po.supplier), frappe.bold(supplier)
			)
		)
	if po.status in ("Closed", "On Hold"):
		frappe.throw(_("Service Order {0} is {1}.").format(frappe.bold(service_order), _(po.status)))
	return po


def find_row(service_order: str, supplier: str | None, process: str, garment_order: str) -> frappe._dict:
	"""The Service Order row for this process and garment order (clear message when there is none)."""
	get_service_order(service_order, supplier)
	rows = frappe.get_all(
		"Purchase Order Item",
		filters={
			"parent": service_order,
			"parenttype": "Purchase Order",
			"production_process": process,
			"garment_order": garment_order,
		},
		fields=["name", "item_code", "qty", "stock_qty", "rate", "base_rate", "uom", "colour", "size", "idx"],
		order_by="idx",
	)
	if not rows:
		frappe.throw(
			_("Service Order {0} has no row for process {1} and Garment Order {2}.").format(
				frappe.bold(service_order), frappe.bold(process), frappe.bold(garment_order)
			),
			title=_("No Service Order Row"),
		)
	return rows[0]


def used_qty(service_order_item: str, exclude: tuple[str, str] | None = None) -> float:
	"""Pieces already issued (Process Issue) or cut (Cut Receive good pieces) against a Service Order row."""
	exclude_dt, exclude_name = exclude or ("", "")
	issued = frappe.db.sql(
		"""select ifnull(sum(total_qty), 0) from `tabProcess Issue`
		where docstatus = 1 and service_order_item = %s and not (%s = 'Process Issue' and name = %s)""",
		(service_order_item, exclude_dt, exclude_name),
	)[0][0]
	cut = frappe.db.sql(
		"""select ifnull(sum(crp.good_qty), 0) from `tabCut Receive Piece` crp
		join `tabCut Receive` cr on cr.name = crp.parent
		join `tabPurchase Order Item` poi on poi.parent = cr.service_order
			and poi.production_process = 'Cutting' and poi.garment_order = crp.garment_order
		where cr.docstatus = 1 and poi.name = %s and not (%s = 'Cut Receive' and cr.name = %s)""",
		(service_order_item, exclude_dt, exclude_name),
	)[0][0]
	return flt(issued) + flt(cut)


def validate_capacity(row: frappe._dict, qty: float, exclude: tuple[str, str], label: str) -> None:
	allowance = flt(frappe.db.get_single_value("Stock Settings", "over_delivery_receipt_allowance"))
	limit = flt(row.qty) * (1 + allowance / 100)
	used = used_qty(row.name, exclude)
	if used + flt(qty) > limit + EPS:
		frappe.throw(
			_(
				"{0}: Service Order row {1} is for {2} pieces ({3}% tolerance allows {4}). {5} are already "
				"issued against it and {6} are entered now."
			).format(
				label,
				row.idx,
				f"{flt(row.qty, 3):g}",
				f"{flt(allowance, 2):g}",
				f"{flt(limit, 2):g}",
				f"{flt(used, 3):g}",
				f"{flt(qty, 3):g}",
			),
			title=_("Service Order Quantity Exceeded"),
		)


@frappe.whitelist()
def service_order_query(doctype, txt, searchfield, start, page_len, filters):
	"""Approved Service Purchase Orders of a supplier (for the Service Order link fields)."""
	filters = frappe.parse_json(filters) or {}
	conditions = {
		"docstatus": 1,
		"po_category": SERVICE_CATEGORY,
		"status": ("not in", ("Closed", "On Hold")),
	}
	if filters.get("supplier"):
		conditions["supplier"] = filters["supplier"]
	names = frappe.get_list(
		"Purchase Order",
		filters={**conditions, "name": ("like", f"%{txt}%")},
		fields=["name", "supplier", "transaction_date"],
		limit_start=start,
		limit_page_length=page_len,
		as_list=True,
	)
	return names
