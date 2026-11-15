"""Velocity rules on standard ERPNext buying documents (doc_events in hooks.py).

Nothing here replaces ERPNext buying logic: these hooks only add the Velocity fields and checks.

- Material Request: items match the request category; rejection reason when the approver rejects.
- Purchase Order: items match the PO category; Shortfall POs need a reason and a Garment Order on every
  row; the category and Garment Order are carried forward from the Material Request (and its Material
  Plan); approver names and dates are recorded for the print; after submit only "Velocity PO Approver
  L1" may change items, rates or quantities (Update Items, through override_whitelisted_methods).
- Purchase Receipt: Garment Order / Job Map from the PO row; fabric rows need the supplier lot and shade,
  and one new Batch is created per fabric lot (ERPNext's Batch document) with shade and lot on it; a row
  with an Accepted inspection must have the inspection's rejected quantity as its rejected quantity.
- Quality Inspection (incoming, on a Purchase Receipt row): Accepted = the lot is usable, possibly with a
  partial rejection (rejected_qty below the lot); Rejected = the whole lot is refused (rejected_qty = the
  lot). A rejected quantity needs a reason.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from velocity_ctp.procurement.common import (
	APPROVED,
	CATEGORY_GROUPS,
	FABRIC_GROUP,
	MR_PENDING,
	MR_REJECTED,
	PO_APPROVER_L1,
	PO_APPROVER_L2,
	PO_DRAFT,
	PO_PENDING_1,
	PO_PENDING_2,
	REQUISITION_APPROVER,
	items_in_group,
)

# ----------------------------------------------------------------------------------------------
# Rejection reason (workflow)
# ----------------------------------------------------------------------------------------------

# doctype -> (pending states, state after a rejection, roles that may reject)
REJECTION_RULES = {
	"Material Request": ((MR_PENDING,), MR_REJECTED, (REQUISITION_APPROVER,)),
	"Purchase Order": ((PO_PENDING_1, PO_PENDING_2), PO_DRAFT, (PO_APPROVER_L1, PO_APPROVER_L2)),
}


def track_rejection(doc) -> None:
	"""A rejection needs a reason (stored by set_rejection_reason before the workflow action).

	Sending the document for approval again clears the previous reason.
	"""
	pending, rejected, _roles = REJECTION_RULES[doc.doctype]
	before = doc.get_doc_before_save()
	old, new = (before.get("workflow_state") if before else None), doc.get("workflow_state")
	if old == new:
		return
	if old in pending and new == rejected:
		if not (doc.get("rejection_reason") or "").strip():
			frappe.throw(_("Please enter the reason for the rejection."), title=_("Reason Required"))
		doc.add_comment(
			"Comment",
			_("Rejected by {0} at {1}. Reason: {2}").format(
				frappe.utils.get_fullname(frappe.session.user), _(old), doc.rejection_reason
			),
		)
	elif new in pending and old not in pending:
		doc.rejection_reason = None


@frappe.whitelist(methods=["POST"])
def set_rejection_reason(doctype: str, name: str, reason: str) -> None:
	"""Store the reason before the Reject action (the workflow action reloads the document from the database)."""
	if doctype not in REJECTION_RULES:
		frappe.throw(_("Rejection reasons are not used for {0}.").format(_(doctype)))
	pending, _rejected, roles = REJECTION_RULES[doctype]
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	if doc.get("workflow_state") not in pending:
		frappe.throw(_("{0} {1} is not waiting for approval.").format(_(doctype), frappe.bold(name)))
	if not set(roles) & set(frappe.get_roles()):
		frappe.throw(_("Only an approver can reject {0}.").format(_(doctype)), frappe.PermissionError)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Please enter the reason for the rejection."), title=_("Reason Required"))
	doc.db_set("rejection_reason", reason, update_modified=False)


# ----------------------------------------------------------------------------------------------
# Material Request
# ----------------------------------------------------------------------------------------------


def material_request_validate(doc, method=None) -> None:
	if doc.material_request_type == "Purchase" and doc.get("request_category"):
		validate_category(doc, doc.request_category, "Material Request")
	if doc.get("workflow_state"):
		track_rejection(doc)


def validate_category(doc, category: str, label: str) -> None:
	group = CATEGORY_GROUPS.get(category)
	if not group:
		return
	membership = items_in_group([r.item_code for r in doc.items], group)
	for row in doc.items:
		if row.item_code and not membership.get(row.item_code):
			frappe.throw(
				_(
					"Row {0}: {1} is not in the {2} item group. A {3} with category {4} can only contain {2} items."
				).format(row.idx, frappe.bold(row.item_code), frappe.bold(_(group)), _(label), _(category)),
				title=_("Wrong Item Group"),
			)


# ----------------------------------------------------------------------------------------------
# Purchase Order
# ----------------------------------------------------------------------------------------------


def purchase_order_before_validate(doc, method=None) -> None:
	if doc.docstatus == 0:
		carry_from_material_requests(doc)


def carry_from_material_requests(doc) -> None:
	"""PO category from the requests' category; Garment Order and Job Map from the request's Material Plan."""
	requests = list({r.material_request for r in doc.items if r.get("material_request")})
	if not requests:
		return
	info = {
		r.name: r
		for r in frappe.get_all(
			"Material Request",
			filters={"name": ("in", requests)},
			fields=["name", "request_category", "material_plan"],
		)
	}
	categories = {info[m].request_category for m in requests if m in info}
	if not doc.get("po_category") and len(categories) == 1 and None not in categories:
		doc.po_category = categories.pop()

	plans = [i.material_plan for i in info.values() if i.material_plan]
	if not plans:
		return
	from velocity_ctp.velocity_ctp.doctype.material_plan.material_plan import job_maps_of_orders

	plan_order = dict(
		frappe.get_all(
			"Material Plan", filters={"name": ("in", plans)}, fields=["name", "garment_order"], as_list=True
		)
	)
	job_maps = job_maps_of_orders(list(set(plan_order.values())))
	for row in doc.items:
		plan = info.get(row.get("material_request"), frappe._dict()).get("material_plan")
		order = plan_order.get(plan)
		if order and not row.get("garment_order"):
			row.garment_order = order
		if row.get("garment_order") and not row.get("job_map"):
			row.job_map = job_maps.get(row.garment_order)


@frappe.whitelist()
def get_request_category(material_requests: str | list) -> str | None:
	"""The common request category of the Material Requests (None if they differ or have none)."""
	frappe.has_permission("Purchase Order", "create", throw=True)
	names = frappe.parse_json(material_requests) or []
	categories = set(
		frappe.get_all("Material Request", filters={"name": ("in", names)}, pluck="request_category")
	)
	return categories.pop() if len(categories) == 1 else None


def purchase_order_validate(doc, method=None) -> None:
	if doc.get("po_category"):
		validate_category(doc, doc.po_category, "Purchase Order")
	if doc.get("po_type") == "Shortfall":
		if not (doc.get("shortfall_reason") or "").strip():
			frappe.throw(
				_("Please enter the shortfall reason for a Shortfall Purchase Order."),
				title=_("Reason Required"),
			)
		missing = [str(r.idx) for r in doc.items if not r.get("garment_order")]
		if missing:
			frappe.throw(
				_(
					"A Shortfall Purchase Order needs a Garment Order on every row. Missing on row(s): {0}."
				).format(", ".join(missing)),
				title=_("Garment Order Required"),
			)
	validate_row_orders(doc)
	if doc.get("workflow_state"):
		record_approvals(doc)
		track_rejection(doc)


def validate_row_orders(doc) -> None:
	"""A row's Job Map must contain its Garment Order."""
	pairs = {(r.garment_order, r.job_map) for r in doc.items if r.get("garment_order") and r.get("job_map")}
	if not pairs:
		return
	known = set(
		frappe.get_all(
			"Job Map Order",
			filters={"parenttype": "Job Map", "parent": ("in", [p[1] for p in pairs])},
			fields=["garment_order", "parent"],
			as_list=True,
		)
	)
	for row in doc.items:
		if row.get("garment_order") and row.get("job_map") and (row.garment_order, row.job_map) not in known:
			frappe.throw(
				_("Row {0}: Garment Order {1} is not on Job Map {2}.").format(
					row.idx, frappe.bold(row.garment_order), frappe.bold(row.job_map)
				)
			)


