"""Scan Station backend: validate scanned bundle barcodes and create Process Issues / Receives."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, nowdate

from velocity_ctp.production import flow

SETTINGS_KEY = "velocity_scan_station"
ACTIONS = ("Issue", "Receive")


def _doctype(action: str) -> str:
	if action not in ACTIONS:
		frappe.throw(_("Action must be Issue or Receive."))
	return "Process Issue" if action == "Issue" else "Process Receive"


@frappe.whitelist()
def get_setup() -> dict:
	if not (
		frappe.has_permission("Process Issue", "create") or frappe.has_permission("Process Receive", "create")
	):
		frappe.throw(_("You do not have permission to issue or receive bundles."), frappe.PermissionError)
	last = frappe.defaults.get_user_default(SETTINGS_KEY)
	return {
		"processes": [
			{
				"name": p.name,
				"process_type": p.process_type,
				"allow_rejection": p.allow_rejection,
				"allow_colour_change": p.allow_colour_change,
			}
			for p in flow.issuable_processes()
		],
		"last": json.loads(last) if last else {},
		"can_issue": bool(frappe.has_permission("Process Issue", "create")),
		"can_receive": bool(frappe.has_permission("Process Receive", "create")),
	}


@frappe.whitelist(methods=["POST"])
def save_choice(process: str, action: str, party: str | None = None) -> None:
	"""Remember the last process / action / party for this user."""
	frappe.defaults.set_user_default(
		SETTINGS_KEY, json.dumps({"process": process, "action": action, "party": party or ""})
	)


def _check_choice(process: str, action: str, party: str | None) -> frappe._dict:
	frappe.has_permission(_doctype(action), "create", throw=True)
	return flow.validate_process_party(process, party or None)


@frappe.whitelist(methods=["POST"])
def scan(
	barcode: str, process: str, action: str, party: str | None = None, scanned: list | str | None = None
) -> dict:
	"""Check one scanned barcode. Returns {"ok": True, "bundle": {...}} or {"ok": False, "reason": "..."}."""
	info = _check_choice(process, action, party)
	scanned = json.loads(scanned) if isinstance(scanned, str) else (scanned or [])
	name = (barcode or "").strip().upper()
	if not name:
		return {"ok": False, "reason": _("Empty scan.")}
	if name in scanned:
		return {"ok": False, "reason": _("Bundle {0} is already in this list.").format(name)}
	if not frappe.db.exists("Bundle", name):
		return {"ok": False, "reason": _("Unknown barcode {0}: no bundle has this number.").format(barcode)}

	bundle = frappe.get_doc("Bundle", name)
	reason = (
		flow.issue_block(bundle, process)
		if action == "Issue"
		else flow.receive_block(bundle, process, party or None)
	)
	if reason:
		return {"ok": False, "reason": reason}

	row = {
		"bundle": bundle.name,
		"garment_order": bundle.garment_order,
		"style": bundle.style,
		"colour": bundle.colour,
		"size": bundle.size,
		"qty": cint(bundle.qty),
	}
	if action == "Receive":
		open_qty = flow.outstanding_qty(bundle)
		row.update(
			{
				"process_issue": bundle.open_issue,
				"issued_qty": open_qty,
				"fresh_qty": open_qty,
				"rejected_qty": 0,
				"repair_qty": 0,
				"to_colour": "",
				"repair_pending": cint(bundle.pending_repair_qty),
			}
		)
		if info.allow_colour_change:
			row["colours"] = frappe.get_all(
				"Style Colour", filters={"parent": bundle.style, "parenttype": "Style"}, pluck="colour"
			)
	return {"ok": True, "bundle": row}


@frappe.whitelist(methods=["POST"])
def submit(process: str, action: str, party: str | None = None, rows: list | str | None = None) -> dict:
	"""Create and submit the Process Issue or Process Receive for the scanned bundles."""
	_check_choice(process, action, party)
	rows = json.loads(rows) if isinstance(rows, str) else (rows or [])
	if not rows:
		frappe.throw(_("Scan at least one bundle first."))
	doctype = _doctype(action)
	doc = frappe.new_doc(doctype)
	doc.update({"production_process": process, "party": party or None, "posting_date": nowdate()})
	for row in rows:
		if action == "Issue":
			doc.append("bundles", {"bundle": row["bundle"]})
		else:
			doc.append(
				"bundles",
				{
					"bundle": row["bundle"],
					"fresh_qty": cint(row.get("fresh_qty")),
					"rejected_qty": cint(row.get("rejected_qty")),
					"repair_qty": cint(row.get("repair_qty")),
					"to_colour": row.get("to_colour") or None,
					"remarks": row.get("remarks"),
				},
			)
	doc.insert()
	doc.submit()
	save_choice(process, action, party)
	return {
		"doctype": doctype,
		"name": doc.name,
		"bundles": len(doc.bundles),
		"pieces": doc.total_qty if action == "Issue" else doc.total_fresh,
	}
