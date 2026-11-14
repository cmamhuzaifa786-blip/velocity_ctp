"""Bundle flow through the processes: stage rules, state changes, snapshots and cancel guards.

Stages follow the Process master's sequence (active processes only):
Cutting -> Stitching -> Washing -> Finishing -> Packing. Process Issue / Receive cover the
processes between Cutting and Packing; packing is done by the Packing List.

Repair pieces: a receive may leave pieces "for repair" at the process. They stay physically
where they were (contractor warehouse or process WIP, kept on the bundle as repair_warehouse)
and the bundle stays Issued until a later receive clears them, so it cannot move on before.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime

CUTTING = "Cutting"
PACKING = "Packing"
SNAPSHOT_FIELDS = {
	"before_process": "current_process",
	"before_warehouse": "current_warehouse",
	"before_status": "status",
	"before_party": "current_party",
	"before_open_issue": "open_issue",
	"before_issued_on": "issued_on",
	"before_qty": "qty",
	"before_colour": "colour",
	"before_item_code": "item_code",
	"before_pending_repair_qty": "pending_repair_qty",
	"before_repair_warehouse": "repair_warehouse",
	"before_packed_qty": "packed_qty",
}


# ----------------------------------------------------------------------------------------------
# Process sequence
# ----------------------------------------------------------------------------------------------


def active_processes() -> list[frappe._dict]:
	return frappe.get_all(
		"Process",
		filters={"is_active": 1},
		fields=["name", "sequence", "process_type", "wip_warehouse", "allow_rejection", "allow_colour_change",
		        "default_piece_rate"],
		order_by="sequence asc",
	)  # fmt: skip


def previous_process(process: str) -> str | None:
	names = [p.name for p in active_processes()]
	if process not in names:
		return None
	index = names.index(process)
	return names[index - 1] if index else None


def issuable_processes() -> list[frappe._dict]:
	"""Processes that use Process Issue / Receive (everything between Cutting and Packing)."""
	return [p for p in active_processes() if p.name not in (CUTTING, PACKING)]


def packing_source_process() -> str | None:
	"""The active process just before Packing (normally Finishing)."""
	return previous_process(PACKING)


def is_outsourced(process_type: str | None, party: str | None) -> bool:
	return process_type == "Outsourced" or (process_type == "Both" and bool(party))


def validate_process_party(process: str, party: str | None) -> frappe._dict:
	info = frappe.db.get_value(
		"Process", process,
		["name", "process_type", "wip_warehouse", "allow_rejection", "allow_colour_change", "default_piece_rate", "is_active"],
		as_dict=True,
	)  # fmt: skip
	if not info or not info.is_active:
		frappe.throw(_("Process {0} is not active.").format(frappe.bold(process)))
	if process in (CUTTING, PACKING):
		frappe.throw(
			_(
				"{0} is not handled by Process Issue / Receive. Use Cut Receive for cutting and Packing List for packing."
			).format(frappe.bold(process))
		)
	if info.process_type == "Outsourced" and not party:
		frappe.throw(
			_("{0} is outsourced. Please select the party (contractor).").format(frappe.bold(process))
		)
	if info.process_type == "In-house" and party:
		frappe.throw(_("{0} is done in-house. Leave the party empty.").format(frappe.bold(process)))
	return info


# ----------------------------------------------------------------------------------------------
# Rules
# ----------------------------------------------------------------------------------------------


def stage_label(bundle) -> str:
	if bundle.status == "In Cutting":
		return _("in Cutting")
	if bundle.status == "Issued":
		where = _("issued to {0}").format(bundle.current_process)
		if bundle.current_party:
			where += " (" + bundle.current_party + ")"
		if cint(bundle.pending_repair_qty):
			where += ", " + _("{0} pcs in repair").format(bundle.pending_repair_qty)
		return where
	if bundle.status == "Received":
		return _("received from {0}").format(bundle.current_process)
	return _(bundle.status or "")


def job_map_block(bundle) -> str | None:
	if not bundle.job_map:
		return None
	on_hold, closed = frappe.db.get_value("Job Map", bundle.job_map, ["on_hold", "job_closed"]) or (0, 0)
	if closed:
		return _("Bundle {0}: Job Map {1} is closed.").format(bundle.name, bundle.job_map)
	if on_hold:
		return _("Bundle {0}: Job Map {1} is on hold.").format(bundle.name, bundle.job_map)
	return None


def issue_block(bundle, process: str) -> str | None:
	"""Why a bundle cannot be issued to `process`, or None."""
	if bundle.status in ("Completed", "Rejected"):
		return _("Bundle {0} is {1} and cannot be issued.").format(bundle.name, _(bundle.status))
	reason = job_map_block(bundle)
	if reason:
		return reason
	if bundle.current_process == process:
		if bundle.status == "Issued":
			return _("Bundle {0} is already issued to {1} on {2}.").format(
				bundle.name, process, bundle.open_issue
			)
		return _("Bundle {0} has already been through {1} ({2}).").format(
			bundle.name, process, stage_label(bundle)
		)
	previous = previous_process(process)
	if previous == CUTTING:
		if bundle.current_process == CUTTING and bundle.status == "In Cutting":
			return None
	elif previous and bundle.current_process == previous and bundle.status == "Received":
		return None
	return _("Bundle {0} is {1}; it must be received from {2} before it can go to {3}.").format(
		bundle.name, stage_label(bundle), previous or "-", process
	)


def receive_block(bundle, process: str, party: str | None) -> str | None:
	"""Why a bundle cannot be received from `process` / `party`, or None."""
	reason = job_map_block(bundle)
	if reason:
		return reason
	if bundle.status != "Issued" or bundle.current_process != process or not bundle.open_issue:
		return _("Bundle {0} is {1}, not issued to {2}.").format(bundle.name, stage_label(bundle), process)
	if (bundle.current_party or None) != (party or None):
		return _("Bundle {0} was issued to {1}, not {2}.").format(
			bundle.name, bundle.current_party or _("in-house"), party or _("in-house")
		)
	return None


def outstanding_qty(bundle) -> int:
	"""Pieces still open at the process for this bundle (repair pieces once a receive has happened)."""
	return cint(bundle.pending_repair_qty) or cint(bundle.qty)


# ----------------------------------------------------------------------------------------------
# State changes
# ----------------------------------------------------------------------------------------------


def snapshot(row, bundle) -> None:
	for row_field, bundle_field in SNAPSHOT_FIELDS.items():
		if row.meta.has_field(row_field):
			row.set(row_field, bundle.get(bundle_field))


def add_movement(bundle, from_process, to_process, doctype, name, qty) -> None:
	bundle.append(
		"history",
		{
			"datetime": now_datetime(),
			"from_process": from_process,
			"to_process": to_process,
			"document_type": doctype,
			"document_name": name,
			"qty": cint(qty),
			"user": frappe.session.user,
		},
	)


def save_bundle(bundle) -> None:
	"""Bundles are maintained by the app only. Links are not re-validated on save: the movement
	history keeps the user of each step even if that user is later deleted."""
	bundle.flags.ignore_permissions = True
	bundle.flags.ignore_links = True
	bundle.save()


def apply_issue(bundle, issue, target_warehouse: str) -> None:
	from_process = bundle.current_process
	bundle.update(
		{
			"current_process": issue.production_process,
			"current_warehouse": target_warehouse,
			"status": "Issued",
			"current_party": issue.party or None,
			"open_issue": issue.name,
			"issued_on": issue.posting_date,
			"pending_repair_qty": 0,
			"repair_warehouse": None,
		}
	)
	add_movement(bundle, from_process, issue.production_process, issue.doctype, issue.name, bundle.qty)
	save_bundle(bundle)


def apply_receive(bundle, receive, row, process_wip: str) -> None:
	fresh, rejected, repair = cint(row.fresh_qty), cint(row.rejected_qty), cint(row.repair_qty)
	qty_after = cint(bundle.qty) - rejected
	values = {
		"qty": qty_after,
		"current_warehouse": process_wip,
		"pending_repair_qty": repair,
		"repair_warehouse": row.from_warehouse if repair else None,
	}
	if repair:
		values["status"] = "Issued"
	else:
		values.update(
			{"status": "Received" if qty_after else "Rejected", "open_issue": None, "current_party": None}
		)
	if row.to_colour and row.new_item_code:
		values.update({"colour": row.to_colour, "item_code": row.new_item_code})
	bundle.update(values)
	add_movement(
		bundle, receive.production_process, receive.production_process, receive.doctype, receive.name, fresh
	)
	save_bundle(bundle)


def restore(bundle, row, doctype: str, name: str) -> None:
	"""Put the bundle back as it was before the document and drop that document's movement rows."""
	for row_field, bundle_field in SNAPSHOT_FIELDS.items():
		if row.meta.has_field(row_field):
			bundle.set(bundle_field, row.get(row_field))
	bundle.set(
		"history", [h for h in bundle.history if not (h.document_type == doctype and h.document_name == name)]
	)
	save_bundle(bundle)


