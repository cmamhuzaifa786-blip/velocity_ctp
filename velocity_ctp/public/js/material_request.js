// Velocity CTP additions to the standard Material Request form (loaded through doctype_js).
// - asks for a reason when the requisition approver rejects the request

frappe.ui.form.on("Material Request", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.workflow_state === "Rejected" && frm.doc.rejection_reason) {
			frm.set_intro(
				__("Rejected: {0}. Use Revise to change it and send it again.", [frappe.utils.escape_html(frm.doc.rejection_reason)]),
				"red"
			);
		} else if (frm.doc.docstatus === 0 && frm.doc.workflow_state === "Pending Approval") {
			frm.set_intro(__("Waiting for approval by a Velocity Requisition Approver."), "yellow");
		}
	},

	before_workflow_action(frm) {
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
						.call("velocity_ctp.procurement.buying.set_rejection_reason", {
							doctype: frm.doctype,
							name: frm.doc.name,
							reason: values.reason,
						})
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
	},
});
