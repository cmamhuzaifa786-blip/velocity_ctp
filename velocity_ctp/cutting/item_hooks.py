"""Item doc_events (hooks.py). Validation only: no permission changes on the core Item DocType."""

import frappe
from frappe import _

from velocity_ctp.cutting.stock import FABRIC_GROUP, is_fabric_group


def validate_fabric_batch(doc, method=None) -> None:
	"""Fabric is tracked by lot/shade, so fabric items must use batches."""
	if is_fabric_group(doc.item_group) and not doc.has_batch_no:
		frappe.throw(
			_(
				"Items in the {0} item group must use batches (one batch per lot / shade). "
				"Please tick Has Batch No for {1}."
			).format(frappe.bold(FABRIC_GROUP), frappe.bold(doc.item_code or doc.item_name)),
			title=_("Batch Tracking Required"),
		)
