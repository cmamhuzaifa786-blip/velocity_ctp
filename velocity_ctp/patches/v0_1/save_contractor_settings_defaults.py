def execute():
	"""Store the new Velocity Settings default (Contractor Rate Tolerance %)."""
	from velocity_ctp.cutting.settings import ensure_saved

	ensure_saved()