# ----------------------------------------------------------------------------------------------
# Cancel guards
# ----------------------------------------------------------------------------------------------


def later_use(bundles: list[str], doctype: str, name: str, created) -> str | None:
	"""A submitted Process Issue / Receive / Packing List created after `name` that uses these bundles."""
	if not bundles:
		return None
	checks = (
		("Process Issue", "Process Issue Bundle", "bundle"),
		("Process Receive", "Process Receive Bundle", "bundle"),
		("Packing List", "Packing List Bundle", "bundle"),
	)
	for parent_type, child_type, field in checks:
		parent = frappe.qb.DocType(parent_type)
		child = frappe.qb.DocType(child_type)
		rows = (
			frappe.qb.from_(child)
			.inner_join(parent)
			.on(parent.name == child.parent)
			.select(parent.name, child[field])
			.where(
				(parent.docstatus == 1)
				& (child.parenttype == parent_type)
				& child[field].isin(bundles)
				& (parent.name != name)
				& (parent.creation > created)
			)
			.limit(1)
			.run()
		)
		if rows:
			return _("bundle {0} is already on {1} {2}").format(rows[0][1], _(parent_type), rows[0][0])
	return None


def receives_against_issue(issue: str) -> list[str]:
	pr = frappe.qb.DocType("Process Receive")
	prb = frappe.qb.DocType("Process Receive Bundle")
	return [
		r[0]
		for r in frappe.qb.from_(prb)
		.inner_join(pr)
		.on(pr.name == prb.parent)
		.select(pr.name)
		.distinct()
		.where((pr.docstatus == 1) & (prb.process_issue == issue) & (prb.parenttype == "Process Receive"))
		.run()
	]


def posting_date_check(posting_date, label: str) -> None:
	if posting_date and getdate(posting_date) > getdate():
		frappe.throw(_("{0} cannot be in the future.").format(label))
