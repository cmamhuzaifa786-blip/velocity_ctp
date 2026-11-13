"""Helpers for keeping ERPNext Item Attribute values in sync with Velocity CTP masters."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

import frappe
from frappe import _

SIZE_ATTRIBUTE = "Size"
COLOUR_ATTRIBUTE = "Colour"


def size_abbreviation(size: str) -> str:
	"""Sizes use the size itself as the abbreviation (for example 32 or XL)."""
	return size.strip()


def colour_abbreviation(colour: str) -> str:
	"""Build a short abbreviation from a colour name.

	One word -> first three letters ("Indigo" -> "IND").
	Several words -> initials, up to four ("Dark Stone Blue" -> "DSB").
	"""
	words = re.findall(r"[A-Za-z0-9]+", colour)
	if not words:
		return "CLR"
	if len(words) == 1:
		return words[0][:3].upper()
	return "".join(w[0] for w in words[:4]).upper()


def _unique_abbreviation(base: str, used: set[str]) -> str:
	abbr = base or "X"
	counter = 1
	while abbr.lower() in used:
		abbr = f"{base}{counter}"
		counter += 1
	return abbr


def ensure_attribute_values(
	attribute: str,
	values: Iterable[str],
	make_abbreviation: Callable[[str], str],
) -> dict[str, str]:
	"""Make sure every value exists on the given Item Attribute.

	Matching is case-insensitive. Missing values are appended with a unique abbreviation.
	Returns a mapping of each requested value (lower case) to the stored attribute value,
	so callers can pass the exact stored spelling to the variant API.
	"""
	if not frappe.db.exists("Item Attribute", attribute):
		frappe.throw(
			_(
				"Item Attribute {0} does not exist. Please run the Velocity CTP setup "
				"(velocity_ctp.setup.install.setup_masters) first."
			).format(frappe.bold(attribute))
		)

	doc = frappe.get_doc("Item Attribute", attribute)
	if doc.numeric_values:
		frappe.throw(
			_(
				"Item Attribute {0} uses numeric values. Velocity CTP requires a non-numeric attribute."
			).format(frappe.bold(attribute))
		)

	stored = {row.attribute_value.lower(): row.attribute_value for row in doc.item_attribute_values}
	used_abbrs = {(row.abbr or "").lower() for row in doc.item_attribute_values}

	added = False
	for value in values:
		value = (value or "").strip()
		if not value or value.lower() in stored:
			continue
		abbr = _unique_abbreviation(make_abbreviation(value), used_abbrs)
		doc.append("item_attribute_values", {"attribute_value": value, "abbr": abbr})
		stored[value.lower()] = value
		used_abbrs.add(abbr.lower())
		added = True

	if added:
		doc.flags.ignore_permissions = True
		doc.save()

	return stored
