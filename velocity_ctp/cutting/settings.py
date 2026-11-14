"""Velocity Settings with field defaults applied (a Single has no stored values until first saved)."""

from __future__ import annotations

import frappe


def get_settings():
	return frappe.get_cached_doc("Velocity Settings")


def ensure_saved() -> bool:
	"""Store the defaults once so that every reader (including the browser) sees them."""
	if frappe.db.sql("select 1 from `tabSingles` where doctype='Velocity Settings' limit 1"):
		return False
	settings = frappe.get_single("Velocity Settings")
	settings.flags.ignore_permissions = True
	settings.save()
	return True
