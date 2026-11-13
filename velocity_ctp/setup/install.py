"""Idempotent setup of Velocity CTP master data.

Run on an existing site with:
    bench --site <site> execute velocity_ctp.setup.install.setup_masters
"""

from __future__ import annotations

from itertools import pairwise

import frappe
from frappe import _

MERCHANDISER_ROLE = "Velocity Merchandiser"

ITEM_ATTRIBUTES = ("Size", "Colour")

ITEM_GROUPS = ("Fabric", "Accessories & Trims", "Non-Product", "Finished Goods", "Services")

# (name, must_be_whole_number)
UOMS = (("Meter", 0), ("Pcs", 1), ("Cone", 1), ("Kg", 0), ("Set", 1))
METER_ALIASES = ("Meter", "Metre")

WAREHOUSES = (
	"Fabric Store",
	"Trim Store",
	"Chemical Store",
	"Cutting WIP",
	"Stitching WIP",
	"Washing WIP",
	"Finishing WIP",
	"Finished Goods Store",
	"Rejection Store",
)

# (process_name, sequence, wip warehouse, requires_barcode, allow_rejection)
PROCESSES = (
	("Cutting", 1, "Cutting WIP", 0, 0),
	("Stitching", 2, "Stitching WIP", 1, 1),
	("Washing", 3, "Washing WIP", 1, 1),
	("Finishing", 4, "Finishing WIP", 1, 1),
	("Packing", 5, "Finished Goods Store", 1, 0),
)

WASH_TYPES = ("Rinse Wash", "Enzyme Wash", "Stone Wash", "Softener Wash")

PRODUCT_CATEGORIES = ("5 Pocket Pant", "Cargo Pant", "Chino Pant", "Short", "Skirt", "Jacket")


def after_install() -> None:
	"""Hook for new sites. Skips quietly when the setup wizard has not created a company yet."""
	if not get_default_company(throw=False):
		print(
			"Velocity CTP: no default company yet. Run velocity_ctp.setup.install.setup_masters after the setup wizard."
		)
		ensure_role()
		return
	setup_masters()


def setup_masters() -> None:
	company = get_default_company()
	log: list[str] = []

	ensure_role(log)
	ensure_item_attributes(log)
	ensure_item_groups(log)
	ensure_uoms(log)
	warehouses = ensure_warehouses(company, log)
	ensure_processes(warehouses, log)
	ensure_simple_records("Wash Type", "wash_type", WASH_TYPES, {"washing_category": "Denim"}, log)
	ensure_simple_records("Product Category", "category_name", PRODUCT_CATEGORIES, {}, log)

	frappe.db.commit()

	print(f"Velocity CTP setup complete for company: {company}")
	print(
		"\n".join(f"  created: {line}" for line in log)
		if log
		else "  Nothing to create; all masters already exist."
	)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def get_default_company(throw: bool = True) -> str | None:
	company = frappe.defaults.get_global_default("company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if company and frappe.db.exists("Company", company):
		return company
	if throw:
		frappe.throw(
			_(
				"No default company is set. Please complete the setup wizard or set a Default Company in Global Defaults, then run the setup again."
			)
		)
	return None


def ensure_role(log: list[str] | None = None) -> None:
	if frappe.db.exists("Role", MERCHANDISER_ROLE):
		return
	frappe.get_doc({"doctype": "Role", "role_name": MERCHANDISER_ROLE, "desk_access": 1}).insert(
		ignore_permissions=True
	)
	if log is not None:
		log.append(f"Role {MERCHANDISER_ROLE}")


def ensure_item_attributes(log: list[str]) -> None:
	for name in ITEM_ATTRIBUTES:
		if frappe.db.exists("Item Attribute", name):
			if frappe.db.get_value("Item Attribute", name, "numeric_values"):
				print(
					f"  warning: Item Attribute {name} uses numeric values; Velocity CTP expects text values."
				)
			continue
		frappe.get_doc({"doctype": "Item Attribute", "attribute_name": name, "numeric_values": 0}).insert(
			ignore_permissions=True
		)
		log.append(f"Item Attribute {name}")


def ensure_item_groups(log: list[str]) -> None:
	root = "All Item Groups"
	if not frappe.db.exists("Item Group", root):
		root = frappe.db.get_value(
			"Item Group", {"is_group": 1, "parent_item_group": ("in", ("", None))}, "name"
		)
	for name in ITEM_GROUPS:
		if frappe.db.exists("Item Group", name):
			continue
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": name, "parent_item_group": root, "is_group": 0}
		).insert(ignore_permissions=True)
		log.append(f"Item Group {name}")


def ensure_uoms(log: list[str]) -> None:
	for name, whole in UOMS:
		if name == "Meter" and any(frappe.db.exists("UOM", alias) for alias in METER_ALIASES):
			continue
		if frappe.db.exists("UOM", name):
			continue
		frappe.get_doc({"doctype": "UOM", "uom_name": name, "must_be_whole_number": whole}).insert(
			ignore_permissions=True
		)
		log.append(f"UOM {name}")


def ensure_warehouses(company: str, log: list[str]) -> dict[str, str]:
	"""Create the production warehouses and return {warehouse_name: warehouse docname}."""
	parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name", order_by="lft asc")
	result: dict[str, str] = {}
	for name in WAREHOUSES:
		existing = frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": company}, "name")
		if existing:
			result[name] = existing
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": name,
				"company": company,
				"parent_warehouse": parent,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
		result[name] = doc.name
		log.append(f"Warehouse {doc.name}")
	return result


def ensure_processes(warehouses: dict[str, str], log: list[str]) -> None:
	for process_name, sequence, warehouse, barcode, rejection in PROCESSES:
		if frappe.db.exists("Process", process_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": process_name,
				"sequence": sequence,
				"process_type": "In-house",
				"wip_warehouse": warehouses[warehouse],
				"requires_barcode": barcode,
				"allow_rejection": rejection,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		log.append(f"Process {process_name}")

	# Chain next_process only where it is still empty, so manual changes are kept.
	for current, following in pairwise(PROCESSES):
		name, next_name = current[0], following[0]
		if frappe.db.exists("Process", name) and not frappe.db.get_value("Process", name, "next_process"):
			doc = frappe.get_doc("Process", name)
			doc.next_process = next_name
			doc.save(ignore_permissions=True)
			log.append(f"Process {name} -> next process {next_name}")


def ensure_simple_records(
	doctype: str, fieldname: str, names: tuple[str, ...], extra: dict, log: list[str]
) -> None:
	for name in names:
		if frappe.db.exists(doctype, name):
			continue
		frappe.get_doc({"doctype": doctype, fieldname: name, "is_active": 1, **extra}).insert(
			ignore_permissions=True
		)
		log.append(f"{doctype} {name}")
