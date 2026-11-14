"""Recommended standard ERPNext buying and stock settings for Velocity procurement.

This is NOT part of setup_masters() and never runs on install or migrate: it changes existing
settings, so it is run once per site, on purpose:

    bench --site <site> execute velocity_ctp.setup.procurement_settings.apply

Add `--kwargs "{'dry_run': True}"` to only print what would change. It prints every value it
changes (old -> new) and leaves settings that already have the recommended value alone.

Settings:
- Buying Settings
  - Purchase Order Required for Purchase Receipt = Yes
  - Purchase Receipt Required for Purchase Invoice = Yes
  - Maintain Same Rate Throughout the Purchase Cycle = on, action Stop,
    role allowed to override the stop: Velocity PO Approver L2
- Stock Settings
  - Over Delivery/Receipt Allowance = 2 %, role allowed to over-receive: Stock Manager
- Accounts Settings
  - Over Billing Allowance = 2 % (same as the receipt allowance: without it, a receipt that is within the
    2 % tolerance cannot be invoiced in full, because the bill would exceed the PO amount)
"""

from __future__ import annotations

import frappe

from velocity_ctp.setup.install import PO_APPROVER_L2_ROLE

RECOMMENDED: tuple[tuple[str, str, object, str], ...] = (
	# (settings doctype, field, value, description)
	("Buying Settings", "po_required", "Yes", "Purchase Order Required for Purchase Receipt"),
	("Buying Settings", "pr_required", "Yes", "Purchase Receipt Required for Purchase Invoice"),
	("Buying Settings", "maintain_same_rate", 1, "Maintain Same Rate Throughout the Purchase Cycle"),
	("Buying Settings", "maintain_same_rate_action", "Stop", "Action if the same rate is not maintained"),
	(
		"Buying Settings",
		"role_to_override_stop_action",
		PO_APPROVER_L2_ROLE,
		"Role allowed to override the stop",
	),
	("Stock Settings", "over_delivery_receipt_allowance", 2.0, "Over Delivery/Receipt Allowance (%)"),
	(
		"Stock Settings",
		"role_allowed_to_over_deliver_receive",
		"Stock Manager",
		"Role allowed to over-deliver/receive",
	),
	("Accounts Settings", "over_billing_allowance", 2.0, "Over Billing Allowance (%)"),
)


def _same(current, value) -> bool:
	if isinstance(value, int | float):
		return frappe.utils.flt(current) == frappe.utils.flt(value)
	return (current or "") == value


def apply(dry_run: bool = False) -> list[str]:
	"""Apply the recommended settings; returns (and prints) the changes."""
	if not frappe.db.exists("Role", PO_APPROVER_L2_ROLE):
		frappe.throw(f"Role {PO_APPROVER_L2_ROLE} does not exist. Run bench migrate for this site first.")

	changes: list[str] = []
	docs: dict[str, object] = {}
	for doctype, field, value, label in RECOMMENDED:
		doc = docs.setdefault(doctype, frappe.get_single(doctype))
		current = doc.get(field)
		if _same(current, value):
			print(f"  unchanged  {doctype}: {label} = {current!r}")
			continue
		changes.append(f"{doctype}: {label}: {current!r} -> {value!r}")
		doc.set(field, value)

	for line in changes:
		print(f"  {'would change' if dry_run else 'changed'}    {line}")
	if changes and not dry_run:
		for doctype in {c.split(":")[0] for c in changes}:
			doc = docs[doctype]
			doc.flags.ignore_permissions = True
			doc.save()
		frappe.db.commit()
	print(f"Procurement settings: {len(changes)} {'change(s) to make' if dry_run else 'change(s) made'}.")
	return changes
