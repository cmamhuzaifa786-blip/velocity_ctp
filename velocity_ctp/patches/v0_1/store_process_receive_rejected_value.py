import frappe
from frappe.utils import cint, flt


def execute():
	"""Store the value of rejected pieces on submitted Process Receives made before the field existed."""
	rows = frappe.db.sql(
		"""select prb.name, prb.item_code, prb.rejected_qty, pr.stock_entry from `tabProcess Receive Bundle` prb
		join `tabProcess Receive` pr on pr.name = prb.parent
		where pr.docstatus = 1 and prb.rejected_qty > 0 and ifnull(prb.rejected_value, 0) = 0""",
		as_dict=True,
	)
	for row in rows:
		rate = frappe.db.sql(
			"""select sed.valuation_rate from `tabStock Entry Detail` sed join `tabWarehouse` w on w.name = sed.t_warehouse
			where sed.parent = %s and sed.item_code = %s and w.warehouse_name = 'Rejection Store' limit 1""",
			(row.stock_entry, row.item_code),
		)
		if rate:
			frappe.db.set_value(
				"Process Receive Bundle",
				row.name,
				"rejected_value",
				flt(cint(row.rejected_qty) * flt(rate[0][0]), 2),
				update_modified=False,
			)
