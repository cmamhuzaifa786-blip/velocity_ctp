"""Velocity Textiles branding: the logo on the letter head, prints, desk and login page.

Run once on an existing site (safe to run again):

    bench --site <site> execute velocity_ctp.setup.branding.apply

It only fills in what is missing; it never overwrites a logo or letter head someone has set:
- Letter Head "Velocity Textiles": replaces the dashed LOGO placeholder with the logo; creates the letter
  head when the site has none, and makes it the default only when the default is ERPNext's generic one
- Navbar Settings logo, Website Settings logo, favicon and splash image: set only when empty
- Desktop Icon "Velocity": logo set only when empty

The logo files are in velocity_ctp/public/images (served at /assets/velocity_ctp/images/):
- velocity_logo.png       the client's file (red-to-black V on a transparent background)
- velocity_logo_mark.png   the same, cropped to the mark (prints)
- velocity_logo_tile.png   the mark on a white rounded tile (app and desktop icon, dark backgrounds)
- velocity_favicon.png     the tile at 64 px (browser tab)
- velocity_logo_small.png  the mark at 48 px (thermal bundle tickets)
"""

from __future__ import annotations

import base64
import os
import re
from functools import lru_cache

import frappe

IMAGES = "/assets/velocity_ctp/images"
LOGO = f"{IMAGES}/velocity_logo.png"
LOGO_MARK = f"{IMAGES}/velocity_logo_mark.png"
LOGO_TILE = f"{IMAGES}/velocity_logo_tile.png"
FAVICON = f"{IMAGES}/velocity_favicon.png"

LETTER_HEAD = "Velocity Textiles"
# ERPNext creates these during setup; a site still using one of them has not chosen a letter head.
GENERIC_LETTER_HEADS = ("Company Letterhead", "Company Letterhead - Grey")
DESKTOP_ICON = "Velocity"

PLACEHOLDER = re.compile(r'<div class="vt-lh-logo"[^>]*>.*?</div>', re.S)


@lru_cache(maxsize=2)
def logo_data_uri(small: bool = False) -> str:
	"""The cropped logo as a data URI: prints and PDFs show it without fetching a URL (wkhtmltopdf, e-mail
	attachments, sites reached by IP)."""
	name = "velocity_logo_small.png" if small else "velocity_logo_mark.png"
	path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "images", name)
	with open(path, "rb") as fh:
		return "data:image/png;base64," + base64.b64encode(fh.read()).decode()


def velocity_logo_src(small: bool = False) -> str:
	"""Jinja method for print formats: {{ velocity_logo_src() }}; small=True for thermal tickets."""
	return logo_data_uri(bool(small))


def logo_img(height: str = "18mm") -> str:
	return (
		f'<img class="vt-lh-logo-img" src="{logo_data_uri()}" alt="Velocity Textiles" '
		f'style="height:{height}; width:auto; max-height:{height}; display:block;">'
	)


def letter_head_html() -> str:
	return f"""<table style="width:100%; border-collapse:collapse; border:none; margin:0; font-family:Inter, Arial, sans-serif; color:#111;">
	<tr>
		<td style="width:22mm; vertical-align:middle; border:none; padding:0;">
			{logo_img()}
		</td>
		<td style="vertical-align:middle; border:none; padding:0 0 0 3mm;">
			<div style="font-size:15pt; font-weight:700; letter-spacing:.01em;">Velocity Textiles (Pvt.) Ltd.</div>
			<div style="font-size:8.5pt; color:#444; line-height:1.45;">
				F-235, S.I.T.E., Near Fire Brigade, Sindh Industrial Trading Estate, Karachi<br>
				Tel 021-32580120-2 &nbsp;·&nbsp; info@velocitytex.com &nbsp;·&nbsp; NTN 4046558-6
			</div>
		</td>
	</tr>
</table>
<div style="border-bottom:1.5px solid #111; margin:2mm 0 1mm;"></div>"""


def _letter_head() -> str | None:
	if not frappe.db.exists("Letter Head", LETTER_HEAD):
		doc = frappe.get_doc(
			{
				"doctype": "Letter Head",
				"letter_head_name": LETTER_HEAD,
				"source": "HTML",
				"content": letter_head_html(),
			}
		)
		doc.insert(ignore_permissions=True)
		doc.db_set("source", "HTML")  # Letter Head.before_insert switches new ones to "Image"
		result = "created"
	else:
		content = frappe.db.get_value("Letter Head", LETTER_HEAD, "content") or ""
		if not PLACEHOLDER.search(content):
			result = None  # already has a logo (or was edited by hand): leave it
		else:
			doc = frappe.get_doc("Letter Head", LETTER_HEAD)
			doc.content = PLACEHOLDER.sub(logo_img(), content, count=1)
			doc.content = doc.content.replace(
				"width:32mm; vertical-align:middle;", "width:22mm; vertical-align:middle;", 1
			)
			doc.source = "HTML"  # the content is HTML; "Image" would expect an attachment
			doc.save(ignore_permissions=True)
			result = "logo added"

	default = frappe.db.get_value("Letter Head", {"is_default": 1}, "name")
	if default != LETTER_HEAD and (not default or default in GENERIC_LETTER_HEADS):
		doc = frappe.get_doc("Letter Head", LETTER_HEAD)
		doc.is_default = 1
		doc.save(ignore_permissions=True)
		result = (result + ", " if result else "") + f"default (was {default or 'none'})"
	return result


def _set_if_empty(doctype: str, fieldname: str, value: str, name: str | None = None) -> bool:
	if name:
		if frappe.db.get_value(doctype, name, fieldname):
			return False
		frappe.db.set_value(doctype, name, fieldname, value)
	else:
		if frappe.db.get_single_value(doctype, fieldname):
			return False
		frappe.db.set_single_value(doctype, fieldname, value)
	return True


def apply() -> dict:
	changes = {}
	letter_head = _letter_head()
	if letter_head:
		changes["Letter Head"] = letter_head
	for doctype, fieldname, value in (
		("Navbar Settings", "app_logo", LOGO),
		("Website Settings", "app_logo", LOGO),
		("Website Settings", "favicon", FAVICON),
		("Website Settings", "splash_image", LOGO),
	):
		if _set_if_empty(doctype, fieldname, value):
			changes[f"{doctype}.{fieldname}"] = value
	if frappe.db.exists("Desktop Icon", DESKTOP_ICON) and _set_if_empty(
		"Desktop Icon", "logo_url", LOGO_TILE, DESKTOP_ICON
	):
		changes["Desktop Icon.logo_url"] = LOGO_TILE
	frappe.db.commit()
	frappe.clear_cache()
	print("Branding:", changes or "nothing to change")
	return changes
