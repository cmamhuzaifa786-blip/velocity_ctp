def execute():
	"""Store the new procurement defaults (PO Second Approval Limit) that the PO workflow condition reads."""
	from velocity_ctp.cutting.settings import ensure_saved

	ensure_saved()