def record_approvals(doc) -> None:
	"""Approver names and dates for the print. Cleared when the PO goes back to Draft."""
	before = doc.get_doc_before_save()
	old, new = (before.get("workflow_state") if before else None), doc.workflow_state
	if old == new:
		return
	user, now = frappe.session.user, now_datetime()
	if old == PO_PENDING_1 and new in (PO_PENDING_2, APPROVED):
		doc.l1_approved_by, doc.l1_approved_on = user, now
	elif old == PO_PENDING_2 and new == APPROVED:
		doc.l2_approved_by, doc.l2_approved_on = user, now
	elif new == PO_DRAFT:
		doc.l1_approved_by = doc.l1_approved_on = doc.l2_approved_by = doc.l2_approved_on = None


@frappe.whitelist()
def update_child_qty_rate(
	parent_doctype: str, trans_items: str, parent_doctype_name: str, child_docname: str = "items"
):
	"""ERPNext "Update Items", with one Velocity rule: on a Purchase Order only "Velocity PO Approver L1"
	may add or remove items or change items, rates or quantities. Other users can still change dates.
	Registered in hooks.py (override_whitelisted_methods); ERPNext's own function does the update."""
	from erpnext.controllers.accounts_controller import update_child_qty_rate as erpnext_update_child_qty_rate

	if parent_doctype == "Purchase Order" and PO_APPROVER_L1 not in frappe.get_roles():
		validate_po_item_changes(parent_doctype_name, trans_items)
	return erpnext_update_child_qty_rate(parent_doctype, trans_items, parent_doctype_name, child_docname)


