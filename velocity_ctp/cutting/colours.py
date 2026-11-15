"""Order colour and cut colour.

Buyers order the final colour (for example "Washed Light"); fabric is cut in a base colour (for example
"Dark Indigo") and the order colour appears after washing. A Garment Order maps order colours to cut
colours (Cut Colours table); an unmapped colour is cut in the order colour.

Order colours are the planning key everywhere (markers, cut pieces, over-cut checks, packing, delivery).
Pieces are produced in the cut colour (Cut Receive variants, Bundle.colour) and a colour-change process
(washing) converts each bundle to its order colour (Bundle.order_colour).
"""

from __future__ import annotations

import frappe


def colour_maps(orders: list[str]) -> dict[tuple[str, str], str]:
	"""{(garment_order, order colour lower): cut colour} for the given orders."""
	if not orders:
		return {}
	return {
		(parent, (order_colour or "").lower()): cut_colour
		for parent, order_colour, cut_colour in frappe.db.sql(
			"""select parent, order_colour, cut_colour from `tabGarment Order Colour Map`
			where parenttype = 'Garment Order' and parent in %(o)s""",
			{"o": orders},
		)
		if cut_colour
	}


def cut_colour(garment_order: str, order_colour: str) -> str:
	"""The colour an order colour is cut in (the order colour itself when not mapped)."""
	return colour_maps([garment_order]).get((garment_order, (order_colour or "").lower())) or order_colour


def order_colours(garment_order: str) -> dict[str, str]:
	"""{colour lower: colour} of the order's quantity matrix."""
	return {
		c.lower(): c
		for c in frappe.get_all(
			"Garment Order Item",
			filters={"parent": garment_order, "parenttype": "Garment Order"},
			pluck="colour",
		)
		if c
	}
