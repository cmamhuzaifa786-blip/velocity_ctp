"""Idempotent setup of Velocity CTP master data.

Run on an existing site with:
    bench --site <site> execute velocity_ctp.setup.install.setup_masters
"""

from __future__ import annotations

from itertools import pairwise

import frappe
from frappe import _

MERCHANDISER_ROLE = "Velocity Merchandiser"
CUTTING_ROLE = "Velocity Cutting"
PRODUCTION_ROLE = "Velocity Production"
VELOCITY_ROLES = (MERCHANDISER_ROLE, CUTTING_ROLE, PRODUCTION_ROLE)
COLOUR_CHANGE_PROCESSES = ("Washing",)

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

# Process WIP warehouses carry their stock on the "Work In Progress" account; stores stay on
# the company's default inventory account (Stock In Hand).
WIP_ACCOUNT_NAME = "Work In Progress"
WIP_WAREHOUSES = ("Cutting WIP", "Stitching WIP", "Washing WIP", "Finishing WIP")

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
	ensure_batch_tracking(log)
	ensure_velocity_settings(log)
	ensure_item_groups(log)
	ensure_uoms(log)
	warehouses = ensure_warehouses(company, log)
	ensure_wip_account(company, warehouses, log)
	ensure_colour_change_processes(log)
	ensure_processes(warehouses, log)
	ensure_simple_records("Wash Type", "wash_type", WASH_TYPES, {"washing_category": "Denim"}, log)
	ensure_simple_records("Product Category", "category_name", PRODUCT_CATEGORIES, {}, log)
	ensure_sales_order_field(log)

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
	for role in VELOCITY_ROLES:
		if frappe.db.exists("Role", role):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)
		if log is not None:
			log.append(f"Role {role}")


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


def ensure_sales_order_field(log: list[str]) -> None:
	if frappe.db.exists("Custom Field", "Sales Order-garment_order"):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"Sales Order",
		{
			"fieldname": "garment_order",
			"label": "Garment Order",
			"fieldtype": "Link",
			"options": "Garment Order",
			"insert_after": "po_date",
			"read_only": 1,
			"no_copy": 1,
			"in_standard_filter": 1,
			"allow_on_submit": 0,
		},
	)
	log.append("Custom Field Sales Order-garment_order")


def ensure_batch_tracking(log: list[str]) -> None:
	"""Fabric is tracked by batch (lot / shade), which needs batch tracking switched on in Stock Settings."""
	if frappe.db.get_single_value("Stock Settings", "enable_serial_and_batch_no_for_item"):
		return
	settings = frappe.get_single("Stock Settings")
	settings.enable_serial_and_batch_no_for_item = 1
	settings.flags.ignore_permissions = True
	settings.save()
	log.append("Stock Settings: Activate Serial / Batch No for Item")


def ensure_velocity_settings(log: list[str]) -> None:
	from velocity_ctp.cutting.settings import ensure_saved

	if ensure_saved():
		log.append("Velocity Settings defaults")


def ensure_wip_account(company: str, warehouses: dict[str, str], log: list[str]) -> None:
	"""Create the "Work In Progress" stock account under Current Assets and set it on the WIP warehouses."""
	account = frappe.db.get_value(
		"Account", {"company": company, "account_name": WIP_ACCOUNT_NAME, "is_group": 0}, "name"
	)
	if not account:
		parent = frappe.db.get_value(
			"Account", {"company": company, "account_name": "Current Assets", "is_group": 1}, "name"
		)
		if not parent:
			frappe.throw(
				_("Account group {0} was not found for company {1}.").format(
					frappe.bold("Current Assets"), company
				)
			)
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": WIP_ACCOUNT_NAME,
				"parent_account": parent,
				"company": company,
				"is_group": 0,
				"account_type": "Stock",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		account = doc.name
		log.append(f"Account {account}")
	elif frappe.db.get_value("Account", account, "account_type") != "Stock":
		frappe.throw(
			_(
				"Account {0} exists but its Account Type is not Stock. Please correct it and run the setup again."
			).format(frappe.bold(account))
		)

	for warehouse_name in WIP_WAREHOUSES:
		warehouse = warehouses.get(warehouse_name)
		if not warehouse or frappe.db.get_value("Warehouse", warehouse, "account") == account:
			continue
		doc = frappe.get_doc("Warehouse", warehouse)
		doc.account = account
		doc.flags.ignore_permissions = True
		doc.save()
		log.append(f"Warehouse {warehouse} -> account {account}")


def ensure_colour_change_processes(log: list[str]) -> None:
	"""Washing may receive bundles in another colour of the style (for example Dark Indigo -> Washed Light)."""
	for name in COLOUR_CHANGE_PROCESSES:
		if frappe.db.exists("Process", name) and not frappe.db.get_value(
			"Process", name, "allow_colour_change"
		):
			frappe.db.set_value("Process", name, "allow_colour_change", 1)
			log.append(f"Process {name}: Allow Colour Change")