def validate_po_item_changes(purchase_order: str, trans_items: str | list) -> None:
	rows = frappe.parse_json(trans_items) or []
	current = {
		r.name: r
		for r in frappe.get_all(
			"Purchase Order Item",
			filters={"parent": purchase_order, "parenttype": "Purchase Order"},
			fields=["name", "item_code", "qty", "rate", "uom", "conversion_factor"],
		)
	}

	def differs(row, old) -> bool:
		return (
			row.get("item_code") != old.item_code
			or flt(row.get("qty"), 6) != flt(old.qty, 6)
			or flt(row.get("rate"), 6) != flt(old.rate, 6)
			or (row.get("uom") or old.uom) != old.uom
			or flt(row.get("conversion_factor") or old.conversion_factor, 6) != flt(old.conversion_factor, 6)
		)

	sent = {r.get("docname") for r in rows}
	added_or_removed = bool(set(current) - sent) or any(r.get("docname") not in current for r in rows)
	if added_or_removed or any(differs(r, current[r["docname"]]) for r in rows):
		frappe.throw(
			_(
				"Only a user with the role {0} can add or remove items or change items, rates or quantities on an "
				"approved Purchase Order. Required-by dates can still be updated."
			).format(frappe.bold(PO_APPROVER_L1)),
			frappe.PermissionError,
			title=_("Approval Needed"),
		)


# ----------------------------------------------------------------------------------------------
# Purchase Receipt
# ----------------------------------------------------------------------------------------------


def purchase_receipt_before_validate(doc, method=None) -> None:
	if doc.docstatus != 0:
		return
	po_rows = [r.purchase_order_item for r in doc.items if r.get("purchase_order_item")]
	if po_rows:
		source = {
			r.name: r
			for r in frappe.get_all(
				"Purchase Order Item",
				filters={"name": ("in", po_rows)},
				fields=["name", "garment_order", "job_map"],
			)
		}
		for row in doc.items:
			src = source.get(row.get("purchase_order_item"))
			if src:
				row.garment_order = row.get("garment_order") or src.garment_order
				row.job_map = row.get("job_map") or src.job_map
	if not doc.is_return:
		rejection_store = frappe.db.get_value(
			"Warehouse", {"warehouse_name": "Rejection Store", "company": doc.company}, "name"
		)
		for row in doc.items:
			if flt(row.rejected_qty) and not row.rejected_warehouse and rejection_store:
				row.rejected_warehouse = rejection_store


