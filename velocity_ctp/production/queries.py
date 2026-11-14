"""Link-field queries for picking bundles on Process Issue / Process Receive."""

from __future__ import annotations

import json

import frappe

from velocity_ctp.production import flow


def _filters(filters) -> dict:
	return json.loads(filters) if isinstance(filters, str) else (filters or {})


def _search(base_filters: dict, txt: str, start: int, page_len: int) -> list[frappe._dict]:
	or_filters = None
	if txt:
		like = f"%{txt}%"
		or_filters = {
			"name": ("like", like),
			"garment_order": ("like", like),
			"colour": ("like", like),
			"size": ("like", like),
		}
	return frappe.get_list(
		"Bundle",
		filters=base_filters,
		or_filters=or_filters,
		fields=["name", "garment_order", "colour", "size", "qty", "status", "current_process", "current_party",
		        "open_issue", "pending_repair_qty", "job_map", "packed_qty"],
		order_by="name asc",
		start=start,
		page_length=page_len,
	)  # fmt: skip


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def issuable_bundles(doctype, txt, searchfield, start, page_len, filters):
	process = _filters(filters).get("process")
	previous = flow.previous_process(process) if process else None
	if not previous:
		return []
	base = {"current_process": previous, "status": "In Cutting" if previous == flow.CUTTING else "Received"}
	rows = _search(base, txt, start, page_len)
	return [
		(r.name, f"{r.garment_order} · {r.colour} / {r.size} · {r.qty} pcs")
		for r in rows
		if not flow.issue_block(r, process)
	]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def receivable_bundles(doctype, txt, searchfield, start, page_len, filters):
	f = _filters(filters)
	process, party = f.get("process"), f.get("party") or None
	if not process:
		return []
	base = {
		"current_process": process,
		"status": "Issued",
		"current_party": party if party else ("is", "not set"),
	}
	rows = _search(base, txt, start, page_len)
	return [
		(r.name, f"{r.garment_order} · {r.colour} / {r.size} · {flow.outstanding_qty(r)} pcs open")
		for r in rows
		if not flow.receive_block(r, process, party)
	]
