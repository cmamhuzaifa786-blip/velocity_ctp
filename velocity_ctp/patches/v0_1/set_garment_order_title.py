import frappe


def execute():
	"""Fill the new Garment Order title ("<order no> · <customer name>") on existing orders."""
	orders = frappe.get_all(
		"Garment Order", filters={"title": ("in", ("", None))}, fields=["name", "customer"]
	)
	names = dict(
		frappe.get_all(
			"Customer",
			filters={"name": ("in", list({o.customer for o in orders if o.customer}))},
			fields=["name", "customer_name"],
			as_list=True,
		)
	)
	for order in orders:
		customer = names.get(order.customer) or order.customer or ""
		title = f"{order.name} · {customer}" if customer else order.name
		frappe.db.set_value("Garment Order", order.name, "title", title, update_modified=False)
