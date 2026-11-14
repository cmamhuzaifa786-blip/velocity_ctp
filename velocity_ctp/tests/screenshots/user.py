"""Temporary user for the screenshot check (development only; never imported by the app).

Run through bench by tests/screenshots/run.js:
    bench --site <site> execute velocity_ctp.tests.screenshots.user.create
    bench --site <site> execute velocity_ctp.tests.screenshots.user.delete
"""

from __future__ import annotations

import secrets

import frappe
from frappe.utils.password import update_password

EMAIL = "vt.screenshots@example.com"
ROLES = ("Velocity Merchandiser", "Sales User", "Velocity Cutting", "Stock User")


def create() -> dict:
	"""Create (or recreate) the screenshot user and return login details and sample records."""
	frappe.set_user("Administrator")
	delete()
	frappe.get_doc(
		{
			"doctype": "User",
			"email": EMAIL,
			"first_name": "Screenshot",
			"last_name": "Check",
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in ROLES],
		}
	).insert(ignore_permissions=True)
	password = f"Vt-{secrets.token_urlsafe(18)}-9a"
	update_password(EMAIL, password)
	frappe.db.commit()
	return {
		"email": EMAIL,
		"password": password,
		"garment_order": _latest("Garment Order", {"docstatus": 1}) or _latest("Garment Order", {}),
		"draft_garment_order": _latest("Garment Order", {"docstatus": 0}),
		"job_map": _latest("Job Map", {}),
		"fabric_issue": _latest("Fabric Issue", {"docstatus": 1, "issue_type": "Issue"}),
		"cutting_marker": _latest("Cutting Marker", {"docstatus": 1}),
		"cut_receive": _latest("Cut Receive", {"docstatus": 1, "bundle_count": (">", 0)}),
		"bundle": _latest("Bundle", {}),
	}


def delete() -> dict:
	"""Remove the screenshot user and its sessions. Safe to run when the user does not exist."""
	frappe.set_user("Administrator")
	existed = bool(frappe.db.exists("User", EMAIL))
	if existed:
		frappe.db.delete("Sessions", {"user": EMAIL})
		frappe.delete_doc("User", EMAIL, ignore_permissions=True, force=True)
	frappe.db.commit()
	return {"deleted": existed}


def _latest(doctype: str, filters: dict) -> str | None:
	names = frappe.get_all(doctype, filters=filters, pluck="name", order_by="creation desc", limit=1)
	return names[0] if names else None
