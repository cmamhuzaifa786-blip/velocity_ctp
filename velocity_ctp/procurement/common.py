"""Shared procurement constants and item-group helpers."""

from __future__ import annotations

import frappe
from frappe import _

REQUISITION_APPROVER = "Velocity Requisition Approver"
PO_APPROVER_L1 = "Velocity PO Approver L1"
PO_APPROVER_L2 = "Velocity PO Approver L2"

FABRIC_GROUP = "Fabric"
ACCESSORY_GROUP = "Accessories & Trims"
NON_PRODUCT_GROUP = "Non-Product"
SERVICE_GROUP = "Services"

# request_category / po_category -> item group (the group and its sub-groups)
CATEGORY_GROUPS = {
	"Fabric": FABRIC_GROUP,
	"Accessory": ACCESSORY_GROUP,
	"Non-Product": NON_PRODUCT_GROUP,
	"Service": SERVICE_GROUP,
}

# Workflow state names (also used by the dashboards and reports)
MR_PENDING = "Pending Approval"
MR_REJECTED = "Rejected"
PO_DRAFT = "Draft"
PO_PENDING_1 = "Pending 1st Approval"
PO_PENDING_2 = "Pending 2nd Approval"
APPROVED = "Approved"


def group_bounds(group: str) -> tuple[int, int] | None:
	bounds = frappe.db.get_value("Item Group", group, ["lft", "rgt"])
	return (bounds[0], bounds[1]) if bounds else None


def items_in_group(items: list[str], group: str) -> dict[str, bool]:
	"""{item_code: True if the item's group is `group` or one of its sub-groups} (one query)."""
	items = [i for i in set(items) if i]
	if not items:
		return {}
	bounds = group_bounds(group)
	rows = frappe.db.sql(
		"""select i.name, ig.lft from `tabItem` i left join `tabItem Group` ig on ig.name = i.item_group
		where i.name in %(items)s""",
		{"items": items},
	)
	return {name: bool(bounds and lft is not None and bounds[0] <= lft <= bounds[1]) for name, lft in rows}


def is_in_group(item_code: str, group: str) -> bool:
	return items_in_group([item_code], group).get(item_code, False)


def validate_items_in_group(rows, group: str, label: str, item_field: str = "item") -> None:
	"""Throw for the first row whose item is not in `group` (or a sub-group)."""
	membership = items_in_group([r.get(item_field) for r in rows], group)
	for row in rows:
		item = row.get(item_field)
		if item and not membership.get(item):
			frappe.throw(
				_("Row {0}: {1} is not in the {2} item group, so it cannot be used on a {3}.").format(
					row.idx, frappe.bold(item), frappe.bold(_(group)), _(label)
				),
				title=_("Wrong Item Group"),
			)