def fabric_rows(doc) -> list:
	membership = items_in_group([r.item_code for r in doc.items], FABRIC_GROUP)
	return [r for r in doc.items if membership.get(r.item_code)]


def purchase_receipt_validate(doc, method=None) -> None:
	if doc.is_return:
		return
	validate_inspection_rejections(doc)
	lots: dict[tuple[str, str], set] = defaultdict(set)
	for row in fabric_rows(doc):
		missing = [
			label
			for field, label in (("supplier_lot_no", _("Supplier Lot No")), ("shade", _("Shade")))
			if not (row.get(field) or "").strip()
		]
		if missing:
			frappe.throw(
				_("Row {0}: {1} is fabric, so {2} must be entered.").format(
					row.idx, frappe.bold(row.item_code), _(" and ").join(missing)
				),
				title=_("Lot and Shade Required"),
			)
		row.supplier_lot_no, row.shade = row.supplier_lot_no.strip(), row.shade.strip()
		lots[(row.item_code, row.supplier_lot_no)].add(row.shade)
		if row.get("batch_no"):
			batch = frappe.db.get_value("Batch", row.batch_no, ["supplier_lot_no", "shade"], as_dict=True)
			if batch and batch.supplier_lot_no and batch.supplier_lot_no != row.supplier_lot_no:
				frappe.throw(
					_(
						"Row {0}: Batch {1} is supplier lot {2}, not {3}. Leave the batch empty to create a new one."
					).format(row.idx, frappe.bold(row.batch_no), batch.supplier_lot_no, row.supplier_lot_no)
				)
	for (item, lot), shades in lots.items():
		if len(shades) > 1:
			frappe.throw(
				_(
					"Supplier lot {0} of {1} is entered with different shades ({2}). One lot has one shade."
				).format(frappe.bold(lot), frappe.bold(item), ", ".join(sorted(shades)))
			)


def purchase_receipt_before_submit(doc, method=None) -> None:
	"""Create one Batch per fabric lot (rows without a batch) and put it on the rows."""
	if doc.is_return:
		return
	created: dict[tuple[str, str], str] = {}
	for row in fabric_rows(doc):
		if row.get("batch_no") or row.get("serial_and_batch_bundle"):
			continue
		key = (row.item_code, row.supplier_lot_no)
		if key not in created:
			created[key] = make_lot_batch(doc, row)
		row.batch_no = created[key]
		row.use_serial_batch_fields = 1


def make_lot_batch(doc, row) -> str:
	"""ERPNext Batch for a supplier lot. Items that create their own batches use their batch series;
	otherwise the Batch ID is <item>-<lot> (with a counter if that ID is taken)."""
	values = {
		"doctype": "Batch",
		"item": row.item_code,
		"supplier": doc.supplier,
		"reference_doctype": doc.doctype,
		"reference_name": doc.name,
		"manufacturing_date": doc.posting_date,
		"supplier_lot_no": row.supplier_lot_no,
		"shade": row.shade,
	}
	if not cint(frappe.get_cached_value("Item", row.item_code, "create_new_batch")):
		base = f"{row.item_code}-{row.supplier_lot_no}".upper().replace(" ", "-")
		batch_id, n = base, 1
		while frappe.db.exists("Batch", batch_id):
			n += 1
			batch_id = f"{base}-{n}"
		values["batch_id"] = batch_id
	batch = frappe.get_doc(values)
	batch.flags.ignore_permissions = True
	batch.insert()
	return batch.name


