// Velocity CTP additions to the standard Purchase Order form (loaded through doctype_js).
// - PO Category from the Material Requests the items come from
// - asks for a reason when an approver rejects the PO
// - hides "Update Items" for users without "Velocity PO Approver L1" (the server also blocks it)

const VT_BUYING = "velocity_ctp.procurement.buying.";
const VT_PO_L1 = "Velocity PO Approver L1";

frappe.ui.form.on("Purchase Order", {
	onload(frm) {
		if (frm.is_new()) vt_po_category_from_requests(frm);
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1 && !frappe.user.has_role(VT_PO_L1)) {
			// ERPNext adds the button in its own refresh; remove it after that has run.
			setTimeout(() => frm.remove_custom_button(__("Update Items")), 0);
		}
		if (frm.doc.docstatus === 0 && frm.doc.workflow_state && frm.doc.workflow_state !== "Draft") {
			frm.set_intro(__("This Purchase Order is waiting for approval ({0}).", [__(frm.doc.workflow_state)]), "yellow");
		} else if (frm.doc.docstatus === 0 && frm.doc.rejection_reason) {
			frm.set_intro(__("Rejected: {0}", [frappe.utils.escape_html(frm.doc.rejection_reason)]), "red");
		}
	},

	before_workflow_action(frm) {
		return vt_ask_rejection_reason(frm);
	},

	po_type(frm) {
		if (frm.doc.po_type === "Shortfall") {
			frappe.show_alert({ message: __("A Shortfall PO needs a reason and a Garment Order on every row."), indicator: "orange" });
		}
	},
});

frappe.ui.form.on("Purchase Order Item", {
	material_request(frm) {
		vt_po_category_from_requests(frm);
	},
});

function vt_po_category_from_requests(frm) {
	if (frm.doc.po_category) return;
	const requests = [...new Set((frm.doc.items || []).map((r) => r.material_request).filter(Boolean))];
	if (!requests.length) return;
	frappe.call(VT_BUYING + "get_request_category", { material_requests: requests }).then((r) => {
		if (r.message && !frm.doc.po_category) frm.set_value("po_category", r.message);
	});
}

function vt_ask_rejection_reason(frm) {
	if (frm.selected_workflow_action !== "Reject") return Promise.resolve();
	frappe.dom.unfreeze();
	return new Promise((resolve, reject) => {
		let done = false;
		const dialog = new frappe.ui.Dialog({
			title: __("Reject {0}", [frm.doc.name]),
			fields: [{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			primary_action_label: __("Reject"),
			primary_action(values) {
				frappe
					.call(VT_BUYING + "set_rejection_reason", { doctype: frm.doctype, name: frm.doc.name, reason: values.reason })
					.then(() => {
						done = true;
						dialog.hide();
						frappe.dom.freeze();
						resolve();
					});
			},
		});
		dialog.onhide = () => {
			if (!done) reject();
		};
		dialog.show();
	});
}
