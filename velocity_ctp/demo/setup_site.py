"""Company setup for a Velocity demo site (by script, no setup wizard in the browser).

Run once on a new demo site, after `bench new-site ... --install-app erpnext --install-app velocity_ctp`:

    bench --site velocity-demo.local execute velocity_ctp.demo.setup_site.run

It refuses to run on a site whose name does not contain "demo". Steps (each is skipped when already done):
1. ERPNext setup wizard: Velocity Textiles (Pvt.) Ltd. (VT), Pakistan, PKR, Asia/Karachi, fiscal year
   1 July - 30 June, standard chart of accounts
2. velocity_ctp.setup.install.setup_masters()
3. velocity_ctp.setup.procurement_settings.apply()
4. Branding: letter head "Velocity Textiles" with the logo (default), app logo and favicon
   (velocity_ctp.setup.branding.apply)
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

COMPANY = "Velocity Textiles (Pvt.) Ltd."
ABBR = "VT"


def check_demo_site() -> None:
	if "demo" not in (frappe.local.site or ""):
		frappe.throw(
			f"This script only runs on a demo site (the site name must contain 'demo'), not on {frappe.local.site}."
		)


def fiscal_year_dates(today=None) -> tuple[str, str]:
	"""Fiscal year 1 July - 30 June that contains today."""
	today = getdate(today or nowdate())
	start_year = today.year if today.month >= 7 else today.year - 1
	return f"{start_year}-07-01", f"{start_year + 1}-06-30"


def setup_company() -> bool:
	"""Run ERPNext's setup wizard steps by script. Returns False when the site was already set up."""
	if frappe.is_setup_complete():
		return False
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	start, end = fiscal_year_dates()
	result = setup_complete(
		{
			"language": "English",
			"country": "Pakistan",
			"timezone": "Asia/Karachi",
			"currency": "PKR",
			"full_name": "Administrator",
			"email": "admin@velocitytex.com",
			"company_name": COMPANY,
			"company_abbr": ABBR,
			"chart_of_accounts": "Standard",
			"fy_start_date": start,
			"fy_end_date": end,
			"setup_demo": 0,
		}
	)
	frappe.db.commit()
	if (result or {}).get("status") != "ok":
		frappe.throw(f"The setup wizard did not finish: {result}")
	return True


def run() -> None:
	check_demo_site()
	print("Company setup:", "done" if setup_company() else "already set up")
	from velocity_ctp.setup import procurement_settings
	from velocity_ctp.setup.install import setup_masters

	setup_masters()
	procurement_settings.apply()
	from velocity_ctp.setup import branding

	branding.apply()
	frappe.db.commit()