def purchase_receipt_on_submit(doc, method=None) -> None:
	"""Existing batches chosen on a fabric row get the lot and shade if they had none."""
	if doc.is_return:
		return
	for row in fabric_rows(doc):
		if not row.get("batch_no"):
			continue
		current = frappe.db.get_value("Batch", row.batch_no, ["supplier_lot_no", "shade"], as_dict=True) or {}
		updates = {
			field: row.get(field)
			for field in ("supplier_lot_no", "shade")
			if not current.get(field) and row.get(field)
		}
		if updates:
			frappe.db.set_value("Batch", row.batch_no, updates)


# ----------------------------------------------------------------------------------------------
# Quality Inspection: partial rejection
# ----------------------------------------------------------------------------------------------


def qty_text(value) -> str:
	"""Quantity for messages: 96, 1296, 12.5 (no trailing .0)."""
	return f"{flt(value, 3):g}"


def receipt_row(qi) -> frappe._dict | None:
	if qi.reference_type != "Purchase Receipt" or not qi.child_row_reference:
		return None
	return frappe.db.get_value(
		"Purchase Receipt Item",
		{"name": qi.child_row_reference, "parent": qi.reference_name},
		["idx", "received_qty", "uom"],
		as_dict=True,
	)


def quality_inspection_validate(doc, method=None) -> None:
	"""Accepted with a rejected quantity = partial rejection (the rest of the lot is usable);
	Rejected = the whole lot is refused. A rejected quantity needs a reason."""
	rejected = flt(doc.get("rejected_qty"))
	row = receipt_row(doc)
	lot = flt(row.received_qty) if row else 0.0
	if doc.status == "Rejected" and not rejected and lot:
		doc.rejected_qty = rejected = lot  # the whole lot is refused
	if rejected < 0:
		frappe.throw(_("Rejected Qty cannot be negative."))
	if rejected and not (doc.get("rejection_reason") or "").strip():
		frappe.throw(
			_("Please enter the reason for rejecting {0} {1}.").format(
				qty_text(rejected), (row.uom if row else "") or _("units")
			),
			title=_("Reason Required"),
		)
	if not row or not lot:
		return
	if rejected > lot + 1e-9:
		frappe.throw(
			_("Rejected Qty {0} is more than the {1} received on row {2} of {3}.").format(
				qty_text(rejected), qty_text(lot), row.idx, doc.reference_name
			)
		)
	if doc.status == "Accepted" and rejected >= lot - 1e-9:
		frappe.throw(
			_(
				"The whole lot ({0}) is rejected, so the status must be Rejected. Keep Accepted only when part of "
				"the lot is rejected and the rest is usable."
			).format(qty_text(lot)),
			title=_("Whole Lot Rejected"),
		)
	if doc.status == "Rejected" and rejected < lot - 1e-9:
		frappe.throw(
			_(
				"Rejected means the whole lot ({0}) is refused, but {1} is entered. For a partial rejection keep the "
				"status Accepted and enter the rejected quantity."
			).format(qty_text(lot), qty_text(rejected)),
			title=_("Partial Rejection"),
		)


def validate_inspection_rejections(doc) -> None:
	"""A row with an Accepted inspection must reject exactly the inspection's rejected quantity."""
	names = [r.quality_inspection for r in doc.items if r.get("quality_inspection")]
	if not names:
		return
	inspections = {
		q.name: q
		for q in frappe.get_all(
			"Quality Inspection",
			filters={"name": ("in", names), "docstatus": ("<", 2)},
			fields=["name", "status", "rejected_qty"],
		)
	}
	for row in doc.items:
		qi = inspections.get(row.get("quality_inspection"))
		if not qi or qi.status != "Accepted":
			continue  # a Rejected inspection stops the receipt in ERPNext (whole lot refused)
		if abs(flt(row.rejected_qty) - flt(qi.rejected_qty)) > 1e-9:
			frappe.throw(
				_(
					"Row {0}: {1} has Rejected Quantity {2} on the receipt, but Quality Inspection {3} rejected {4}. "
					"They must be the same: correct the receipt row or the inspection."
				).format(
					row.idx,
					frappe.bold(row.item_code),
					qty_text(row.rejected_qty),
					frappe.bold(qi.name),
					qty_text(qi.rejected_qty),
				),
				title=_("Rejected Quantity Mismatch"),
			)
