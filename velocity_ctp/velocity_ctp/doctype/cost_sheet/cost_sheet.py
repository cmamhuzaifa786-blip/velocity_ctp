# Copyright (c) 2026, Muhammad Huzaifa and contributors
# For license information, please see license.txt

"""Cost Sheet with approval and revisions.

Flow: Draft -> Submit for Approval (Pending Approval) -> Approve (Approved, document submitted)
or Reject (Rejected, editable again). Approving is the only way a Cost Sheet is submitted.
Revise creates a draft "<base>-R<n>" copy; when it is approved the previous approved revision
of the same base becomes Superseded, so only one revision per base is Approved at a time.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, flt, now_datetime

from velocity_ctp.costing import calc
from velocity_ctp.cutting.stock import is_fabric_group
from velocity_ctp.setup.install import get_default_company

APPROVER_ROLE = "Velocity Costing Approver"
ACCESSORY_GROUP = "Accessories & Trims"
EDITABLE_STATUSES = ("Draft", "Rejected")


class CostSheet(Document):
	def onload(self) -> None:
		from velocity_ctp.cutting.settings import get_settings

		self.set_onload("target_margin", flt(get_settings().target_margin_percent))
		self.set_onload("is_approver", APPROVER_ROLE in frappe.get_roles())
		if self.status == "Superseded":
			self.set_onload("current_revision", current_revision(self.name))

	def autoname(self) -> None:
		if self.base_cost_sheet and cint(self.revision_no):
			self.name = f"{self.base_cost_sheet}-R{cint(self.revision_no)}"
		else:
			self.name = make_autoname("CS-.YY.-.#####", doc=self)

	def validate(self) -> None:
		if not self.company:
			self.company = get_default_company()
		if not self.merchandiser:
			self.merchandiser = frappe.session.user
		if self.docstatus == 0 and not self.flags.approval_action:
			if self.status == "Pending Approval" and not self.is_new():
				frappe.throw(
					_(
						"Cost Sheet {0} is waiting for approval and cannot be changed. Ask an approver to reject it first."
					).format(frappe.bold(self.name)),
					title=_("Waiting for Approval"),
				)
			self.status = "Draft"
		self.validate_header()
		self.validate_items()
		if not self.costs:
			self.set_costs_from_heads()
		calc.calculate(self)

	def validate_header(self) -> None:
		style_customer = frappe.db.get_value("Style", self.style, "customer")
		if style_customer and style_customer != self.customer:
			frappe.throw(
				_("Style {0} belongs to customer {1}, not {2}.").format(
					frappe.bold(self.style), frappe.bold(style_customer), frappe.bold(self.customer)
				)
			)
		if flt(self.exchange_rate) <= 0:
			frappe.throw(_("Exchange Rate must be greater than zero."))
		if cint(self.quantity_pcs) <= 0:
			frappe.throw(_("Quantity (Pcs) must be greater than zero."))
		if cint(self.revision_no) and not (self.revision_reason or "").strip():
			frappe.throw(_("Please enter the reason for this revision."), title=_("Revision Reason Required"))
		if (
			self.price_basis == "CNF"
			and flt(self.quoted_cnf_fc) <= 0
			and self.docstatus == 0
			and self.flags.approval_action
		):
			frappe.throw(_("Please enter the Quoted CNF price."))

	def validate_items(self) -> None:
		for row in self.fabrics or []:
			if row.fabric_item and not is_fabric_group(
				frappe.db.get_value("Item", row.fabric_item, "item_group")
			):
				frappe.throw(
					_("Fabric row {0}: {1} is not in the Fabric item group.").format(row.idx, row.fabric_item)
				)
		accessory_bounds = frappe.db.get_value("Item Group", ACCESSORY_GROUP, ["lft", "rgt"])
		for row in self.accessories or []:
			if not row.accessory_item:
				continue
			group = frappe.db.get_value("Item", row.accessory_item, "item_group")
			lft = frappe.db.get_value("Item Group", group, "lft")
			if not (accessory_bounds and lft and accessory_bounds[0] <= lft <= accessory_bounds[1]):
				frappe.throw(
					_("Accessory row {0}: {1} is not in the {2} item group.").format(
						row.idx, row.accessory_item, ACCESSORY_GROUP
					)
				)

	def set_costs_from_heads(self) -> None:
		for head in active_heads():
			self.append(
				"costs",
				{
					"cost_head": head.name,
					"section": head.section,
					"calculation": head.calculation,
					"rate_or_percent": flt(head.default_value) if head.calculation != calc.COMPUTED else 0,
				},
			)

	@frappe.whitelist()
	def recalculate(self) -> None:
		"""Live calculation for the form (the document is not saved)."""
		if not self.costs:
			self.set_costs_from_heads()
		calc.calculate(self)

	def before_submit(self) -> None:
		if not self.flags.approval_action:
			frappe.throw(
				_(
					"Cost Sheets are submitted by approval. Use Submit for Approval, and an approver approves it."
				),
				title=_("Approval Required"),
			)

	def base_name(self) -> str:
		return self.base_cost_sheet or self.name

	def supersede_previous(self) -> None:
		base = self.base_name()
		previous = frappe.get_all(
			"Cost Sheet",
			filters={"status": "Approved", "name": ("!=", self.name)},
			or_filters={"name": base, "base_cost_sheet": base},
			pluck="name",
		)
		for name in previous:
			frappe.db.set_value("Cost Sheet", name, "status", "Superseded")
			# Orders keep their link; their fetched status shows the notice to switch revisions.
			for order in frappe.get_all("Garment Order", filters={"cost_sheet": name}, pluck="name"):
				frappe.db.set_value(
					"Garment Order", order, "cost_sheet_status", "Superseded", update_modified=False
				)
			frappe.get_doc("Cost Sheet", name).add_comment(
				"Info", _("Superseded by revision {0}.").format(self.name)
			)


def active_heads() -> list[frappe._dict]:
	return frappe.get_all(
		"Cost Head",
		filters={"is_active": 1},
		fields=["name", "section", "calculation", "default_value"],
		order_by="sequence asc, name asc",
	)


def _load(name: str, ptype: str = "write"):
	doc = frappe.get_doc("Cost Sheet", name)
	doc.check_permission(ptype)
	return doc


def _check_approver() -> None:
	if APPROVER_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only a {0} can approve or reject Cost Sheets.").format(APPROVER_ROLE), frappe.PermissionError
		)


@frappe.whitelist(methods=["POST"])
def submit_for_approval(cost_sheet: str) -> str:
	doc = _load(cost_sheet)
	if doc.docstatus != 0 or doc.status not in EDITABLE_STATUSES:
		frappe.throw(_("Only a Draft or Rejected Cost Sheet can be submitted for approval."))
	if flt(doc.quoted_fob_fc) <= 0:
		frappe.throw(_("Please enter the Quoted FOB price before submitting for approval."))
	if not doc.fabrics:
		frappe.throw(_("Please enter at least one fabric line before submitting for approval."))
	doc.status = "Pending Approval"
	doc.flags.approval_action = True
	doc.save()
	doc.add_comment("Info", _("Submitted for approval."))
	return doc.status


@frappe.whitelist(methods=["POST"])
def approve(cost_sheet: str) -> str:
	_check_approver()
	doc = _load(cost_sheet, "submit")
	if doc.status != "Pending Approval":
		frappe.throw(_("Only a Cost Sheet that is Pending Approval can be approved."))
	if doc.owner == frappe.session.user:
		frappe.throw(
			_(
				"You created Cost Sheet {0}, so you cannot approve it. Another approver must approve it."
			).format(frappe.bold(doc.name)),
			title=_("Self-Approval Not Allowed"),
		)
	doc.status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.rejection_reason = None
	doc.flags.approval_action = True
	doc.submit()
	doc.supersede_previous()
	return doc.status


@frappe.whitelist(methods=["POST"])
def reject(cost_sheet: str, reason: str) -> str:
	_check_approver()
	doc = _load(cost_sheet)
	if doc.status != "Pending Approval":
		frappe.throw(_("Only a Cost Sheet that is Pending Approval can be rejected."))
	if not (reason or "").strip():
		frappe.throw(_("Please enter the reason for rejecting this Cost Sheet."))
	doc.status = "Rejected"
	doc.rejection_reason = reason.strip()
	doc.flags.approval_action = True
	doc.save()
	doc.add_comment("Info", _("Rejected: {0}").format(reason.strip()))
	return doc.status


@frappe.whitelist(methods=["POST"])
def revise(cost_sheet: str, reason: str) -> str:
	"""Create a draft revision of an approved Cost Sheet."""
	source = frappe.get_doc("Cost Sheet", cost_sheet)
	if not frappe.has_permission("Cost Sheet", "create"):
		frappe.throw(_("You do not have permission to create Cost Sheets."), frappe.PermissionError)
	if source.status != "Approved":
		frappe.throw(_("Only an Approved Cost Sheet can be revised."))
	if not (reason or "").strip():
		frappe.throw(_("Please enter the reason for this revision."), title=_("Revision Reason Required"))
	base = source.base_name()
	open_revision = frappe.db.get_value("Cost Sheet", {"base_cost_sheet": base, "docstatus": 0}, "name")
	if open_revision:
		frappe.throw(
			_("Revision {0} is already open for this Cost Sheet.").format(frappe.bold(open_revision))
		)
	revisions = frappe.get_all("Cost Sheet", filters={"base_cost_sheet": base}, pluck="revision_no")
	new = frappe.copy_doc(source)
	new.update(
		{
			"base_cost_sheet": base,
			"revision_no": max([cint(r) for r in revisions] + [cint(source.revision_no)]) + 1,
			"revision_reason": reason.strip(),
			"status": "Draft",
			"merchandiser": frappe.session.user,
		}
	)
	new.insert()
	return new.name


@frappe.whitelist(methods=["POST"])
def copy_to_style(cost_sheet: str, style: str) -> str:
	"""Copy all tables of a Cost Sheet into a new draft for another style."""
	source = _load(cost_sheet, "read")
	if not frappe.has_permission("Cost Sheet", "create"):
		frappe.throw(_("You do not have permission to create Cost Sheets."), frappe.PermissionError)
	new = frappe.copy_doc(source)
	new.update(
		{
			"style": style,
			"customer": frappe.db.get_value("Style", style, "customer"),
			"style_name": frappe.db.get_value("Style", style, "style_name"),
			"base_cost_sheet": None,
			"revision_no": 0,
			"revision_reason": None,
			"status": "Draft",
			"merchandiser": frappe.session.user,
		}
	)
	new.insert()
	return new.name


@frappe.whitelist()
def current_revision(cost_sheet: str) -> str | None:
	"""The Approved revision that shares the base of `cost_sheet` (for superseded links)."""
	frappe.has_permission("Cost Sheet", "read", throw=True)
	base = frappe.db.get_value("Cost Sheet", cost_sheet, "base_cost_sheet") or cost_sheet
	names = frappe.get_all(
		"Cost Sheet",
		filters={"status": "Approved"},
		or_filters={"name": base, "base_cost_sheet": base},
		pluck="name",
		limit=1,
	)
	return names[0] if names else None


@frappe.whitelist()
def get_cost_heads() -> list[dict]:
	frappe.has_permission("Cost Sheet", "read", throw=True)
	return active_heads()
