"""Demo data for a Velocity demo site (real document flows, dates relative to the day it runs).

    bench --site velocity-demo.local execute velocity_ctp.demo.seed.run

- Refuses to run on a site whose name does not contain "demo".
- Idempotent: every step stores what it created under the site default "velocity_demo:<step>" and is
  skipped on the next run (safe to run again; a run that stopped half way continues where it stopped).
- Every transaction goes through the app's and ERPNext's own documents and their normal submit paths,
  as the demo user who would do that job. Steps run oldest first across all orders, so stock is valued
  in date order (no backdated reposting).
- Dates are relative to the day of the first run (days_ago / days_ahead). Recreate the site before a demo
  for fresh dates (see README "Demo site").
- At the end the demo data map is written to velocity_ctp/demo/DEMO_DATA.md.

Dry run (everything rolled back): bench --site velocity-demo.local execute velocity_ctp.demo.seed.run --kwargs "{'dry_run': True}"
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from contextlib import contextmanager

import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate

PASSWORD = "Velocity@2026"
MAIL = "velocity-demo.local"  # demo login addresses; never delivered
PREFIX = "velocity_demo:"

# ----------------------------------------------------------------------------------------------
# Masters (names from the client's current system)
# ----------------------------------------------------------------------------------------------

CUSTOMERS = {
	"Juicy Couture": "USD",
	"TCW Trends Inc.": "USD",
	"Hoodrich": "USD",
	"Ink Clothing": "USD",
	"Marald S.p.A": "EUR",
}
SUPPLIERS = {
	"Meko Denim Mills": "Raw Material",
	"Imran Brother": "Raw Material",
	"Combine Textile": "Raw Material",
	"MS Clothing": "Raw Material",
	"Trimstex Enterprises": "Raw Material",
	"M.R. Carton Care": "Raw Material",
	"Kqing Fashion Export Co., Ltd": "Raw Material",
	"Fabritex Enterprises": "Local",
	"Raheel Brothers": "Local",
	"Muhammad Kafil Cutting Contractor": "Services",
	"MS Garments": "Services",
}
KAFIL, MS_GARMENTS = "Muhammad Kafil Cutting Contractor", "MS Garments"
SIZE_SETS = {
	"28-40": ["28", "30", "32", "34", "36", "38", "40"],
	"28-34": ["28", "30", "32", "34"],
	"6-14": ["6", "8", "10", "12", "14"],
	"S-XXL": ["S", "M", "L", "XL", "XXL"],
	"44-54": ["44", "46", "48", "50", "52", "54"],
	"Kids S 8-10Y to XL 13-15Y": ["S 8-10Y", "M 10-12Y", "L 12-13Y", "XL 13-15Y"],
}
# code, name, group, uom, batch, inspection before purchase
ITEMS = [
	("FAB-TWILL-1010", "10X10/70X40 Main Body Twill", "Fabric", "Meter", 1, 0),
	("FAB-TWILL-PRT-24150", "24X150/76X60 2/1 Twill Printed", "Fabric", "Meter", 1, 0),
	("FAB-DENIM-DYED", "Denim Dyed Main Body", "Fabric", "Meter", 1, 0),
	("FAB-CAMO-Z-TWILL", "3X8/64X45 Printed Camo 3/1 Z Twill", "Fabric", "Meter", 1, 0),
	("ACC-METAL-BUTTON", "Metal Button", "Accessories & Trims", "Nos", 0, 0),
	("ACC-WAIST-TAG", "Waist Tag", "Accessories & Trims", "Nos", 0, 0),
	("ACC-MAIN-SIZE-LABEL", "Main + Size Label", "Accessories & Trims", "Nos", 0, 0),
	("ACC-SATIN-CARE-LABEL", "Satin Care Label", "Accessories & Trims", "Nos", 0, 0),
	("ACC-SWING-TAG", "Swing Tag", "Accessories & Trims", "Nos", 0, 1),
	("ACC-ZIPPER-4.5-BRASS", "Polyester Zipper 4.5 A/Brass", "Accessories & Trims", "Nos", 0, 1),
	("ACC-THREAD-COATS-80", "Cotton Thread Coats 80 Tex", "Accessories & Trims", "Nos", 0, 0),
	("ACC-POLYBAG-STICKER", "Poly Bag Sticker", "Accessories & Trims", "Nos", 0, 0),
	("PKG-CARTON-60X40X20", "Carton 60x40x20", "Accessories & Trims", "Nos", 0, 0),
	("CHEM-WASH-ENZYME", "Washing Enzyme", "Non-Product", "Kg", 0, 0),
	("CHEM-SOFTENER", "Softener", "Non-Product", "Kg", 0, 0),
	("NDL-DPX5", "Needles DPX5", "Non-Product", "Nos", 0, 0),
]
# style_no: name, customer, category, size set, wash type, colours
STYLES = {
	"JCTDN009": (
		"Camo Y2K Back Graphic Mini Skirt",
		"Juicy Couture",
		"Skirt",
		"6-14",
		"Softener Wash",
		["Camo Green", "Camo Pink"],
	),
	"WHIPLASH WALK": (
		"Whiplash Walk Wide Leg Jean",
		"TCW Trends Inc.",
		"5 Pocket Pant",
		"28-34",
		"Stone Wash",
		["Dark Indigo", "Mid Blue"],
	),
	"ORIGIN OVERSIZED": (
		"Origin Oversized Kids Denim Jacket",
		"Hoodrich",
		"Jacket",
		"Kids S 8-10Y to XL 13-15Y",
		"Stone Wash",
		["Black", "Washed Black"],
	),
	"STADE OVER": (
		"Stade Over Mens Cargo Pants",
		"Ink Clothing",
		"Cargo Pant",
		"S-XXL",
		"Enzyme Wash",
		["Khaki", "Olive"],
	),
	"PSE1603SS": (
		"PSE1603SS Chino Pant",
		"Marald S.p.A",
		"Chino Pant",
		"44-54",
		"Softener Wash",
		["Navy", "Sand"],
	),
	"SKINNY JEANS 5PKT": (
		"Skinny Jeans 5 Pocket",
		"TCW Trends Inc.",
		"5 Pocket Pant",
		"28-40",
		"Rinse Wash",
		["Rinse Blue", "Black"],
	),
}
USERS = [
	# email local part, full name, roles, demo role
	(
		"muhammad.mirza",
		"Muhammad Mirza",
		["Velocity Merchandiser", "Sales User", "Purchase User", "Stock User"],
		"Merchandiser",
	),
	("costing.officer", "Ayesha Siddiqui", ["Velocity Costing", "Velocity Merchandiser"], "Costing"),
	(
		"costing.approver",
		"Faisal Qureshi",
		["Velocity Costing Approver", "Velocity Costing"],
		"Costing Approver",
	),
	(
		"po.approver.l1",
		"Nadeem Akhtar",
		["Velocity PO Approver L1", "Velocity Requisition Approver", "Purchase User"],
		"PO Approver L1 and Requisition Approver",
	),
	(
		"po.approver.l2",
		"Tariq Mehmood",
		["Velocity PO Approver L2", "Purchase Manager", "Purchase User", "Accounts User"],
		"PO Approver L2",
	),
	("cutting.supervisor", "Imran Ali", ["Velocity Cutting", "Stock User"], "Cutting Supervisor"),
	(
		"production.supervisor",
		"Shahid Hussain",
		["Velocity Production", "Stock User", "Velocity Gate Approver", "Velocity Gate"],
		"Production Supervisor and Gate Approver",
	),
	(
		"store.keeper",
		"Rashid Khan",
		["Stock User", "Quality Manager", "Purchase User", "Velocity Gate"],
		"Store Keeper and Gate",
	),
	("accounts.officer", "Sana Javed", ["Accounts User", "Sales User", "Stock User"], "Accounts"),
]


def email(local: str) -> str:
	return f"{local}@{MAIL}"


MIRZA, COSTING, COSTING_APPROVER = (
	email("muhammad.mirza"),
	email("costing.officer"),
	email("costing.approver"),
)
L1, L2, CUTTER, PRODUCTION = (
	email("po.approver.l1"),
	email("po.approver.l2"),
	email("cutting.supervisor"),
	email("production.supervisor"),
)
STORE, ACCOUNTS = email("store.keeper"), email("accounts.officer")

# Orders: key -> customer, style, buyer PO, ordered days ago, ship in days, excess %, lines, cut colour map
ORDERS = {
	"O1": dict(
		customer="Juicy Couture",
		style="JCTDN009",
		po="JC-PO-77120",
		ordered=12,
		ship=75,
		excess=8,
		lines={
			"Camo Green": {"6": 120, "8": 150, "10": 150, "12": 120, "14": 60},
			"Camo Pink": {"6": 120, "8": 150, "10": 150, "12": 120, "14": 60},
		},
	),
	"O2": dict(
		customer="TCW Trends Inc.",
		style="WHIPLASH WALK",
		po="TCW-44871",
		ordered=30,
		ship=5,
		excess=0,
		lines={
			"Dark Indigo": {"28": 72, "30": 72, "32": 72, "34": 72},
			"Mid Blue": {"28": 72, "30": 72, "32": 71, "34": 71},
		},
	),
	"O3": dict(
		customer="Hoodrich",
		style="ORIGIN OVERSIZED",
		po="HR-ORG-2290",
		ordered=32,
		ship=18,
		excess=0,
		lines={"Washed Black": {"S 8-10Y": 132, "M 10-12Y": 132, "L 12-13Y": 132, "XL 13-15Y": 131}},
		colour_map={"Washed Black": "Black"},
	),
	"O4": dict(
		customer="Ink Clothing",
		style="STADE OVER",
		po="INK-SO-1187",
		ordered=24,
		ship=25,
		excess=0,
		lines={
			"Khaki": {"S": 90, "M": 90, "L": 90, "XL": 90, "XXL": 90},
			"Olive": {"S": 90, "M": 90, "L": 90, "XL": 90, "XXL": 90},
		},
	),
	"O5": dict(
		customer="Marald S.p.A",
		style="PSE1603SS",
		po="MAR-0316-SS",
		ordered=10,
		ship=40,
		excess=0,
		lines={
			"Navy": {"44": 60, "46": 60, "48": 60, "50": 60, "52": 60, "54": 60},
			"Sand": {"44": 57, "46": 57, "48": 57, "50": 57, "52": 56, "54": 56},
		},
	),
	"O6": dict(
		customer="TCW Trends Inc.",
		style="SKINNY JEANS 5PKT",
		po="TCW-45102",
		ordered=8,
		ship=10,
		excess=0,
		lines={
			"Rinse Blue": {"28": 80, "30": 80, "32": 80, "34": 70, "36": 70, "38": 60, "40": 60},
			"Black": {"28": 80, "30": 80, "32": 80, "34": 70, "36": 70, "38": 60, "40": 60},
		},
	),
	"O7": dict(
		customer="TCW Trends Inc.",
		style="WHIPLASH WALK",
		po="TCW-43990",
		ordered=40,
		ship=3,
		ship_moved=-4,
		excess=0,
		lines={"Mid Blue": {"28": 60, "30": 60, "32": 60, "34": 60}},
	),
	"O8": dict(
		customer="Juicy Couture",
		style="JCTDN009",
		po="JC-PO-76004",
		ordered=45,
		ship=12,
		excess=0,
		lines={"Camo Green": {"6": 72, "8": 72, "10": 72, "12": 72, "14": 72}},
	),
}
# Fabric per style (item, metres of marker per piece) and lots received (lot, shade, metres)
STYLE_FABRIC = {
	"JCTDN009": ("FAB-CAMO-Z-TWILL", 1.05),
	"WHIPLASH WALK": ("FAB-TWILL-1010", 1.15),
	"ORIGIN OVERSIZED": ("FAB-DENIM-DYED", 1.25),
	"STADE OVER": ("FAB-TWILL-1010", 1.20),
	"PSE1603SS": ("FAB-TWILL-PRT-24150", 1.10),
	"SKINNY JEANS 5PKT": ("FAB-DENIM-DYED", 1.15),
}
FABRIC_LOTS = {
	# item: supplier, rate, [(lot, shade, metres)]
	"FAB-TWILL-1010": (
		"Combine Textile",
		610,
		[("CT-1010-A", "Shade A", 700), ("CT-1010-B", "Shade B", 900), ("CT-1010-C", "Shade C", 1200)],
	),
	"FAB-DENIM-DYED": (
		"Meko Denim Mills",
		690,
		[("MK-DD-2611", "Indigo 2", 700), ("MK-DD-2612", "Indigo 3", 400)],
	),
	"FAB-CAMO-Z-TWILL": (
		"Imran Brother",
		850,
		[("IB-CAMO-31", "Lot 31", 420), ("IB-CAMO-32", "Lot 32", 160)],
	),
	"FAB-TWILL-PRT-24150": (
		"MS Clothing",
		575,
		[("MSC-PRT-07", "Print 7", 420), ("MSC-PRT-08", "Print 8", 400)],
	),
}
TRIMS = {
	# item: supplier, rate, qty received
	"ACC-METAL-BUTTON": ("Trimstex Enterprises", 6.5, 4000),
	"ACC-WAIST-TAG": ("Trimstex Enterprises", 4.0, 3000),
	"ACC-MAIN-SIZE-LABEL": ("Kqing Fashion Export Co., Ltd", 3.5, 4000),
	"ACC-SATIN-CARE-LABEL": ("Kqing Fashion Export Co., Ltd", 2.5, 4000),
	"ACC-ZIPPER-4.5-BRASS": ("Kqing Fashion Export Co., Ltd", 18.0, 2000),
	"ACC-THREAD-COATS-80": ("Trimstex Enterprises", 450.0, 200),
	"ACC-POLYBAG-STICKER": ("Trimstex Enterprises", 1.2, 3000),
	"PKG-CARTON-60X40X20": ("M.R. Carton Care", 165.0, 150),
}
PROCESS_RATES = {
	"Cutting": 12,
	"Stitching": 95,
	"Washing": 45,
	"Finishing": 22,
}  # in-house absorption per piece


# ----------------------------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------------------------


def run(dry_run: bool = False) -> None:
	if "demo" not in (frappe.local.site or ""):
		frappe.throw(
			f"The demo seed only runs on a demo site (name containing 'demo'), not on {frappe.local.site}."
		)
	frappe.flags.mute_emails = True
	seed = Seed(dry_run=bool(dry_run))
	try:
		seed.run()
		write_data_map()
	finally:
		frappe.set_user("Administrator")
		if dry_run:
			frappe.db.rollback()
			frappe.defaults._clear_cache("__default")
			print("Dry run: everything rolled back.")
		else:
			frappe.db.commit()
	print(f"Steps created: {seed.created}, already done: {seed.skipped}.")


def days_ago(n: int) -> str:
	return add_days(nowdate(), -n)


def days_ahead(n: int) -> str:
	return add_days(nowdate(), n)


@contextmanager
def as_user(user: str):
	frappe.set_user(user)
	frappe.local.message_log = []
	try:
		yield
	finally:
		frappe.set_user("Administrator")


def get(key: str):
	# read straight from the table: the defaults cache would survive a dry-run rollback
	value = frappe.db.get_value("DefaultValue", {"parent": "__default", "defkey": PREFIX + key}, "defvalue")
	return json.loads(value) if value else None


class Seed:
	def __init__(self, dry_run: bool = False):
		self.dry_run = dry_run
		self.created = 0
		self.skipped = 0

	def step(self, key: str, fn, *args):
		done = get(key)
		if done is not None:
			self.skipped += 1
			return done
		value = fn(*args)
		frappe.db.set_default(PREFIX + key, json.dumps(value if value is not None else True, default=str))
		if not self.dry_run:
			frappe.db.commit()
		self.created += 1
		print(f"  {key}: {value}")
		return value

	def run(self) -> None:
		self.step("masters", setup_masters)
		self.step("receivables", setup_receivables)
		self.step("users", setup_users)
		self.step("styles", setup_styles)
		self.step("cost_sheets", setup_cost_sheets)
		self.step("orders", setup_orders)
		for _day, key, fn in sorted(timeline(), key=lambda t: -t[0]):
			self.step(key, fn)


# ----------------------------------------------------------------------------------------------
# Masters, users, styles, cost sheets, orders
# ----------------------------------------------------------------------------------------------


def company() -> str:
	return frappe.defaults.get_global_default("company")


def wh(name: str) -> str:
	return frappe.db.get_value("Warehouse", {"warehouse_name": name, "company": company()}, "name")


def setup_masters() -> str:
	ss = frappe.get_single("Stock Settings")
	if not ss.enable_serial_and_batch_no_for_item:
		ss.enable_serial_and_batch_no_for_item = 1  # fabric is tracked by lot
		ss.save()
	for process, rate in PROCESS_RATES.items():
		frappe.db.set_value("Process", process, "absorption_rate_per_pc", rate)
	frappe.db.set_value("Process", "Stitching", "process_type", "Both")  # in-house or CMT contractor
	for currency, rate in (("USD", 276), ("EUR", 305)):
		if not frappe.db.exists("Currency Exchange", {"from_currency": currency, "to_currency": "PKR"}):
			frappe.get_doc(
				{
					"doctype": "Currency Exchange",
					"date": days_ago(90),
					"from_currency": currency,
					"to_currency": "PKR",
					"exchange_rate": rate,
					"for_buying": 1,
					"for_selling": 1,
				}
			).insert()
	for name, currency in CUSTOMERS.items():
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_type": "Company",
					"customer_group": "Commercial",
					"territory": "Rest Of The World",
					"default_currency": currency,
				}
			).insert()
	for name, group in SUPPLIERS.items():
		if not frappe.db.exists("Supplier", name):
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": name,
					"supplier_group": group,
					"supplier_type": "Company",
					"country": "China" if "Kqing" in name else "Pakistan",
				}
			).insert()
	if not frappe.db.exists("Sales Partner", "Ink Clothing"):
		frappe.get_doc(
			{
				"doctype": "Sales Partner",
				"partner_name": "Ink Clothing",
				"commission_rate": 5,
				"territory": "All Territories",
			}
		).insert()
	for name, sizes in SIZE_SETS.items():
		if not frappe.db.exists("Size Set", name):
			frappe.get_doc(
				{
					"doctype": "Size Set",
					"size_set_name": name,
					"is_active": 1,
					"sizes": [{"size": s, "sequence": i} for i, s in enumerate(sizes, 1)],
				}
			).insert()
	for code, name, group, uom, batch, inspection in ITEMS:
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": name,
					"item_group": group,
					"stock_uom": uom,
					"is_stock_item": 1,
					"has_batch_no": batch,
					"inspection_required_before_purchase": inspection,
					"include_item_in_manufacturing": 0,
				}
			).insert()
	dept = frappe.db.get_value("Department", {"department_name": "Washing", "company": company()})
	if not dept:
		dept = (
			frappe.get_doc(
				{
					"doctype": "Department",
					"department_name": "Washing",
					"company": company(),
					"parent_department": "All Departments",
				}
			)
			.insert()
			.name
		)
	cc = frappe.db.get_value("Cost Center", {"cost_center_name": "Washing", "company": company()})
	if not cc:
		root = frappe.db.get_value(
			"Cost Center", {"company": company(), "is_group": 1}, "name", order_by="lft"
		)
		cc = (
			frappe.get_doc(
				{
					"doctype": "Cost Center",
					"cost_center_name": "Washing",
					"company": company(),
					"parent_cost_center": root,
				}
			)
			.insert()
			.name
		)
	settings = frappe.get_single("Velocity Settings")
	if not any(r.department == dept for r in settings.department_cost_centers):
		settings.append("department_cost_centers", {"department": dept, "cost_center": cc})
		settings.save()
	return "ok"


def setup_receivables() -> dict:
	"""Foreign-currency buyers are invoiced in their currency, so each needs a receivable account in it."""
	parent = frappe.db.get_value(
		"Account", {"company": company(), "account_type": "Receivable", "is_group": 0}, "parent_account"
	)
	abbr = frappe.db.get_value("Company", company(), "abbr")
	result = {}
	for currency in sorted(set(CUSTOMERS.values())):
		name = f"Debtors {currency} - {abbr}"
		if not frappe.db.exists("Account", name):
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"Debtors {currency}",
					"company": company(),
					"parent_account": parent,
					"account_type": "Receivable",
					"account_currency": currency,
				}
			).insert()
		for customer, cur in CUSTOMERS.items():
			doc = frappe.get_doc("Customer", customer)
			if cur == currency and not any(a.company == company() for a in doc.accounts):
				doc.append("accounts", {"company": company(), "account": name})
				doc.save()
		result[currency] = name
	return result


def setup_users() -> list[str]:
	for local, full_name, roles, _label in USERS:
		address = email(local)
		if not frappe.db.exists("User", address):
			first, _sep, last = full_name.partition(" ")
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": address,
					"first_name": first,
					"last_name": last,
					"send_welcome_email": 0,
					"user_type": "System User",
					"roles": [{"role": r} for r in roles],
				}
			)
			user.flags.no_welcome_mail = True
			user.insert(ignore_permissions=True)
			from frappe.utils.password import update_password

			update_password(address, PASSWORD)
		frappe.db.set_value("User", address, {"thread_notify": 0, "send_me_a_copy": 0}, update_modified=False)
	return [email(u[0]) for u in USERS]


def setup_styles() -> list[str]:
	for style_no, (name, customer, category, size_set, wash, colours) in STYLES.items():
		if frappe.db.exists("Style", style_no):
			continue
		with as_user(MIRZA):
			style = frappe.get_doc(
				{
					"doctype": "Style",
					"style_no": style_no,
					"style_name": name,
					"customer": customer,
					"product_category": category,
					"size_set": size_set,
					"wash_type": wash,
					"gender": "Kids" if "Kids" in size_set else None,
					"season": "SS27",
					"colours": [{"colour": c} for c in colours],
				}
			).insert()
			style.create_item_variants()
	return list(STYLES)


HEAD_RATES = {
	"Washing Cost": 55,
	"Print": 75,
	"Embellishment": 55,
	"Manufacturing Cost": 550,
	"Courier Charges": 15,
	"Clearing / Handling Charges": 15,
	"Transport / Forwarding Charges": 20,
	"Sample Cost": 1,
	"Bank Charges": 2.5,
	"Insurance Charges": 0.1,
	"Commission": 9,
	"Service Charges / Fashion Support": 1.25,
}
COST_SHEETS = {
	# style: customer, currency, rate, quoted, qty, excess, fabrics[(placement, item, desc, usage, cost)], extra head rates
	"JCTDN009": (
		"Juicy Couture",
		"USD",
		276,
		8.25,
		1200,
		8,
		[
			("Body", "FAB-CAMO-Z-TWILL", "3X8/64X45 Printed Camo 3/1 Z Twill", 0.60, 725),
			("Pocketing", "FAB-DENIM-DYED", "Denim pocketing", 0.18, 268),
		],
		{},
	),
	"WHIPLASH WALK": (
		"TCW Trends Inc.",
		"USD",
		276,
		8.10,
		574,
		0,
		[("Body", "FAB-TWILL-1010", "10X10/70X40 Main Body Twill", 1.15, 610)],
		{"Manufacturing Cost": 420},
	),
	"ORIGIN OVERSIZED": (
		"Hoodrich",
		"USD",
		276,
		9.40,
		527,
		0,
		[("Body", "FAB-DENIM-DYED", "Denim Dyed Main Body", 1.25, 690)],
		{"Manufacturing Cost": 480},
	),
	"STADE OVER": (
		"Ink Clothing",
		"USD",
		276,
		8.90,
		900,
		0,
		[("Body", "FAB-TWILL-1010", "10X10/70X40 Main Body Twill", 1.20, 610)],
		{"Manufacturing Cost": 460},
	),
	"PSE1603SS": (
		"Marald S.p.A",
		"EUR",
		305,
		7.20,
		700,
		0,
		[("Body", "FAB-TWILL-PRT-24150", "24X150/76X60 2/1 Twill Printed", 1.10, 575)],
		{"Manufacturing Cost": 430},
	),
	"SKINNY JEANS 5PKT": (
		"TCW Trends Inc.",
		"USD",
		276,
		7.85,
		1000,
		0,
		[("Body", "FAB-DENIM-DYED", "Denim Dyed Main Body", 1.15, 690)],
		{"Manufacturing Cost": 520},
	),
}


def setup_cost_sheets() -> dict:
	from velocity_ctp.velocity_ctp.doctype.cost_sheet.cost_sheet import approve, submit_for_approval

	result = {}
	for style, (customer, currency, rate, quoted, qty, excess, fabrics, extra) in COST_SHEETS.items():
		existing = frappe.db.get_value("Cost Sheet", {"style": style, "status": "Approved"}, "name")
		if existing:
			result[style] = existing
			continue
		with as_user(COSTING):
			cs = frappe.get_doc(
				{
					"doctype": "Cost Sheet",
					"customer": customer,
					"style": style,
					"costing_date": days_ago(50),
					"price_basis": "FOB",
					"quantity_pcs": qty,
					"excess_percent": excess,
					"currency": currency,
					"exchange_rate": rate,
					"quoted_fob_fc": quoted,
					"fabrics": [
						{
							"placement": p,
							"fabric_item": i,
							"fabric_description": d,
							"source": "Local",
							"usage_per_pc": u,
							"unit_cost": c,
						}
						for p, i, d, u, c in fabrics
					],
					"accessories": [
						{
							"accessory_description": "Trims kit (buttons, labels, tags, zipper, thread, carton)",
							"source": "Local",
							"usage_per_pc": 1.0,
							"unit_cost": 220,
						}
					],
				}
			)
			cs.recalculate()
			rates = {**HEAD_RATES, **extra}
			for row in cs.costs:
				if row.cost_head in rates:
					row.rate_or_percent = rates[row.cost_head]
			cs.insert()
			submit_for_approval(cs.name)
		with as_user(COSTING_APPROVER):
			approve(cs.name)
		result[style] = cs.name
	return result


def setup_orders() -> dict:
	sheets = get("cost_sheets")
	result = {}
	for key, o in ORDERS.items():
		existing = frappe.db.get_value("Garment Order", {"buyer_po_no": o["po"]}, "name")
		if existing:
			result[key] = existing
			continue
		with as_user(MIRZA):
			go = frappe.get_doc(
				{
					"doctype": "Garment Order",
					"customer": o["customer"],
					"style": o["style"],
					"order_type": "Bulk",
					"order_date": days_ago(o["ordered"]),
					"ship_date": days_ahead(o["ship"]) if o["ship"] >= 0 else days_ago(-o["ship"]),
					"buyer_po_no": o["po"],
					"season": "SS27",
					"currency": CUSTOMERS[o["customer"]],
					"excess_percent": o["excess"],
					"merchandiser": MIRZA,
					"cost_sheet": sheets[o["style"]],
					"destination": None,
					"items": [
						{"colour": c, "size": s, "order_qty": q, "rate": order_rate(o)}
						for c, sizes in o["lines"].items()
						for s, q in sizes.items()
					],
					"colour_map": [
						{"order_colour": oc, "cut_colour": cc}
						for oc, cc in (o.get("colour_map") or {}).items()
					],
				}
			)
			go.insert()
			go.submit()
		result[key] = go.name
	return result


def order_rate(o: dict) -> float:
	return COST_SHEETS[o["style"]][3]


def order(key: str) -> str:
	return get("orders")[key]


# ----------------------------------------------------------------------------------------------
# Timeline: (days ago, step key, function); run oldest first
# ----------------------------------------------------------------------------------------------


def timeline() -> list[tuple]:
	t = [
		(60, "purchase_fabric", purchase_fabric),
		(58, "purchase_trims", purchase_trims),
		(56, "purchase_chemicals", purchase_chemicals),
		(55, "receive_fabric", receive_fabric),
		(54, "receive_trims", receive_trims),
		(53, "receive_chemicals", receive_chemicals),
		(52, "bill_suppliers", bill_suppliers),
		(50, "carton_po_overdue", carton_po_overdue),
		(48, "service_orders", service_orders),
		(47, "job_maps", job_maps),
		(46, "sales_orders", sales_orders),
		(46, "material_plans", material_plans),
		(45, "allocations", allocations),
		# O8: Juicy Couture, fully shipped (USD export, agent commission)
		(30, "o8_cut", lambda: cut("O8", KAFIL, 30)),
		(28, "o8_stitch_issue", lambda: issue("O8", "Stitching", 28, MS_GARMENTS)),
		(22, "o8_stitch_receive", lambda: receive("O8", "Stitching", 22, MS_GARMENTS, reject={0: 2})),
		(21, "o8_wash_issue", lambda: issue("O8", "Washing", 21)),
		(18, "o8_wash_receive", lambda: receive("O8", "Washing", 18)),
		(17, "o8_finish_issue", lambda: issue("O8", "Finishing", 17)),
		(17, "o8_accessories", lambda: accessory_issue("O8", 17)),
		(14, "o8_finish_receive", lambda: receive("O8", "Finishing", 14)),
		(12, "o8_pack", lambda: pack("O8", 12)),
		(3, "o8_ship", ship_o8),
		# O2: TCW WHIPLASH WALK, packed, ready to ship
		(24, "o2_cut", lambda: cut("O2", KAFIL, 24)),
		(23, "o2_stitch_issue", lambda: issue("O2", "Stitching", 23)),
		(16, "o2_stitch_receive", lambda: receive("O2", "Stitching", 16, reject={1: 3})),
		(15, "o2_wash_issue", lambda: issue("O2", "Washing", 15)),
		(11, "o2_wash_receive", lambda: receive("O2", "Washing", 11)),
		(10, "o2_finish_issue", lambda: issue("O2", "Finishing", 10)),
		(9, "o2_accessories", lambda: accessory_issue("O2", 9)),
		(6, "o2_finish_receive", lambda: receive("O2", "Finishing", 6)),
		(3, "o2_pack_1", lambda: pack("O2", 3, colours=["Dark Indigo"])),
		(1, "o2_pack_2", lambda: pack("O2", 1, colours=["Mid Blue"])),
		# O3: Hoodrich, ordered Washed Black, cut Black; in washing, one bundle converted
		(26, "o3_cut", lambda: cut("O3", KAFIL, 26)),
		(25, "o3_stitch_issue", lambda: issue("O3", "Stitching", 25)),
		(13, "o3_stitch_receive", lambda: receive("O3", "Stitching", 13)),
		(10, "o3_wash_issue", lambda: issue("O3", "Washing", 10)),
		(1, "o3_wash_receive_one", lambda: receive("O3", "Washing", 1, only=1)),
		# O7: older TCW order, overdue, at finishing
		(22, "o7_cut", lambda: cut("O7", KAFIL, 22)),
		(20, "o7_stitch_issue", lambda: issue("O7", "Stitching", 20)),
		(14, "o7_stitch_receive", lambda: receive("O7", "Stitching", 14)),
		(13, "o7_wash_issue", lambda: issue("O7", "Washing", 13)),
		(9, "o7_wash_receive", lambda: receive("O7", "Washing", 9)),
		(6, "o7_finish_issue", lambda: issue("O7", "Finishing", 6)),
		# O4: Ink Clothing STADE OVER at MS Garments (CMT), ageing across buckets
		(16, "o4_cut", lambda: cut("O4", KAFIL, 16)),
		(10, "o4_stitch_issue_1", lambda: issue("O4", "Stitching", 10, MS_GARMENTS, part=(0, 3))),
		(6, "o4_stitch_issue_2", lambda: issue("O4", "Stitching", 6, MS_GARMENTS, part=(1, 3))),
		(2, "o4_stitch_issue_3", lambda: issue("O4", "Stitching", 2, MS_GARMENTS, part=(2, 3))),
		(
			3,
			"o4_stitch_receive_part",
			lambda: receive("O4", "Stitching", 3, MS_GARMENTS, only=6, reject={0: 4, 2: 2}, repair={1: 2}),
		),
		# O5: Marald, cutting in progress today
		(0, "o5_cut_today", lambda: cut("O5", None, 0, colours=["Navy"], plan_other=["Sand"])),
		# Procurement and stores for O1 and the dashboards
		(9, "chemicals_to_washing", chemicals_to_washing),
		(9, "repair_gate_pass", repair_gate_pass),
		(5, "gate_return_partial", gate_return_partial),
		(14, "contractor_bills", contractor_bills),
		(8, "pay_ms_garments", pay_ms_garments),
		(2, "o1_material_plan", o1_material_plan),
		(1, "grn_pending_inspection", grn_pending_inspection),
		(0, "sample_gate_pass", sample_gate_pass),
	]
	return t


# ----------------------------------------------------------------------------------------------
# Purchasing
# ----------------------------------------------------------------------------------------------


def workflow(doctype: str, name: str, action: str) -> None:
	from frappe.model.workflow import apply_workflow

	apply_workflow(frappe.get_doc(doctype, name), action)


def approve_po(name: str) -> None:
	with as_user(L1):
		workflow("Purchase Order", name, "Approve")
	if frappe.db.get_value("Purchase Order", name, "workflow_state") == "Pending 2nd Approval":
		with as_user(L2):
			workflow("Purchase Order", name, "Approve")


def make_po(supplier: str, category: str, rows: list[dict], day: int, schedule_in: int = 10) -> str:
	with as_user(MIRZA):
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": supplier,
				"po_category": category,
				"transaction_date": days_ago(day),
				"schedule_date": add_days(days_ago(day), schedule_in),
				"items": [{**r, "schedule_date": add_days(days_ago(day), schedule_in)} for r in rows],
			}
		).insert()
		workflow("Purchase Order", po.name, "Submit for Approval")
	approve_po(po.name)
	return po.name


def purchase_fabric() -> dict:
	result = {}
	for item, (supplier, rate, lots) in FABRIC_LOTS.items():
		qty = sum(m for _l, _s, m in lots)
		result[item] = make_po(
			supplier,
			"Fabric",
			[{"item_code": item, "qty": qty, "rate": rate, "warehouse": wh("Fabric Store")}],
			60,
		)
	return result


def purchase_trims() -> dict:
	by_supplier = defaultdict(list)
	for item, (supplier, rate, qty) in TRIMS.items():
		by_supplier[supplier].append(
			{"item_code": item, "qty": qty, "rate": rate, "warehouse": wh("Trim Store")}
		)
	by_supplier["Kqing Fashion Export Co., Ltd"].append(
		{"item_code": "ACC-SWING-TAG", "qty": 2000, "rate": 6.0, "warehouse": wh("Trim Store")}
	)
	return {s: make_po(s, "Accessory", rows, 58) for s, rows in by_supplier.items()}


def purchase_chemicals() -> dict:
	return {
		"Fabritex Enterprises": make_po(
			"Fabritex Enterprises",
			"Non-Product",
			[
				{"item_code": "CHEM-WASH-ENZYME", "qty": 100, "rate": 950, "warehouse": wh("Chemical Store")},
				{"item_code": "CHEM-SOFTENER", "qty": 80, "rate": 420, "warehouse": wh("Chemical Store")},
			],
			56,
		),
		"Raheel Brothers": make_po(
			"Raheel Brothers",
			"Non-Product",
			[{"item_code": "NDL-DPX5", "qty": 500, "rate": 35, "warehouse": wh("Stores")}],
			56,
		),
	}


def receipt(po: str, day: int, challan: str, edit=None, submit=True) -> str:
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt

	with as_user(STORE):
		pr = make_purchase_receipt(po)
		pr.update({"posting_date": days_ago(day), "set_posting_time": 1, "supplier_challan_no": challan})
		if edit:
			edit(pr)
		pr.insert()
		if submit:
			pr.submit()
	return pr.name


def receive_fabric() -> dict:
	pos = get("purchase_fabric")
	result = {}
	for item, (_supplier, _rate, lots) in FABRIC_LOTS.items():

		def split(pr, lots=lots):
			row = pr.items[0]
			rows = []
			for lot, shade, metres in lots:
				r = frappe.copy_doc(row)
				r.qty = r.received_qty = metres
				r.supplier_lot_no, r.shade = lot, shade
				rows.append(r)
			pr.set("items", rows)
			for i, r in enumerate(pr.items, 1):
				r.idx = i

		result[item] = receipt(pos[item], 55, f"DC-{item[-4:]}-{len(lots)}", split)
	return result


def receive_trims() -> dict:
	pos = get("purchase_trims")
	result = {}
	for supplier, po in pos.items():
		if supplier == "Kqing Fashion Export Co., Ltd":
			# zipper: partial rejection at inspection (40 of 2,000); swing tags arrive later (pending inspection)
			def edit(pr):
				pr.set("items", [r for r in pr.items if r.item_code != "ACC-SWING-TAG"])
				for i, r in enumerate(pr.items, 1):
					r.idx = i
				z = next(r for r in pr.items if r.item_code == "ACC-ZIPPER-4.5-BRASS")
				z.received_qty, z.qty, z.rejected_qty = 2000, 1960, 40

			name = receipt(po, 54, "KQ-INV-5521", edit, submit=False)
			with as_user(STORE):
				pr = frappe.get_doc("Purchase Receipt", name)
				z = next(r for r in pr.items if r.item_code == "ACC-ZIPPER-4.5-BRASS")
				qi = frappe.get_doc(
					{
						"doctype": "Quality Inspection",
						"inspection_type": "Incoming",
						"reference_type": "Purchase Receipt",
						"reference_name": name,
						"child_row_reference": z.name,
						"item_code": z.item_code,
						"sample_size": 80,
						"inspected_by": STORE,
						"manual_inspection": 1,
						"status": "Accepted",
						"rejected_qty": 40,
						"rejection_reason": "40 zippers with broken slider pull; returned to supplier.",
						"report_date": days_ago(54),
					}
				).insert()
				qi.submit()
				pr = frappe.get_doc("Purchase Receipt", name)
				pr.submit()
			result[supplier] = name
		else:
			result[supplier] = receipt(po, 54, f"DC-{supplier[:3].upper()}-{54}")
	return result


def receive_chemicals() -> dict:
	return {s: receipt(po, 53, f"DC-{s[:3].upper()}-CHEM") for s, po in get("purchase_chemicals").items()}


def bill_suppliers() -> list[str]:
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	names = []
	for pr, bill in (
		(get("receive_fabric")["FAB-TWILL-1010"], "CT-INV-8841"),
		(get("receive_trims")["Trimstex Enterprises"], "TX-2026-1190"),
	):
		with as_user(ACCOUNTS):
			pi = make_purchase_invoice(pr)
			pi.update(
				{
					"posting_date": days_ago(52),
					"set_posting_time": 1,
					"bill_no": bill,
					"bill_date": days_ago(53),
				}
			)
			pi.insert()
			pi.submit()
		names.append(pi.name)
	return names


def carton_po_overdue() -> str:
	return make_po(
		"M.R. Carton Care",
		"Accessory",
		[{"item_code": "PKG-CARTON-60X40X20", "qty": 100, "rate": 165, "warehouse": wh("Trim Store")}],
		50,
		schedule_in=47,
	)


def service_orders() -> dict:
	result = {}
	cutting = [
		{
			"item_code": "Cutting Charges",
			"qty": sum(sum(s.values()) for s in ORDERS[k]["lines"].values()),
			"rate": 14,
			"production_process": "Cutting",
			"garment_order": order(k),
		}
		for k in ("O8", "O2", "O3", "O7", "O4")
	]
	result["kafil"] = make_po(KAFIL, "Service", cutting, 48, schedule_in=60)
	cmt = [
		{
			"item_code": "Stitching Charges (CMT)",
			"qty": sum(sum(s.values()) for s in ORDERS[k]["lines"].values()),
			"rate": 165,
			"production_process": "Stitching",
			"garment_order": order(k),
		}
		for k in ("O8", "O4")
	]
	result["ms_garments"] = make_po(MS_GARMENTS, "Service", cmt, 48, schedule_in=60)
	return result


def job_maps() -> dict:
	result = {}
	approvals = (
		"fit_sample_approved",
		"size_set_sample_approved",
		"photo_sample_approved",
		"pp_sample_approved",
		"ok_to_cut",
	)
	plan = {"O1": 3, "O6": 1}  # approvals given so far (O1 waiting for PP, O6 only fit)
	for key in ("O8", "O2", "O3", "O7", "O4", "O5", "O1", "O6"):
		with as_user(MIRZA):
			jm = frappe.get_doc(
				{
					"doctype": "Job Map",
					"merchandiser": MIRZA,
					"fabric_type": "Dyed",
					"priority": "High" if key in ("O2", "O7") else "Normal",
					"jobs": [{"garment_order": order(key)}],
					"trims_start_date": days_ago(44),
					"cutting_start_date": days_ago(40) if key not in ("O1", "O6") else days_ahead(14),
				}
			).insert()
			for field in approvals[: plan.get(key, 5)]:
				jm.set(field, 1)
			jm.save()
		result[key] = jm.name
	return result


def job_map(key: str) -> str:
	return get("job_maps")[key]


def sales_orders() -> dict:
	from velocity_ctp.velocity_ctp.doctype.garment_order.garment_order import make_sales_order

	result = {}
	for key in ("O8", "O2", "O3", "O4", "O7"):
		with as_user(MIRZA):
			name = frappe.db.get_value("Garment Order", order(key), "sales_order") or make_sales_order(
				order(key)
			)
			so = frappe.get_doc("Sales Order", name)
			if so.docstatus == 0:
				so.transaction_date = days_ago(46)
				so.po_no = ORDERS[key]["po"]
				if so.currency == "USD":
					so.conversion_rate = 276
				so.save()
				so.submit()
			if ORDERS[key].get("ship_moved"):  # the buyer moved the ship date forward; it has now passed
				go = frappe.get_doc("Garment Order", order(key))
				go.ship_date = days_ago(-ORDERS[key]["ship_moved"])
				go.save()
		result[key] = name
	return result


def material_plans() -> dict:
	"""Material Plans of the orders in production (their stock is already in the stores)."""
	result = {}
	for key in ("O8", "O2", "O3", "O7", "O4", "O5"):
		item, per_pc = STYLE_FABRIC[ORDERS[key]["style"]]
		with as_user(MIRZA):
			plan = frappe.get_doc(
				{
					"doctype": "Material Plan",
					"garment_order": order(key),
					"planning_date": days_ago(46),
					"fabrics": [
						{
							"placement": "Body",
							"fabric_item": item,
							"consumption_per_pc": per_pc,
							"wastage_percent": 3,
						}
					],
					"accessories": [
						{"accessory_item": i, "basis": "Per Piece", "consumption_per_unit": 1}
						for i in ("ACC-METAL-BUTTON", "ACC-MAIN-SIZE-LABEL", "ACC-SATIN-CARE-LABEL")
					],
				}
			).insert()
			plan.submit()
		result[key] = plan.name
	return result


def allocations() -> dict:
	result = {}
	plans = {
		"O8": {
			"ACC-METAL-BUTTON": 360,
			"ACC-WAIST-TAG": 360,
			"ACC-MAIN-SIZE-LABEL": 360,
			"ACC-SATIN-CARE-LABEL": 360,
			"ACC-ZIPPER-4.5-BRASS": 360,
			"ACC-POLYBAG-STICKER": 360,
			"PKG-CARTON-60X40X20": 15,
		},
		"O2": {
			"ACC-METAL-BUTTON": 574,
			"ACC-WAIST-TAG": 574,
			"ACC-MAIN-SIZE-LABEL": 574,
			"ACC-SATIN-CARE-LABEL": 574,
			"ACC-ZIPPER-4.5-BRASS": 574,
			"ACC-POLYBAG-STICKER": 574,
			"PKG-CARTON-60X40X20": 26,
		},
		"O4": {"ACC-METAL-BUTTON": 900, "ACC-THREAD-COATS-80": 60, "ACC-MAIN-SIZE-LABEL": 900},
	}
	for key, items in plans.items():
		with as_user(MIRZA):
			doc = frappe.get_doc(
				{
					"doctype": "Accessory Allocation",
					"job_map": job_map(key),
					"garment_order": order(key),
					"posting_date": days_ago(45),
					"items": [{"item": i, "qty": q} for i, q in items.items()],
				}
			).insert()
			doc.submit()
		result[key] = doc.name
	return result


# ----------------------------------------------------------------------------------------------
# Production
# ----------------------------------------------------------------------------------------------


def fabric_batches(item: str) -> list[str]:
	return frappe.get_all(
		"Batch", filters={"item": item, "supplier_lot_no": ("is", "set")}, pluck="name", order_by="name"
	)


def free_batch(item: str, need: float) -> str:
	from erpnext.stock.doctype.batch.batch import get_batch_qty

	for batch in fabric_batches(item):
		if flt(get_batch_qty(batch_no=batch, warehouse=wh("Fabric Store"))) >= need:
			return batch
	frappe.throw(f"No lot of {item} has {need} m in the Fabric Store.")


def cut(
	key: str, contractor: str | None, day: int, colours: list | None = None, plan_other: list | None = None
) -> dict:
	"""Fabric issue, one marker per colour (ratio 1 per size) and the Cut Receive of the given colours."""
	o = ORDERS[key]
	item, per_pc = STYLE_FABRIC[o["style"]]
	jm, go = job_map(key), order(key)
	markers = []
	for colour in list(o["lines"]):
		sizes = o["lines"][colour]
		plies = max(sizes.values())
		length = round(len(sizes) * per_pc, 2)
		need = round(length * plies * 1.02 + 0.5, 1)
		batch = free_batch(item, need)
		with as_user(CUTTER):
			fi = frappe.get_doc(
				{
					"doctype": "Fabric Issue",
					"issue_type": "Issue",
					"job_map": jm,
					"cutting_party": contractor,
					"posting_date": days_ago(day + 1),
					"items": [
						{
							"fabric_item": item,
							"batch_no": batch,
							"qty": need,
							"shade_remarks": frappe.db.get_value("Batch", batch, "shade"),
						}
					],
				}
			).insert()
			fi.submit()
			mk = frappe.get_doc(
				{
					"doctype": "Cutting Marker",
					"job_map": jm,
					"garment_order": go,
					"colour": colour,
					"fabric_item": item,
					"batch_no": batch,
					"cutting_party": contractor,
					"marker_length": length,
					"no_of_plies": plies,
					"end_loss_percent": 2,
					"marker_efficiency": 86.5,
					"size_ratio": [{"size": s, "ratio": 1} for s in sizes],
				}
			).insert()
			mk.submit()
		markers.append((colour, mk.name))
	to_cut = [m for c, m in markers if not colours or c in colours]
	with as_user(CUTTER):
		cr = frappe.get_doc(
			{
				"doctype": "Cut Receive",
				"job_map": jm,
				"cutting_party": contractor,
				"posting_date": days_ago(day),
				"service_order": get("service_orders")["kafil"] if contractor == KAFIL else None,
				"markers": [{"cutting_marker": m} for m in to_cut],
			}
		)
		cr.sync_from_markers()
		for p in cr.pieces:
			colour = next(c for c, m in markers if m == p.cutting_marker)
			p.cut_qty = o["lines"][colour].get(p.size, 0)
			p.rejected_qty = 1 if (p.size == list(o["lines"][colour])[-1] and p.cut_qty > 50) else 0
		for f in cr.fabric:
			f.used_qty = round(flt(f.required_qty) * 0.985, 1)
		cr.insert()
		cr.submit()
	return {"markers": [m for _c, m in markers], "cut_receive": cr.name}


def bundles_of(key: str, status: tuple = ("In Cutting", "Received", "Issued")) -> list[frappe._dict]:
	return frappe.get_all(
		"Bundle",
		filters={"garment_order": order(key), "status": ("in", status)},
		fields=["name", "qty", "colour", "size", "current_process", "status", "pending_repair_qty"],
		order_by="name",
	)


def issue(key: str, process: str, day: int, party: str | None = None, part: tuple | None = None) -> str:
	from velocity_ctp.production.flow import issue_block

	ready = [b for b in bundles_of(key) if not issue_block(frappe.get_doc("Bundle", b.name), process)]
	if part:
		index, parts = part
		size = -(-len(ready) // (parts - index))  # spread what is left over the remaining issues
		ready = ready[:size]
	service_order = None
	if party:
		service_order = get("service_orders")["ms_garments" if party == MS_GARMENTS else "kafil"]
	with as_user(PRODUCTION):
		doc = frappe.get_doc(
			{
				"doctype": "Process Issue",
				"production_process": process,
				"party": party,
				"service_order": service_order,
				"posting_date": days_ago(day),
				"vehicle_no": "KHI-4417" if party else None,
				"driver_name": "Saleem Ahmed" if party else None,
				"bundles": [{"bundle": b.name} for b in ready],
			}
		).insert()
		doc.submit()
	if party:  # the challan leaves the gate
		gate_outward("Process Challan", "Process Issue", doc.name, day)
	return doc.name


def receive(
	key: str,
	process: str,
	day: int,
	party: str | None = None,
	only: int | None = None,
	reject: dict | None = None,
	repair: dict | None = None,
) -> str:
	from velocity_ctp.production.flow import outstanding_qty

	open_bundles = [
		b
		for b in frappe.get_all(
			"Bundle",
			filters={"garment_order": order(key), "status": "Issued", "current_process": process},
			fields=["name"],
			order_by="name",
		)
	]
	if only:
		open_bundles = open_bundles[:only]
	with as_user(PRODUCTION):
		doc = frappe.get_doc(
			{
				"doctype": "Process Receive",
				"production_process": process,
				"party": party,
				"posting_date": days_ago(day),
				"bundles": [],
			}
		)
		for i, b in enumerate(open_bundles):
			qty = outstanding_qty(frappe.get_doc("Bundle", b.name))
			rej, rep = (reject or {}).get(i, 0), (repair or {}).get(i, 0)
			doc.append(
				"bundles",
				{"bundle": b.name, "fresh_qty": qty - rej - rep, "rejected_qty": rej, "repair_qty": rep},
			)
		doc.insert()
		doc.submit()
	return doc.name


ACCESSORY_USE = {
	"Finishing": [
		"ACC-METAL-BUTTON",
		"ACC-WAIST-TAG",
		"ACC-MAIN-SIZE-LABEL",
		"ACC-SATIN-CARE-LABEL",
		"ACC-ZIPPER-4.5-BRASS",
	],
	"Packing": ["ACC-POLYBAG-STICKER", "PKG-CARTON-60X40X20"],
}


def accessory_issue(key: str, day: int) -> list[str]:
	allocated = {
		r.item: flt(r.qty) for r in frappe.get_doc("Accessory Allocation", get("allocations")[key]).items
	}
	names = []
	for process, items in ACCESSORY_USE.items():
		rows = [{"item": i, "qty": allocated[i]} for i in items if i in allocated]
		with as_user(STORE):
			doc = frappe.get_doc(
				{
					"doctype": "Accessory Issue",
					"issue_type": "Issue",
					"job_map": job_map(key),
					"garment_order": order(key),
					"to_process": process,
					"posting_date": days_ago(day),
					"items": rows,
				}
			).insert()
			doc.submit()
		names.append(doc.name)
	return names


def pack(key: str, day: int, colours: list | None = None) -> str:
	from velocity_ctp.velocity_ctp.doctype.packing_list.packing_list import get_available, get_next_carton

	lines = [line for line in get_available(order(key)) if not colours or line["colour"] in colours]
	carton = get_next_carton(order(key))
	rows = []
	for line in lines:
		full, rest = divmod(cint(line["qty"]), 24)
		if full:
			rows.append(
				{
					"carton_from": carton,
					"carton_to": carton + full - 1,
					"colour": line["colour"],
					"size": line["size"],
					"pcs_per_carton": 24,
				}
			)
			carton += full
		if rest:
			rows.append(
				{
					"carton_from": carton,
					"carton_to": carton,
					"colour": line["colour"],
					"size": line["size"],
					"pcs_per_carton": rest,
				}
			)
			carton += 1
	pcs = sum((r["carton_to"] - r["carton_from"] + 1) * r["pcs_per_carton"] for r in rows)
	cartons = sum(r["carton_to"] - r["carton_from"] + 1 for r in rows)
	with as_user(PRODUCTION):
		doc = frappe.get_doc(
			{
				"doctype": "Packing List",
				"garment_order": order(key),
				"packing_date": days_ago(day),
				"cartons": rows,
				"net_weight": round(pcs * 0.48, 2),
				"gross_weight": round(pcs * 0.48 + cartons * 1.1, 2),
			}
		).insert()
		doc.submit()
	return doc.name


# ----------------------------------------------------------------------------------------------
# Shipment (O8): Delivery Note, gate pass, USD Commercial Invoice with agent commission
# ----------------------------------------------------------------------------------------------


def ship_o8() -> dict:
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

	from velocity_ctp.shipping.delivery import make_delivery_note

	with as_user(MIRZA):
		dn = frappe.get_doc("Delivery Note", make_delivery_note([get("o8_pack")]))
		dn.update({"posting_date": days_ago(3), "set_posting_time": 1})
		dn.save()
		dn.submit()
	gate_outward("Delivery", "Delivery Note", dn.name, 3)
	with as_user(ACCOUNTS):
		si = make_sales_invoice(dn.name)
		si.update(
			{
				"posting_date": days_ago(3),
				"set_posting_time": 1,
				"due_date": days_ahead(57),
				"invoice_category": "Export",
				"shipment_type": "By Sea",
				"payment_mode": "LC",
				"lc_contract_no": "LC-HBL-2611-0457",
				"lc_date": days_ago(40),
				"draft_at": "At Sight",
				"form_e_no": "FE-KHI-88412",
				"form_e_date": days_ago(4),
				"port_of_loading": "Karachi, Pakistan",
				"destination": "Los Angeles, USA",
				"vessel_flight": "MAERSK KOWLOON V.612E",
				"vessel_date": days_ago(2),
				"bl_awb_no": "MAEU 261188420",
				"bl_awb_date": days_ago(2),
				"container_no": "MSKU 7741203",
				"notify_party": "Juicy Couture Logistics, 2140 E 7th St, Los Angeles CA",
				"sales_partner": "Ink Clothing",
				"commission_rate": 5,
				"conversion_rate": 276,
			}
		)
		si.insert()
		si.submit()
	return {"delivery_note": dn.name, "sales_invoice": si.name}


# ----------------------------------------------------------------------------------------------
# Stores, gate, contractor billing, procurement for O1
# ----------------------------------------------------------------------------------------------


def chemicals_to_washing() -> str:
	dept = frappe.db.get_value("Department", {"department_name": "Washing", "company": company()})
	with as_user(STORE):
		doc = frappe.get_doc(
			{
				"doctype": "Department Issue",
				"issue_type": "Issue",
				"department": dept,
				"posting_date": days_ago(9),
				"purpose": "Enzyme and softener for washing (WHIPLASH WALK, ORIGIN OVERSIZED)",
				"warehouse": wh("Chemical Store"),
				"items": [{"item": "CHEM-WASH-ENZYME", "qty": 25}, {"item": "CHEM-SOFTENER", "qty": 15}],
			}
		).insert()
		doc.submit()
	return doc.name


def gate_outward(
	kind: str,
	reference_doctype: str | None,
	reference: str | None,
	day: int,
	rows: list | None = None,
	party: tuple | None = None,
	handover: str = "Driver",
) -> str:
	from velocity_ctp.shipping.gate import get_reference_items

	with as_user(STORE):
		data = get_reference_items(reference_doctype, reference) if reference else {}
		doc = frappe.get_doc(
			{
				"doctype": "Gate Outward",
				"gate_pass_type": kind,
				"entry_date": days_ago(day),
				"reference_doctype": reference_doctype,
				"reference_name": reference,
				"party_type": (party or (data.get("party_type"),))[0],
				"party": party[1] if party else data.get("party"),
				"vehicle_no": data.get("vehicle_no") or "KHI-2214",
				"driver_name": data.get("driver_name") or "Saleem Ahmed",
				"handover_to": handover,
				"items": rows or data.get("items"),
			}
		).insert()
		workflow(
			"Gate Outward",
			doc.name,
			"Submit" if kind in ("Delivery", "Process Challan", "Purchase Return") else "Submit for Approval",
		)
	if kind not in ("Delivery", "Process Challan", "Purchase Return"):
		with as_user(PRODUCTION):
			workflow("Gate Outward", doc.name, "Approve")
	return doc.name


def repair_gate_pass() -> str:
	return gate_outward(
		"Repair",
		None,
		None,
		9,
		rows=[
			{
				"description": "Overlock machine motor (Juki MO-6714S)",
				"uom": "Nos",
				"qty": 2,
				"returnable": 1,
				"expected_return_date": days_ago(4),
			},
			{
				"description": "Straight knife cutting machine blade (KM 10 inch) for sharpening",
				"uom": "Nos",
				"qty": 1,
				"returnable": 1,
				"expected_return_date": days_ago(5),
			},
		],
		party=("Supplier", "Fabritex Enterprises"),
		handover="Al-Madina Electric Works",
	)


def gate_return_partial() -> str:
	from velocity_ctp.shipping.gate import get_returnable_items

	out = get("repair_gate_pass")
	rows = [r for r in get_returnable_items(out) if "blade" in (r["description"] or "")]
	with as_user(STORE):
		doc = frappe.get_doc(
			{
				"doctype": "Gate Inward",
				"gate_pass_type": "Repair Return",
				"entry_date": days_ago(5),
				"against_gate_outward": out,
				"party_type": "Supplier",
				"party": "Fabritex Enterprises",
				"vehicle_no": "KHI-7781",
				"items": rows,
			}
		).insert()
		doc.submit()
	return doc.name  # the two motors are still out (open returnable, overdue)


def contractor_bills() -> dict:
	from velocity_ctp.velocity_ctp.doctype.contractor_bill_run.contractor_bill_run import get_unbilled_work

	result = {}
	for supplier, upto in ((KAFIL, 23), (MS_GARMENTS, 21)):
		work = get_unbilled_work(supplier, days_ago(40), days_ago(upto), company())
		with as_user(ACCOUNTS):
			run = frappe.get_doc(
				{
					"doctype": "Contractor Bill Run",
					"supplier": supplier,
					"from_date": days_ago(40),
					"to_date": days_ago(upto),
					"posting_date": days_ago(14),
					"items": work,
				}
			).insert()
			run.submit()
			pi = frappe.get_doc(
				"Purchase Invoice", frappe.db.get_value("Contractor Bill Run", run.name, "purchase_invoice")
			)
			pi.update(
				{
					"posting_date": days_ago(14),
					"set_posting_time": 1,
					"bill_no": f"{supplier[:3].upper()}-{run.name[-5:]}",
					"bill_date": days_ago(15),
				}
			)
			pi.save()
			pi.submit()
		result[supplier] = {"bill_run": run.name, "invoice": pi.name}
	return result


def pay_ms_garments() -> str:
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	invoice = get("contractor_bills")[MS_GARMENTS]["invoice"]
	with as_user(ACCOUNTS):
		pe = get_payment_entry("Purchase Invoice", invoice)
		pe.update(
			{
				"posting_date": days_ago(8),
				"reference_no": "CHQ-004417",
				"reference_date": days_ago(8),
				"mode_of_payment": "Cheque",
			}
		)
		pe.insert()
		pe.submit()
	return pe.name


def o1_material_plan() -> dict:
	from velocity_ctp.velocity_ctp.doctype.material_plan.material_plan import (
		create_material_request,
		get_cost_sheet_lines,
	)

	go = order("O1")
	with as_user(MIRZA):
		lines = get_cost_sheet_lines(go)
		plan = frappe.get_doc(
			{
				"doctype": "Material Plan",
				"garment_order": go,
				"planning_date": days_ago(2),
				"fabrics": [{**f, "wastage_percent": 3} for f in lines["fabrics"]],
				"accessories": [
					{"accessory_item": i, "basis": "Per Piece", "consumption_per_unit": c}
					for i, c in (
						("ACC-METAL-BUTTON", 1),
						("ACC-WAIST-TAG", 1),
						("ACC-MAIN-SIZE-LABEL", 1),
						("ACC-ZIPPER-4.5-BRASS", 1),
						("ACC-SWING-TAG", 1),
					)
				],
			}
		).insert()
		plan.submit()
		requests = create_material_request(plan.name)
		for mr in requests:
			workflow("Material Request", mr, "Submit for Approval")
	fabric_mr = next(
		m for m in requests if frappe.db.get_value("Material Request", m, "request_category") == "Fabric"
	)
	with as_user(L1):
		workflow("Material Request", fabric_mr, "Approve")  # the accessory request stays pending approval
	from erpnext.stock.doctype.material_request.material_request import make_purchase_order

	with as_user(MIRZA):
		po = make_purchase_order(fabric_mr)
		po.supplier = "Imran Brother"
		po.schedule_date = days_ahead(20)
		for r in po.items:
			r.rate, r.schedule_date = 850, days_ahead(20)
		po.supplier_pi_no = "IB-PI-2611-07"
		po.insert()
		workflow("Purchase Order", po.name, "Submit for Approval")
	with as_user(L1):
		workflow("Purchase Order", po.name, "Approve")  # above the limit: waits for the 2nd approval
	return {"material_plan": plan.name, "material_requests": requests, "purchase_order": po.name}


def grn_pending_inspection() -> str:
	po = get("purchase_trims")["Kqing Fashion Export Co., Ltd"]

	def only_swing_tags(pr):
		pr.set("items", [r for r in pr.items if r.item_code == "ACC-SWING-TAG"])
		pr.items[0].idx = 1

	return receipt(po, 1, "KQ-INV-5560", only_swing_tags, submit=False)  # draft: waits for the inspection


def sample_gate_pass() -> str:
	with as_user(STORE):
		doc = frappe.get_doc(
			{
				"doctype": "Gate Outward",
				"gate_pass_type": "Sample",
				"entry_date": nowdate(),
				"party_type": "Customer",
				"party": "Juicy Couture",
				"handover_to": "DHL Express",
				"delivery_challan_no": "DHL 4471 2290 18",
				"items": [
					{
						"description": "JCTDN009 PP sample, Camo Green size 10 (for PP approval)",
						"uom": "Nos",
						"qty": 2,
					}
				],
			}
		).insert()
		workflow("Gate Outward", doc.name, "Submit for Approval")  # waits for the gate approver
	return doc.name


# ----------------------------------------------------------------------------------------------
# Demo data map
# ----------------------------------------------------------------------------------------------


def write_data_map() -> str:
	path = os.path.join(os.path.dirname(__file__), "DEMO_DATA.md")
	orders = get("orders") or {}
	if not orders:
		return path
	sheets = get("cost_sheets") or {}
	jms = get("job_maps") or {}
	lines = [
		"# Velocity CTP demo data map",
		"",
		f"Site `{frappe.local.site}`, seeded on {getdate(frappe.db.get_value('Garment Order', orders['O1'], 'creation')).isoformat()} "
		"(dates are relative to that day). Regenerated by `velocity_ctp.demo.seed.run`.",
		"",
		"## Logins",
		"",
		f"Password for every demo user: `{PASSWORD}` (e-mail addresses are not deliverable; e-mail is off).",
		"",
		"| User | Login | Use for |",
		"|---|---|---|",
	]
	for local, full_name, _roles, label in USERS:
		lines.append(f"| {full_name} | `{email(local)}` | {label} |")
	lines += [
		"| Administrator | `Administrator` | Everything (the password set when the site was created) |",
		"",
		"## Orders",
		"",
		"| # | Job # | Customer / Style | Qty | Job Map | Cost Sheet | Material Plan | Stage |",
		"|---|---|---|---|---|---|---|---|",
	]
	stage = {
		"O1": "Approvals: waiting for PP sample; material shortfall; requisition pending approval; fabric PO pending 2nd approval",
		"O2": "Cut, stitched, washed, finished and packed in cartons; ships in 5 days (Ready to Ship)",
		"O3": "Ordered Washed Black, cut Black; stitched; at washing (8+ days), one bundle already washed into Washed Black",
		"O4": "At MS Garments for CMT stitching (issued 10, 6 and 2 days ago); part received with rejections, 2 repair pieces pending",
		"O5": "OK to Cut; Navy cut today, Sand marker planned",
		"O6": "Approvals pending (fit only), ships in 10 days: At risk; margin below target (Margin Watch)",
		"O7": "Ship date passed (overdue); at finishing, not packed",
		"O8": "Fully shipped and invoiced: export Commercial Invoice in USD with agent commission (Ink Clothing)",
	}
	plans = {**(get("material_plans") or {}), "O1": (get("o1_material_plan") or {}).get("material_plan")}
	for key, o in ORDERS.items():
		go = orders.get(key)
		qty = sum(sum(s.values()) for s in o["lines"].values())
		lines.append(
			f"| {key} | {go} | {o['customer']} / {o['style']} | {qty:,} | {jms.get(key, '—')} | {sheets.get(o['style'], '—')} | "
			f"{plans.get(key) or '—'} | {stage[key]} |"
		)
	ship = get("o8_ship") or {}
	bills = get("contractor_bills") or {}
	o1 = get("o1_material_plan") or {}
	washing_open = frappe.get_all(
		"Bundle",
		filters={"garment_order": orders.get("O3"), "status": "Issued", "current_process": "Washing"},
		fields=["name", "colour", "order_colour", "size", "qty"],
		order_by="name",
		limit=5,
	)
	lines += [
		"",
		"## Best record for each feature",
		"",
		"| Feature | Open |",
		"|---|---|",
		f"| Quantity matrix and Cut Colours | Garment Order {orders.get('O3')} (Washed Black cut from Black) |",
		f"| Approval cards | Job Map {jms.get('O1')} (waiting for PP) and {jms.get('O6')} |",
		f"| Control Tower ageing | Production Control: {orders.get('O4')} at MS Garments (0-3, 4-7, 8+ days) and {orders.get('O3')} at Washing |",
		f"| Margin Watch | Velocity Home: {orders.get('O6')} (SKINNY JEANS 5PKT) |",
		f"| Order Costing / Order Closing Sheet | {orders.get('O8')} (fully shipped) |",
		f"| PO approval (2nd level) | Purchase Order {o1.get('purchase_order')} (camo fabric, above the limit) |",
		f"| Requisition approval | Material Request {next((m for m in o1.get('material_requests', []) if frappe.db.get_value('Material Request', m, 'workflow_state') == 'Pending Approval'), '—')} |",
		f"| Partial rejection | Purchase Receipt {(get('receive_trims') or {}).get('Kqing Fashion Export Co., Ltd')} (zippers: 40 of 2,000 rejected at inspection) |",
		f"| GRN pending inspection | Purchase Receipt {get('grn_pending_inspection')} (swing tags) |",
		f"| Commercial Invoice (USD, agent commission) | Sales Invoice {ship.get('sales_invoice')} (print: Commercial Invoice) |",
		f"| Contractor billing | Contractor Bill Run {(bills.get(KAFIL) or {}).get('bill_run')} and {(bills.get(MS_GARMENTS) or {}).get('bill_run')}; Accrued Contractor Charges report |",
		f"| Open returnable gate pass | Gate Outward {get('repair_gate_pass')} (2 overlock motors still out, overdue) |",
		f"| Gate approval | Gate Outward {get('sample_gate_pass')} (PP sample, waiting for the gate approver) |",
		f"| Overdue PO | Purchase Order {get('carton_po_overdue')} (cartons, M.R. Carton Care) |",
		f"| Service orders | Purchase Order {(get('service_orders') or {}).get('kafil')} (Kafil cutting) and {(get('service_orders') or {}).get('ms_garments')} (MS Garments CMT) |",
		f"| Chemicals issue to Washing | Department Issue {get('chemicals_to_washing')} |",
		f"| Ready to ship | Packing Lists {get('o2_pack_1')} and {get('o2_pack_2')} of {orders.get('O2')} |",
		"",
		"## Bundles to scan live",
		"",
		f"Bundles of {orders.get('O3')} at Washing, ready for **Scan Station → Washing → Receive** (they turn into Washed Black on receipt), "
		"then **Finishing → Issue**:",
		"",
		"| Bundle (barcode) | Colour now | Order colour | Size | Pieces |",
		"|---|---|---|---|---|",
	]
	for b in washing_open:
		lines.append(f"| `{b.name}` | {b.colour} | {b.order_colour} | {b.size} | {b.qty} |")
	washed = frappe.get_all(
		"Bundle",
		filters={"garment_order": orders.get("O3"), "status": "Received", "current_process": "Washing"},
		pluck="name",
	)
	cut_today = frappe.get_all(
		"Bundle",
		filters={"garment_order": orders.get("O5"), "status": "In Cutting"},
		pluck="name",
		order_by="name",
		limit=3,
	)
	lines += [
		"",
		f"Already washed (Washed Black), ready for **Finishing → Issue**: {', '.join(f'`{b}`' for b in washed) or '—'}.",
		f"Cut today ({orders.get('O5')}, Navy), ready for **Stitching → Issue**: {', '.join(f'`{b}`' for b in cut_today) or '—'}.",
	]
	with open(path, "w") as fh:
		fh.write("\n".join(lines) + "\n")
	print(f"Demo data map written to {path}")
	return path
