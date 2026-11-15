"""Bundles: size-wise groups of good cut pieces with a barcode ticket (the barcode is the bundle name)."""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cint, now_datetime

from velocity_ctp.cutting import code128
from velocity_ctp.cutting.settings import get_settings
from velocity_ctp.cutting.stock import CUTTING_PROCESS, get_cutting_wip

TICKET_FORMATS = {"A4 sheet": "a4", "Thermal 4x2 inch": "thermal"}


def get_bundle_size() -> int:
	size = cint(get_settings().default_bundle_size)
	return size if size > 0 else 20


def split_into_bundles(qty: int, bundle_size: int) -> list[int]:
	"""[20, 20, 7] for 47 pieces in bundles of 20: the last bundle takes the remainder."""
	qty = cint(qty)
	if qty <= 0:
		return []
	full, remainder = divmod(qty, bundle_size)
	return [bundle_size] * full + ([remainder] if remainder else [])


def create_bundles(cut_receive) -> int:
	"""Create bundles for the good pieces of a submitted Cut Receive. Returns the number created."""
	bundle_size = get_bundle_size()
	wip = get_cutting_wip(cut_receive.company)
	styles = dict(
		frappe.get_all(
			"Garment Order",
			filters={"name": ("in", list({p.garment_order for p in cut_receive.pieces}))},
			fields=["name", "style"],
			as_list=True,
		)
	)

	# Group good pieces per order + colour + size (a Cut Receive may list the same line twice).
	lines: dict[tuple[str, str, str], dict] = {}
	for row in cut_receive.pieces:
		good = cint(row.cut_qty) - cint(row.rejected_qty)
		if good <= 0:
			continue
		key = (row.garment_order, row.colour, row.size)  # order colour
		line = lines.setdefault(
			key, {"item_code": row.item_code, "cut_colour": row.get("cut_colour") or row.colour, "qty": 0}
		)
		line["qty"] += good

	created = 0
	total_in_bundles = 0
	now = now_datetime()
	for (order, colour, size), line in lines.items():
		parts = split_into_bundles(line["qty"], bundle_size)
		for number, qty in enumerate(parts, start=1):
			bundle = frappe.get_doc(
				{
					"doctype": "Bundle",
					"cut_receive": cut_receive.name,
					"job_map": cut_receive.job_map,
					"garment_order": order,
					"style": styles.get(order),
					"colour": line["cut_colour"],
					"order_colour": colour,
					"size": size,
					"item_code": line["item_code"],
					"qty": qty,
					"cut_qty": qty,
					"bundle_no_in_lot": number,
					"bundles_in_lot": len(parts),
					"current_process": CUTTING_PROCESS,
					"current_warehouse": wip,
					"status": "In Cutting",
					"history": [
						{
							"datetime": now,
							"from_process": None,
							"to_process": CUTTING_PROCESS,
							"document_type": "Cut Receive",
							"document_name": cut_receive.name,
							"qty": qty,
							"user": frappe.session.user,
						}
					],
				}
			)
			bundle.flags.ignore_permissions = True
			bundle.insert()
			created += 1
			total_in_bundles += qty

	good_total = sum(line["qty"] for line in lines.values())
	if total_in_bundles != good_total:
		# Should never happen; stop rather than leave stock and bundles out of step.
		frappe.throw(
			_("Bundle quantity {0} does not match the good cut quantity {1}.").format(
				total_in_bundles, good_total
			)
		)
	return created


def can_cancel_cut_receive(cut_receive: str) -> tuple[bool, str]:
	"""Whether a Cut Receive may be cancelled: none of its bundles may have moved beyond cutting.

	Later phases (stitching, washing, ...) extend this with their own checks.
	"""
	moved = frappe.get_all(
		"Bundle",
		filters={"cut_receive": cut_receive},
		or_filters={"status": ("!=", "In Cutting"), "current_process": ("!=", CUTTING_PROCESS)},
		pluck="name",
		limit=5,
	)
	if not moved:
		bm = frappe.qb.DocType("Bundle Movement")
		b = frappe.qb.DocType("Bundle")
		rows = (
			frappe.qb.from_(bm)
			.inner_join(b)
			.on(b.name == bm.parent)
			.select(bm.parent)
			.where((b.cut_receive == cut_receive) & (bm.parenttype == "Bundle"))
			.groupby(bm.parent)
			.having(Count(bm.name) > 1)
			.limit(5)
			.run()
		)
		moved = [r[0] for r in rows]
	if moved:
		return False, _(
			"Bundles {0} have already moved beyond cutting. Reverse those movements before cancelling."
		).format(", ".join(moved))
	return True, ""


def delete_bundles(cut_receive: str) -> int:
	names = frappe.get_all("Bundle", filters={"cut_receive": cut_receive}, pluck="name")
	for name in names:
		frappe.delete_doc("Bundle", name, ignore_permissions=True, force=True)
	return len(names)


def get_ticket_format(requested: str | None = None) -> str:
	"""'a4' or 'thermal': from the request (print dialog) or Velocity Settings."""
	requested = requested or frappe.form_dict.get("ticket_size")
	if requested in TICKET_FORMATS.values():
		return requested
	setting = get_settings().bundle_ticket_format
	return TICKET_FORMATS.get(setting, "a4")


def get_bundle_tickets(cut_receive: str, ticket_size: str | None = None) -> dict:
	"""Ticket data for the "Bundle Ticket" print format (exposed to Jinja through hooks)."""
	frappe.has_permission("Cut Receive", "print", cut_receive, throw=True)
	bundles = frappe.get_all(
		"Bundle",
		filters={"cut_receive": cut_receive},
		fields=[
			"name",
			"garment_order",
			"job_map",
			"style",
			"colour",
			"size",
			"qty",
			"bundle_no_in_lot",
			"bundles_in_lot",
		],
		order_by="garment_order asc, colour asc, size asc, bundle_no_in_lot asc",
	)
	style_names = dict(
		frappe.get_all(
			"Style",
			filters={"name": ("in", list({b.style for b in bundles if b.style}))},
			fields=["name", "style_name"],
			as_list=True,
		)
	)
	totals: dict[str, int] = defaultdict(int)
	for bundle in bundles:
		bundle.style_name = style_names.get(bundle.style) or ""
		bundle.barcode = code128.svg(bundle.name, height=50)
		totals[bundle.garment_order] += cint(bundle.qty)
	return {"format": get_ticket_format(ticket_size), "tickets": bundles, "total_qty": sum(totals.values())}
