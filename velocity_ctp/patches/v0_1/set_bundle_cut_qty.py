import frappe


def execute():
	"""Bundles created before Phase 4 get their cut quantity (pieces when the bundle was created)."""
	frappe.db.sql("update `tabBundle` set cut_qty = qty where ifnull(cut_qty, 0) = 0")
