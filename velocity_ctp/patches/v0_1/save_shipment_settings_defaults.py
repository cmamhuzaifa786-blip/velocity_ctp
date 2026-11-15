def execute():
	"""Store the new Velocity Settings defaults (Shipment Tolerance %, Require Gate Outward for Delivery)."""
	from velocity_ctp.cutting.settings import ensure_saved

	ensure_saved()
