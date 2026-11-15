import frappe


def execute():
	"""Create the "Velocity Absorption" Stock Entry Type and label the absorption entries made before it
	existed (Process Receive absorption entries; value only, no physical movement)."""
	from velocity_ctp.setup.install import ensure_stock_entry_types

	ensure_stock_entry_types([])
	entries = frappe.get_all(
		"Process Receive", filters={"absorption_entry": ("is", "set")}, pluck="absorption_entry"
	)
	if entries:
		frappe.db.sql(
			"update `tabStock Entry` set stock_entry_type = 'Velocity Absorption' where name in %s and purpose = 'Repack'",
			(entries,),
		)
