"""setup_masters() must never change values on records that already exist.

Changes a set of existing values, runs setup_masters() again, checks every value is unchanged,
then rolls everything back (nothing is left changed on the site).

Run:  bench --site velocity.local execute velocity_ctp.tests.test_setup_masters.run
Or, on a site with tests enabled:  bench --site <site> run-tests --module velocity_ctp.tests.test_setup_masters
"""

from __future__ import annotations

import contextlib
import io

import frappe

from velocity_ctp.setup.install import get_default_company, setup_masters

SAVEPOINT = "velocity_setup_test"


def _changes(company: str) -> list[dict]:
	"""Existing values to change: (doctype, name, field, new value)."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	stock_account = frappe.get_cached_value("Company", company, "default_inventory_account")
	cutting_wip = frappe.db.get_value(
		"Warehouse", {"warehouse_name": "Cutting WIP", "company": company}, "name"
	)
	changes = [
		("Process", "Washing", "allow_colour_change", 0),
		("Process", "Stitching", "process_type", "Both"),
		("Process", "Cutting", "next_process", None),
		("Process", "Finishing", "default_piece_rate", 7.5),
		("Warehouse", cutting_wip, "account", stock_account),
		("Stock Settings", "Stock Settings", "enable_serial_and_batch_no_for_item", 0),
		("Velocity Settings", "Velocity Settings", "default_bundle_size", 25),
		("Velocity Settings", "Velocity Settings", "fabric_wastage_alert_percent", 7),
		("Wash Type", "Stone Wash", "washing_category", "Non-Denim"),
		("UOM", "Pcs", "must_be_whole_number", 0),
	]
	missing = [
		c
		for c in changes
		if not c[1]
		or (c[0] not in ("Stock Settings", "Velocity Settings") and not frappe.db.exists(c[0], c[1]))
	]
	if missing:
		raise AssertionError(f"Run setup_masters once before this test; missing records: {missing} ({abbr})")
	return [{"doctype": d, "name": n, "field": f, "value": v} for d, n, f, v in changes]


def _set(change: dict) -> None:
	if change["doctype"] in ("Stock Settings", "Velocity Settings"):
		frappe.db.set_single_value(change["doctype"], change["field"], change["value"])
	else:
		frappe.db.set_value(
			change["doctype"], change["name"], change["field"], change["value"], update_modified=False
		)


def _get(change: dict):
	if change["doctype"] in ("Stock Settings", "Velocity Settings"):
		return frappe.db.get_single_value(change["doctype"], change["field"])
	return frappe.db.get_value(change["doctype"], change["name"], change["field"])


def _same(a, b) -> bool:
	if isinstance(a, int | float) or isinstance(b, int | float):
		return float(a or 0) == float(b or 0)
	return (a or None) == (b or None)


def check() -> list[tuple[str, bool, str]]:
	"""Run the check inside a savepoint and roll it back. Returns [(label, passed, detail)]."""
	frappe.set_user("Administrator")
	company = get_default_company()
	results: list[tuple[str, bool, str]] = []
	frappe.db.savepoint(SAVEPOINT)
	try:
		changes = _changes(company)
		for change in changes:
			_set(change)
		frappe.clear_cache()

		output = io.StringIO()
		with contextlib.redirect_stdout(output):
			created = setup_masters(commit=False)

		for change in changes:
			value = _get(change)
			label = f"{change['doctype']} {change['name']}: {change['field']} kept"
			results.append(
				(label, _same(value, change["value"]), f"expected {change['value']!r}, found {value!r}")
			)
		results.append(("Nothing was created on a set-up site", not created, f"created: {created}"))
		results.append(
			(
				"Batch tracking off is reported as a warning, not changed",
				"Batch tracking is off" in output.getvalue(),
				output.getvalue().strip().splitlines()[-1] if output.getvalue().strip() else "",
			)
		)
	finally:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_cache()
	return results


def run() -> dict:
	"""bench execute entry point: prints each check and raises if any failed."""
	results = check()
	for label, passed, detail in results:
		print(f"{'PASS' if passed else 'FAIL'} {label}" + ("" if passed else f" ({detail})"))
	failed = [label for label, passed, _detail in results if not passed]
	print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
	if failed:
		raise AssertionError(f"setup_masters changed existing values: {failed}")
	return {"passed": len(results), "failed": 0}


try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # older Frappe
	IntegrationTestCase = None

if IntegrationTestCase:

	class TestSetupMasters(IntegrationTestCase):
		def test_existing_values_are_never_changed(self):
			for label, passed, detail in check():
				self.assertTrue(passed, f"{label}: {detail}")
