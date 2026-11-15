"""Gate passes (no stock effect): Gate Outward and Gate Inward.

- Outward types Delivery, Process Challan and Purchase Return need a submitted reference (Delivery Note,
  Process Issue, Purchase Return receipt) and cannot exceed its quantities per item; Sample, Repair and
  Other go through the approval workflow (Velocity Gate Approver, no self-approval).
- Returnable outward rows stay open until Gate Inward rows (return_against) bring the quantity back;
  partial returns are allowed.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

REFERENCE_TYPES = {
	"Delivery": "Delivery Note",
	"Process Challan": "Process Issue",
	"Purchase Return": "Purchase Receipt",
}
APPROVAL_TYPES = ("Sample", "Repair", "Other")
EPS = 1e-9


def reference_items(doctype: str, name: str) -> list[dict]:
	"""Items of a reference document: {item_code, description, uom, qty}, one row per item."""
	rows: dict[str, dict] = {}
	if doctype == "Delivery Note":
		source = frappe.get_all(
			"Delivery Note Item",
			filters={"parent": name, "parenttype": doctype},
			fields=["item_code", "item_name as description", "stock_uom as uom", "stock_qty as qty"],
			order_by="idx",
		)
	elif doctype == "Process Issue":
		source = frappe.get_all(
			"Process Issue Bundle",
			filters={"parent": name, "parenttype": doctype},
			fields=["item_code", "qty"],
			order_by="idx",
		)
		for r in source:
			r.uom = frappe.get_cached_value("Item", r.item_code, "stock_uom")
			r.description = frappe.get_cached_value("Item", r.item_code, "item_name")
	elif doctype == "Purchase Receipt":
		source = frappe.get_all(
			"Purchase Receipt Item",
			filters={"parent": name, "parenttype": doctype},
			fields=["item_code", "item_name as description", "stock_uom as uom", "stock_qty as qty"],
			order_by="idx",
		)
	else:
		return []
	for r in source:
		line = rows.setdefault(
			r.item_code, {"item_code": r.item_code, "description": r.description, "uom": r.uom, "qty": 0.0}
		)
		line["qty"] += abs(flt(r.qty))
	return list(rows.values())


def reference_party(doctype: str, name: str) -> tuple[str | None, str | None]:
	if doctype == "Delivery Note":
		return "Customer", frappe.db.get_value(doctype, name, "customer")
	if doctype == "Process Issue":
		return (
			("Supplier", frappe.db.get_value(doctype, name, "party"))
			if frappe.db.get_value(doctype, name, "party")
			else (None, None)
		)
	if doctype == "Purchase Receipt":
		return "Supplier", frappe.db.get_value(doctype, name, "supplier")
	return None, None


def passed_qty(doctype: str, name: str, exclude: str | None = None) -> dict[str, float]:
	"""{item: qty} already on submitted Gate Outwards for a reference document."""
	result: dict[str, float] = defaultdict(float)
	for item, qty in frappe.db.sql(
		"""select goi.item_code, sum(goi.qty) from `tabGate Outward Item` goi
		join `tabGate Outward` go on go.name = goi.parent
		where go.docstatus = 1 and go.reference_doctype = %s and go.reference_name = %s and go.name != %s
		group by goi.item_code""",
		(doctype, name, exclude or ""),
	):
		result[item] += flt(qty)
	return result


def validate_outward(doc) -> None:
	reference_type = REFERENCE_TYPES.get(doc.gate_pass_type)
	if reference_type:
		if doc.reference_doctype != reference_type or not doc.reference_name:
			frappe.throw(
				_("A {0} gate pass needs a submitted {1} as its reference.").format(
					_(doc.gate_pass_type), _(reference_type)
				),
				title=_("Reference Required"),
			)
		ref = frappe.db.get_value(reference_type, doc.reference_name, ["docstatus"], as_dict=True)
		if not ref or ref.docstatus != 1:
			frappe.throw(
				_("{0} {1} is not submitted.").format(_(reference_type), frappe.bold(doc.reference_name))
			)
		if reference_type == "Purchase Receipt" and not frappe.db.get_value(
			reference_type, doc.reference_name, "is_return"
		):
			frappe.throw(_("{0} is not a Purchase Return.").format(frappe.bold(doc.reference_name)))
		party_type, party = reference_party(reference_type, doc.reference_name)
		if party and not doc.party:
			doc.party_type, doc.party = party_type, party
		allowed = {r["item_code"]: r["qty"] for r in reference_items(reference_type, doc.reference_name)}
		used = passed_qty(reference_type, doc.reference_name, exclude=doc.name)
		entered: dict[str, float] = defaultdict(float)
		for row in doc.items:
			if not row.item_code:
				frappe.throw(_("Row {0}: select the item from {1}.").format(row.idx, doc.reference_name))
			if row.item_code not in allowed:
				frappe.throw(
					_("Row {0}: {1} is not on {2}.").format(
						row.idx, frappe.bold(row.item_code), doc.reference_name
					)
				)
			entered[row.item_code] += flt(row.qty)
		for item, qty in entered.items():
			left = allowed[item] - used.get(item, 0.0)
			if qty > left + EPS:
				frappe.throw(
					_("{0}: {1} of {2} is left to pass on {3} ({4} already passed); {5} is entered.").format(
						frappe.bold(item),
						f"{max(left, 0):g}",
						f"{allowed[item]:g}",
						doc.reference_name,
						f"{used.get(item, 0):g}",
						f"{qty:g}",
					),
					title=_("More Than the Reference"),
				)
	for row in doc.items:
		if not row.item_code and not (row.description or "").strip():
			frappe.throw(_("Row {0}: enter an item or a description.").format(row.idx))
		if row.item_code and not row.uom:
			row.uom = frappe.get_cached_value("Item", row.item_code, "stock_uom")
		if row.item_code and not row.description:
			row.description = frappe.get_cached_value("Item", row.item_code, "item_name")
		if flt(row.qty) <= 0:
			frappe.throw(_("Row {0}: Qty must be greater than zero.").format(row.idx))
		if row.returnable and not row.expected_return_date:
			frappe.throw(
				_("Row {0}: please enter the expected return date of the returnable item.").format(row.idx)
			)
		if not row.returnable:
			row.expected_return_date = None


def open_returnables(
	gate_outward: str | None = None, exclude_inward: str | None = None
) -> list[frappe._dict]:
	"""Open returnable rows of submitted Gate Outwards: qty - returned (Gate Inwards except `exclude_inward`)."""
	conditions = ["go.docstatus = 1", "goi.returnable = 1"]
	values: dict = {"exclude": exclude_inward or ""}
	if gate_outward:
		conditions.append("go.name = %(go)s")
		values["go"] = gate_outward
	rows = frappe.db.sql(
		f"""select go.name as gate_outward, go.party_type, go.party, go.entry_date, go.gate_pass_type, goi.name as row_name,
			goi.item_code, goi.description, goi.uom, goi.qty, goi.expected_return_date,
			ifnull((select sum(gii.qty) from `tabGate Inward Item` gii join `tabGate Inward` gi on gi.name = gii.parent
				where gi.docstatus = 1 and gii.return_against = goi.name and gi.name != %(exclude)s), 0) as returned
		from `tabGate Outward Item` goi join `tabGate Outward` go on go.name = goi.parent
		where {" and ".join(conditions)} order by go.entry_date, go.name, goi.idx""",
		values,
		as_dict=True,
	)
	for r in rows:
		r.open_qty = flt(r.qty) - flt(r.returned)
	return [r for r in rows if r.open_qty > EPS]


def validate_inward(doc) -> None:
	returns = [r for r in doc.items if r.return_against]
	if doc.gate_pass_type == "Repair Return" and not returns:
		frappe.throw(
			_("A Repair Return brings back returnable items: use Get Returnable Items on the Gate Outward.")
		)
	if returns:
		open_rows = {r.row_name: r for r in open_returnables(exclude_inward=doc.name)}
		entered: dict[str, float] = defaultdict(float)
		for row in returns:
			entered[row.return_against] += flt(row.qty)
		for row_name, qty in entered.items():
			src = open_rows.get(row_name)
			if not src:
				frappe.throw(_("A returned row is not an open returnable item of a submitted Gate Outward."))
			if qty > src.open_qty + EPS:
				frappe.throw(
					_("{0} on {1}: {2} is still out; {3} is entered.").format(
						frappe.bold(src.item_code or src.description),
						src.gate_outward,
						f"{src.open_qty:g}",
						f"{qty:g}",
					),
					title=_("More Than Sent Out"),
				)
	for row in doc.items:
		if not row.item_code and not (row.description or "").strip():
			frappe.throw(_("Row {0}: enter an item or a description.").format(row.idx))
		if flt(row.qty) <= 0:
			frappe.throw(_("Row {0}: Qty must be greater than zero.").format(row.idx))


def refresh_returned(gate_outwards: list[str]) -> None:
	"""Returned quantity on the outward rows and the open returnable total on each Gate Outward."""
	for name in set(filter(None, gate_outwards)):
		rows = frappe.get_all(
			"Gate Outward Item",
			filters={"parent": name, "parenttype": "Gate Outward"},
			fields=["name", "qty", "returnable"],
		)
		open_total = 0.0
		for row in rows:
			returned = flt(
				frappe.db.sql(
					"""select ifnull(sum(gii.qty), 0) from `tabGate Inward Item` gii join `tabGate Inward` gi on gi.name = gii.parent
					where gi.docstatus = 1 and gii.return_against = %s""",
					row.name,
				)[0][0]
			)
			frappe.db.set_value(
				"Gate Outward Item", row.name, "returned_qty", returned, update_modified=False
			)
			if row.returnable:
				open_total += max(flt(row.qty) - returned, 0)
		frappe.db.set_value("Gate Outward", name, "open_returnable_qty", open_total, update_modified=False)


@frappe.whitelist()
def get_reference_items(reference_doctype: str, reference_name: str) -> dict:
	"""Rows still to pass for a reference document (Gate Outward pre-fill)."""
	frappe.has_permission("Gate Outward", "read", throw=True)
	used = passed_qty(reference_doctype, reference_name)
	items = []
	for r in reference_items(reference_doctype, reference_name):
		left = r["qty"] - used.get(r["item_code"], 0)
		if left > EPS:
			items.append({**r, "qty": left})
	party_type, party = reference_party(reference_doctype, reference_name)
	values = {}
	if reference_doctype == "Process Issue":
		values = (
			frappe.db.get_value("Process Issue", reference_name, ["vehicle_no", "driver_name"], as_dict=True)
			or {}
		)
	return {"items": items, "party_type": party_type, "party": party, **values}


@frappe.whitelist()
def get_returnable_items(gate_outward: str) -> list[dict]:
	frappe.has_permission("Gate Inward", "read", throw=True)
	return [
		{
			"item_code": r.item_code,
			"description": r.description,
			"uom": r.uom,
			"qty": r.open_qty,
			"return_against": r.row_name,
			"gate_outward": r.gate_outward,
		}
		for r in open_returnables(gate_outward)
	]
