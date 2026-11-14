"""Velocity Settings with field defaults applied.

A Single stores nothing until it is saved, and fields added later have no stored value. Readers
get the field default for any value that was never stored; setup stores those defaults once
(only for values that do not exist yet, never changing a stored value).
"""

from __future__ import annotations

import frappe


def _defaults() -> dict:
	meta = frappe.get_meta("Velocity Settings")
	return {
		df.fieldname: df.default
		for df in meta.fields
		if df.default is not None and df.fieldtype not in ("Section Break", "Column Break")
	}


def get_settings():
	doc = frappe.get_cached_doc("Velocity Settings")
	stored = _stored_fields()
	for fieldname, default in _defaults().items():
		if fieldname not in stored:
			doc.set(
				fieldname,
				frappe.get_meta("Velocity Settings").get_field(fieldname) and _cast(fieldname, default),
			)
	return doc


def _cast(fieldname: str, value):
	df = frappe.get_meta("Velocity Settings").get_field(fieldname)
	if df.fieldtype in ("Int", "Check"):
		return int(value)
	if df.fieldtype in ("Float", "Percent", "Currency"):
		return float(value)
	return value


def _stored_fields() -> set[str]:
	return set(frappe.db.sql_list("select field from `tabSingles` where doctype = 'Velocity Settings'"))


def ensure_saved() -> list[str]:
	"""Store defaults for settings that have no stored value yet. Returns the fields stored."""
	stored = _stored_fields()
	missing = {k: v for k, v in _defaults().items() if k not in stored}
	if not stored:
		settings = frappe.get_single("Velocity Settings")
		settings.flags.ignore_permissions = True
		settings.save()
		return sorted(missing)
	for fieldname, default in missing.items():
		frappe.db.set_single_value("Velocity Settings", fieldname, _cast(fieldname, default))
	if missing:
		frappe.clear_document_cache("Velocity Settings", "Velocity Settings")
	return sorted(missing)
