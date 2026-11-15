import frappe


def execute():
	"""Order colour / cut colour: data made before the Cut Colours map keeps working as before.

	Bundles get order_colour = their current colour, Cut Receive pieces and Cutting Markers get
	cut_colour = their colour (orders without a map are cut in the order colour).
	"""
	frappe.db.sql("update `tabBundle` set order_colour = colour where ifnull(order_colour, '') = ''")
	frappe.db.sql("update `tabCut Receive Piece` set cut_colour = colour where ifnull(cut_colour, '') = ''")
	frappe.db.sql("update `tabCutting Marker` set cut_colour = colour where ifnull(cut_colour, '') = ''")
