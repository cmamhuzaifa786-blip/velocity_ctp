"""Company setup for a Velocity demo site (by script, no setup wizard in the browser).

Run once on a new demo site, after `bench new-site ... --install-app erpnext --install-app velocity_ctp`:

    bench --site velocity-demo.local execute velocity_ctp.demo.setup_site.run

It refuses to run on a site whose name does not contain "demo". Steps (each is skipped when already done):
1. ERPNext setup wizard: Velocity Textiles (Pvt.) Ltd. (VT), Pakistan, PKR, Asia/Karachi, fiscal year
   1 July - 30 June, standard chart of accounts
2. velocity_ctp.setup.install.setup_masters()
3. velocity_ctp.setup.procurement_settings.apply()
4. Letter head "Velocity Textiles" (default), with a placeholder for the logo
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

COMPANY = "Velocity Textiles (Pvt.) Ltd."
ABBR = "VT"
LETTER_HEAD = "Velocity Textiles"

# The logo placeholder: upload the logo, then replace the <div class="vt-lh-logo"> ... </div> block in the
# Letter Head's HTML with <img src="/files/<your-logo>.png" style="max-height:20mm">.
LETTER_HEAD_HTML = """<table style="width:100%; border-collapse:collapse; font-family:Inter, Arial, sans-serif; color:#111;">
	<tr>
		<td style="width:32mm; vertical-align:middle;">
			<div class="vt-lh-logo" style="width:28mm; height:18mm; border:1.5px dashed #9aa4b2; border-radius:2mm;
				display:flex; align-items:center; justify-content:center; color:#6b7480; font-size:8pt; text-align:center;">
				LOGO<br>(replace in Letter Head)
			</div>
		</td>
		<td style="vertical-align:middle; padding-left:4mm;">
			<div style="font-size:15pt; font-weight:700; letter-spacing:.01em;">Velocity Textiles (Pvt.) Ltd.</div>
			<div style="font-size:8.5pt; color:#444; line-height:1.45;">
				F-235, S.I.T.E., Near Fire Brigade, Sindh Industrial Trading Estate, Karachi<br>
				Tel 021-32580120-2 &nbsp;·&nbsp; info@velocitytex.com &nbsp;·&nbsp; NTN 4046558-6
			</div>
		</td>
	</tr>
</table>
<div style="border-bottom:1.5px solid #111; margin:2mm 0 1mm;"></div>"""


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


def ensure_letter_head() -> bool:
	if frappe.db.exists("Letter Head", LETTER_HEAD):
		return False
	frappe.get_doc(
		{
			"doctype": "Letter Head",
			"letter_head_name": LETTER_HEAD,
			"source": "HTML",
			"content": LETTER_HEAD_HTML,
			"is_default": 1,
		}
	).insert(ignore_permissions=True)
	return True


def run() -> None:
	check_demo_site()
	print("Company setup:", "done" if setup_company() else "already set up")
	from velocity_ctp.setup import procurement_settings
	from velocity_ctp.setup.install import setup_masters

	setup_masters()
	procurement_settings.apply()
	print("Letter head:", "created" if ensure_letter_head() else "already exists")
	frappe.db.commit()
