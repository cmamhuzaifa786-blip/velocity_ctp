def execute():
	"""Store Velocity Settings defaults so that every reader sees them (Singles store nothing until saved)."""
	from velocity_ctp.cutting.settings import ensure_saved

	ensure_saved()
