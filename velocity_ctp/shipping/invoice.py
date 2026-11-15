"""Commercial Invoice: standard Sales Invoice with export fields (custom fields, fixtures).

- Made from the Delivery Note with ERPNext's mapping; the Garment Order, the Packing Lists, cartons and
  weights are carried from the Delivery Note(s).
- Export invoices need the LC / contract no., shipment type and destination on submit; the invoice
  currency must be the Sales Order's currency.
- With "Require Gate Outward for Delivery" (Velocity Settings), every Delivery Note on the invoice needs
  a submitted Gate Outward before the invoice can be submitted.
- Agent commission uses ERPNext's Sales Partner and commission rate.
"""

from __future__ import annotations

from collections import OrderedDict

import frappe
from frappe import _
from frappe.utils import cint, flt


def delivery_notes_of(doc) -> list[str]:
	return list(OrderedDict.fromkeys(r.delivery_note for r in doc.items if r.get("delivery_note")))


def sales_invoice_before_validate(doc, method=None) -> None:
	if doc.docstatus != 0 or doc.get("is_return"):
		return
	notes = delivery_notes_of(doc)
	if not notes:
		return
	if not doc.get("garment_order"):
		doc.garment_order = frappe.db.get_value("Delivery Note", notes[0], "garment_order")
	if not doc.get("packing_lists"):
		for row in frappe.get_all(
			"Shipment Packing List",
			filters={"parenttype": "Delivery Note", "parent": ("in", notes)},
			fields=["packing_list", "total_pcs", "total_cartons", "net_weight", "gross_weight"],
			order_by="parent, idx",
		):
			doc.append("packing_lists", row)
	rows = doc.get("packing_lists") or []
	if rows:
		doc.total_cartons = sum(cint(r.total_cartons) for r in rows)
		doc.net_weight = flt(sum(flt(r.net_weight) for r in rows), 3) or doc.get("net_weight")
		doc.gross_weight = flt(sum(flt(r.gross_weight) for r in rows), 3) or doc.get("gross_weight")


def sales_invoice_validate(doc, method=None) -> None:
	if doc.get("is_return"):
		return
	orders = list({r.sales_order for r in doc.items if r.get("sales_order")})
	for so in orders:
		currency = frappe.db.get_value("Sales Order", so, "currency")
		if currency and currency != doc.currency:
			frappe.throw(
				_("The invoice currency {0} is not the currency {1} of Sales Order {2}.").format(
					frappe.bold(doc.currency), frappe.bold(currency), so
				),
				title=_("Currency Mismatch"),
			)


EXPORT_REQUIRED = (
	("lc_contract_no", "LC / Contract No."),
	("shipment_type", "Shipment Type"),
	("destination", "Destination"),
)


def sales_invoice_before_submit(doc, method=None) -> None:
	if doc.get("is_return"):
		return
	if doc.get("invoice_category") == "Export":
		missing = [_(label) for field, label in EXPORT_REQUIRED if not doc.get(field)]
		if missing:
			frappe.throw(
				_("An Export invoice needs {0} before it is submitted.").format(", ".join(missing)),
				title=_("Export Details Missing"),
			)
	from velocity_ctp.cutting.settings import get_settings

	if cint(get_settings().require_gate_outward_for_delivery):
		without = [
			dn
			for dn in delivery_notes_of(doc)
			if not frappe.db.exists(
				"Gate Outward", {"docstatus": 1, "reference_doctype": "Delivery Note", "reference_name": dn}
			)
		]
		if without:
			frappe.throw(
				_("Delivery Note(s) {0} have not left the gate yet: submit their Gate Outward first.").format(
					", ".join(without)
				),
				title=_("Gate Outward Required"),
			)


# ----------------------------------------------------------------------------------------------
# Print helpers (Commercial Invoice, Proforma Invoice)
# ----------------------------------------------------------------------------------------------


def get_invoice_lines(doc) -> list[dict]:
	"""Lines by style and colour: sizes, quantity, rate and amount (in the document currency)."""
	items = [r.item_code for r in doc.items]
	attributes: dict[str, dict] = {}
	for parent, attribute, value in frappe.db.sql(
		"""select parent, attribute, attribute_value from `tabItem Variant Attribute`
		where parent in %(i)s""",
		{"i": items or [""]},
	):
		attributes.setdefault(parent, {})[attribute] = value
	templates = dict(
		frappe.get_all(
			"Item", filters={"name": ("in", items or [""])}, fields=["name", "variant_of"], as_list=True
		)
	)
	lines: OrderedDict = OrderedDict()
	for row in doc.items:
		attrs = attributes.get(row.item_code, {})
		style = templates.get(row.item_code) or row.item_code
		colour = attrs.get("Colour") or ""
		line = lines.setdefault(
			(style, colour),
			{
				"style": style,
				"style_name": frappe.get_cached_value("Item", style, "item_name") if style else "",
				"colour": colour,
				"sizes": [],
				"qty": 0.0,
				"amount": 0.0,
				"uom": row.uom,
				"hs_code": frappe.get_cached_value("Item", row.item_code, "customs_tariff_number") or "",
			},
		)
		size = attrs.get("Size")
		if size and size not in line["sizes"]:
			line["sizes"].append(size)
		line["qty"] += flt(row.qty)
		line["amount"] += flt(row.amount)
	result = []
	for line in lines.values():
		line["rate"] = flt(line["amount"] / line["qty"], 4) if line["qty"] else 0
		line["sizes"] = ", ".join(line["sizes"])
		result.append(line)
	return result
