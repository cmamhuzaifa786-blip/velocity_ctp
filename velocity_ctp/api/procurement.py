"""Procurement panel on Velocity Home and the Material stage of the Order Tracker."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, getdate, nowdate

from velocity_ctp.procurement.common import MR_PENDING, PO_PENDING_1, PO_PENDING_2

OPEN_PO_EXCLUDED = ["Closed", "Completed", "On Hold", "Delivered"]


def _count(doctype: str, filters: dict) -> int:
	return cint(frappe.get_list(doctype, filters=filters, fields=[{"COUNT": "name", "as": "n"}])[0].n)


def grns_pending_inspection() -> list[str]:
	"""Draft Purchase Receipts with a row whose item needs inspection before purchase and has no inspection."""
	names = frappe.db.sql_list(
		"""select distinct pr.name from `tabPurchase Receipt` pr
		join `tabPurchase Receipt Item` pri on pri.parent = pr.name and pri.parenttype = 'Purchase Receipt'
		join `tabItem` i on i.name = pri.item_code
		where pr.docstatus = 0 and pr.is_return = 0 and i.inspection_required_before_purchase = 1
			and ifnull(pri.quality_inspection, '') = ''"""
	)
	if not names:
		return []
	# respect the user's permissions on Purchase Receipt
	return frappe.get_list("Purchase Receipt", filters={"name": ("in", names)}, pluck="name")


@frappe.whitelist()
def get_procurement_summary() -> dict | None:
	can = {
		dt: bool(frappe.has_permission(dt, "read"))
		for dt in ("Material Request", "Purchase Order", "Purchase Receipt")
	}
	if not any(can.values()):
		return None
	today = str(getdate(nowdate()))
	cards = []
	if can["Material Request"]:
		filters = {"docstatus": 0, "workflow_state": MR_PENDING}
		cards.append(
			{
				"key": "requisitions_pending",
				"label": _("Requisitions Pending Approval"),
				"sub": _("Material Requests waiting for an approver"),
				"value": _count("Material Request", filters),
				"tone": "warn",
				"doctype": "Material Request",
				"filters": filters,
			}
		)
	if can["Purchase Order"]:
		for key, state, label in (
			("po_pending_1", PO_PENDING_1, _("POs Pending 1st Approval")),
			("po_pending_2", PO_PENDING_2, _("POs Pending 2nd Approval")),
		):
			filters = {"docstatus": 0, "workflow_state": state}
			cards.append(
				{
					"key": key,
					"label": label,
					"sub": _("Velocity PO Approver L1")
					if state == PO_PENDING_1
					else _("Above the second-approval limit"),
					"value": _count("Purchase Order", filters),
					"tone": "warn",
					"doctype": "Purchase Order",
					"filters": filters,
				}
			)
		filters = {
			"docstatus": 1,
			"status": ["not in", OPEN_PO_EXCLUDED],
			"per_received": ["<", 100],
			"schedule_date": ["<", today],
		}
		cards.append(
			{
				"key": "po_overdue",
				"label": _("POs Overdue"),
				"sub": _("Required-by date passed, not fully received"),
				"value": _count("Purchase Order", filters),
				"tone": "bad",
				"doctype": "Purchase Order",
				"filters": filters,
			}
		)
	if can["Purchase Receipt"]:
		pending = grns_pending_inspection()
		cards.append(
			{
				"key": "grn_pending_qi",
				"label": _("GRNs Pending Inspection"),
				"sub": _("Draft receipts without a quality inspection"),
				"value": len(pending),
				"tone": "info",
				"doctype": "Purchase Receipt",
				"filters": {"name": ["in", pending or [""]]},
			}
		)
	return {"cards": cards}


# ----------------------------------------------------------------------------------------------
# Order Tracker: Material stage
# ----------------------------------------------------------------------------------------------


def stage_material(orders: list[frappe._dict], context: dict) -> dict[str, dict]:
	"""Material stage from the order's submitted Material Plan (availability computed for all plans at once).

	Not planned: no submitted plan. Planned: a shortfall exists. Covered: no shortfall. Issued: every
	fabric and accessory fully issued. The tooltip shows fabric and accessory coverage %.
	"""
	from velocity_ctp.procurement.availability import compute, coverage

	names = [o.name for o in orders]
	plans = (
		frappe.get_all(
			"Material Plan",
			filters={"garment_order": ("in", names), "docstatus": 1},
			fields=["name", "garment_order", "company"],
		)
		if names
		else []
	)
	by_company: dict[str, list[dict]] = defaultdict(list)
	for p in plans:
		by_company[p.company].append({"name": p.name, "garment_order": p.garment_order, "needs": None})
	rows_by_plan: dict[str, list[dict]] = {}
	for company, targets in by_company.items():
		rows_by_plan.update(compute(company, targets))
	plan_of = {p.garment_order: p.name for p in plans}

	labels = {
		"Planned": (_("Planned"), "blocked"),
		"Covered": (_("Covered"), "active"),
		"Issued": (_("Issued"), "done"),
	}
	result: dict[str, dict] = {}
	for o in orders:
		plan = plan_of.get(o.name)
		if not plan:
			result[o.name] = {"state": "pending", "detail": _("Not planned")}
			continue
		rows = rows_by_plan.get(plan, [])
		cov = coverage(rows)
		detail, state = labels[cov["state"]]
		short = [r for r in rows if r["shortfall"] > 0]
		parts = []
		if cov["fabric"] is not None:
			parts.append(_("Fabric {0}% covered").format(cov["fabric"]))
		if cov["accessory"] is not None:
			parts.append(_("Accessories {0}% covered").format(cov["accessory"]))
		if short:
			parts.append(_("shortfall on {0} item(s)").format(len(short)))
		result[o.name] = {"state": state, "detail": detail, "hint": " · ".join(parts) + f" ({plan})"}
	return result
