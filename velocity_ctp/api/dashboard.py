"""Backend for the Velocity Home and Order Tracker pages.

Every query is set based: lists are read once with frappe.get_list (so user permissions apply)
and joined in Python. There are no queries inside per-row loops.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, getdate, nowdate

from velocity_ctp.setup.install import get_default_company

OPEN_STATUSES = ("Open", "In Production")
ACTIVE_STATUSES = ("Open", "In Production", "On Hold")
RISK_WINDOW_DAYS = 14
UPCOMING_WINDOW_DAYS = 30

# (check field, label) in approval order. Kept in sync with job_map.APPROVALS.
APPROVAL_STAGES: tuple[tuple[str, str], ...] = (
	("fit_sample_approved", "Fit"),
	("size_set_sample_approved", "Size Set"),
	("photo_sample_approved", "Photo"),
	("pp_sample_approved", "PP"),
	("ok_to_cut", "OK to Cut"),
)
APPROVAL_FIELDS = [field for field, _label in APPROVAL_STAGES]


def _check_read(doctype: str) -> None:
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("You do not have permission to read {0}.").format(_(doctype)), frappe.PermissionError)


def _agg(field: str, fn: str, alias: str) -> dict:
	return {fn: field, "as": alias}


# ----------------------------------------------------------------------
# Velocity Home
# ----------------------------------------------------------------------


@frappe.whitelist()
def get_home_data() -> dict:
	_check_read("Garment Order")
	can_read_job_map = bool(frappe.has_permission("Job Map", "read"))
	today = getdate(nowdate())
	in_14 = add_days(today, RISK_WINDOW_DAYS)
	in_30 = add_days(today, UPCOMING_WINDOW_DAYS)

	by_status = {
		row.status: row
		for row in frappe.get_list(
			"Garment Order",
			filters={"docstatus": 1},
			fields=["status", _agg("name", "COUNT", "count"), _agg("total_order_qty", "SUM", "qty")],
			group_by="status",
		)
	}
	open_count = sum(cint(by_status[s].count) for s in OPEN_STATUSES if s in by_status)
	open_qty = sum(cint(by_status[s].qty) for s in OPEN_STATUSES if s in by_status)
	on_hold = cint(by_status["On Hold"].count) if "On Hold" in by_status else 0

	shipping_soon = frappe.get_list(
		"Garment Order",
		filters={"docstatus": 1, "status": ("in", ACTIVE_STATUSES), "ship_date": ("between", (today, in_14))},
		fields=[_agg("name", "COUNT", "count")],
	)[0].count

	job_counts: dict[str, int] = {}
	if can_read_job_map:
		job_counts = {
			row.status: cint(row.count)
			for row in frappe.get_list(
				"Job Map", fields=["status", _agg("name", "COUNT", "count")], group_by="status"
			)
		}

	shipments = get_upcoming_shipments(today, in_30)

	return {
		"company": get_default_company(throw=False),
		"today": str(today),
		"kpis": [
			{
				"key": "open_orders",
				"label": _("Open Orders"),
				"sub": _("Submitted, not completed"),
				"value": open_count,
				"tone": "info",
				"doctype": "Garment Order",
				"filters": {"docstatus": 1, "status": ["in", list(OPEN_STATUSES)]},
			},
			{
				"key": "pieces",
				"label": _("Pieces on Order"),
				"value": open_qty,
				"sub": _("Across open orders"),
				"tone": "info",
				"doctype": "Garment Order",
				"filters": {"docstatus": 1, "status": ["in", list(OPEN_STATUSES)]},
			},
			{
				"key": "pending_approvals",
				"label": _("Jobs Pending Approvals"),
				"sub": _("Waiting for sample approvals"),
				"value": job_counts.get("Pending Approvals", 0),
				"tone": "warn",
				"doctype": "Job Map",
				"filters": {"status": "Pending Approvals"},
				"hidden": not can_read_job_map,
			},
			{
				"key": "ready_to_cut",
				"label": _("Ready to Cut"),
				"sub": _("OK to Cut given"),
				"value": job_counts.get("Ready to Cut", 0),
				"tone": "ok",
				"doctype": "Job Map",
				"filters": {"status": "Ready to Cut"},
				"hidden": not can_read_job_map,
			},
			{
				"key": "shipping_soon",
				"label": _("Shipping in Next 14 Days"),
				"sub": _("Due by {0}").format(frappe.format(in_14, "Date")),
				"value": cint(shipping_soon),
				"tone": "warn",
				"doctype": "Garment Order",
				"filters": {
					"docstatus": 1,
					"status": ["in", list(ACTIVE_STATUSES)],
					"ship_date": ["between", [str(today), str(in_14)]],
				},
			},
			{
				"key": "on_hold",
				"label": _("On Hold"),
				"sub": _("Paused orders"),
				"value": on_hold,
				"tone": "bad",
				"doctype": "Garment Order",
				"filters": {"docstatus": 1, "status": "On Hold"},
			},
		],
		"shipments": shipments,
		"customers": get_orders_by_customer(),
		"pipeline": get_approval_pipeline() if can_read_job_map else None,
	}


def get_orders_by_customer(limit: int = 20) -> list[dict]:
	"""Open orders (same definition as the Open Orders card) grouped by customer, most pieces first."""
	rows = frappe.get_list(
		"Garment Order",
		filters={"docstatus": 1, "status": ("in", OPEN_STATUSES)},
		fields=[
			"customer",
			_agg("name", "COUNT", "orders"),
			_agg("total_order_qty", "SUM", "pieces"),
			_agg("ship_date", "MIN", "next_ship_date"),
		],
		group_by="customer",
	)
	rows.sort(key=lambda r: (-cint(r.pieces), r.customer))
	rows = rows[:limit]
	names = dict(
		frappe.get_all(
			"Customer",
			filters={"name": ("in", [r.customer for r in rows])},
			fields=["name", "customer_name"],
			as_list=True,
		)
	)
	today = getdate(nowdate())
	for row in rows:
		row.customer_name = names.get(row.customer) or row.customer
		row.orders = cint(row.orders)
		row.pieces = cint(row.pieces)
		row.overdue = bool(row.next_ship_date and getdate(row.next_ship_date) < today)
		row.filters = {"docstatus": 1, "status": ["in", list(OPEN_STATUSES)], "customer": row.customer}
	return rows


def get_upcoming_shipments(today, until) -> list[dict]:
	"""Active orders shipping on or before `until`, including overdue ones."""
	orders = frappe.get_list(
		"Garment Order",
		filters={"docstatus": 1, "status": ("in", ACTIVE_STATUSES), "ship_date": ("<=", until)},
		fields=["name", "customer", "style", "style_name", "total_order_qty", "ship_date", "status"],
		order_by="ship_date asc",
		limit_page_length=100,
	)
	job_maps = get_job_map_info([o.name for o in orders])
	for order in orders:
		order.days_left = date_diff(order.ship_date, today)
		order.overdue = order.days_left < 0
		info = job_maps.get(order.name)
		order.job_map = info.job_map if info else None
	return orders


def get_approval_pipeline() -> dict:
	"""Active (not closed) Job Maps counted at the approval stage they are waiting for."""
	maps = frappe.get_list(
		"Job Map", filters={"job_closed": 0}, fields=["name", "status", *APPROVAL_FIELDS], limit_page_length=0
	)
	stages = [
		{"key": field, "label": _(label), "count": 0, "filters": _stage_filters(i)}
		for i, (field, label) in enumerate(APPROVAL_STAGES)
	]
	ready = 0
	for job_map in maps:
		if job_map.ok_to_cut:
			ready += 1
			continue
		for i, field in enumerate(APPROVAL_FIELDS):
			if not job_map.get(field):
				stages[i]["count"] += 1
				break
	return {"stages": stages, "active": len(maps), "ready": ready}


def _stage_filters(index: int) -> dict:
	"""List filters for Job Maps waiting at the given stage (all earlier stages approved)."""
	filters: dict = {"job_closed": 0}
	if index == len(APPROVAL_FIELDS) - 1:
		# OK to Cut waits only on PP approval; earlier samples are not enforced by the rules.
		filters.update({"pp_sample_approved": 1, "ok_to_cut": 0})
		return filters
	for field in APPROVAL_FIELDS[:index]:
		filters[field] = 1
	filters[APPROVAL_FIELDS[index]] = 0
	return filters


def get_job_map_info(order_names: list[str]) -> dict[str, frappe._dict]:
	"""{garment_order: job map row} for the latest Job Map of each order (one query)."""
	if not order_names:
		return {}
	jm = frappe.qb.DocType("Job Map")
	jmo = frappe.qb.DocType("Job Map Order")
	rows = (
		frappe.qb.from_(jmo)
		.inner_join(jm)
		.on(jm.name == jmo.parent)
		.select(
			jmo.garment_order,
			jm.name.as_("job_map"),
			jm.status,
			jm.job_closed,
			jm.on_hold,
			jm.cutting_start_date,
			*[jm[field] for field in APPROVAL_FIELDS],
		)
		.where((jmo.parenttype == "Job Map") & jmo.garment_order.isin(order_names))
		.orderby(jm.job_closed)  # open Job Maps first
		.orderby(jm.modified, order=frappe.qb.desc)
		.run(as_dict=True)
	)
	result: dict[str, frappe._dict] = {}
	for row in rows:
		result.setdefault(row.garment_order, row)
	return result


# ----------------------------------------------------------------------
# Order Tracker
# ----------------------------------------------------------------------


class StageState(TypedDict):
	state: str  # "done" | "active" | "blocked" | "pending"
	detail: str


StageProvider = Callable[[list[frappe._dict], dict], dict[str, StageState]]


def _not_started(orders: list[frappe._dict]) -> dict[str, StageState]:
	return {o.name: {"state": "pending", "detail": _("Not started")} for o in orders}


def stage_order(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Order stage: done once the Garment Order is submitted; on hold shows as blocked."""
	result: dict[str, StageState] = {}
	for o in orders:
		if o.docstatus == 0:
			result[o.name] = {"state": "active", "detail": _("Draft")}
		elif o.status == "On Hold":
			result[o.name] = {"state": "blocked", "detail": _("On hold")}
		else:
			result[o.name] = {"state": "done", "detail": _("Confirmed")}
	return result


def stage_approvals(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Approvals stage: from the order's Job Map (sample approvals and OK to Cut)."""
	job_maps: dict[str, frappe._dict] = context["job_maps"]
	result: dict[str, StageState] = {}
	for o in orders:
		jm = job_maps.get(o.name)
		if not jm:
			result[o.name] = {"state": "pending", "detail": _("No job map")}
			continue
		done = sum(1 for field in APPROVAL_FIELDS if jm.get(field))
		if jm.ok_to_cut:
			result[o.name] = {"state": "done", "detail": _("OK to cut")}
		elif jm.on_hold:
			result[o.name] = {"state": "blocked", "detail": _("Job on hold")}
		else:
			waiting = next(_(label) for field, label in APPROVAL_STAGES if not jm.get(field))
			result[o.name] = {
				"state": "active",
				"detail": _("{0}/{1} · {2}").format(done, len(APPROVAL_FIELDS), waiting),
			}
	return result


def stage_cutting(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Cutting stage. Plug in cut quantities (for example from cutting entries) in a later phase."""
	return _not_started(orders)


def stage_stitching(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Stitching stage. Plug in stitching output against cutting quantity in a later phase."""
	return _not_started(orders)


def stage_washing(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Washing stage. Plug in washing issue/receipt progress in a later phase."""
	return _not_started(orders)


def stage_finishing(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Finishing stage. Plug in finishing output in a later phase."""
	return _not_started(orders)


def stage_packing(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Packing stage. Plug in packed quantity in a later phase."""
	return _not_started(orders)


def stage_shipped(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Shipped stage. Plug in delivered quantity (Delivery Notes against the Sales Order) later."""
	return _not_started(orders)


# Order of this list is the order of the pipeline on the page.
TRACKER_STAGES: tuple[tuple[str, str, StageProvider], ...] = (
	("order", "Order", stage_order),
	("approvals", "Approvals", stage_approvals),
	("cutting", "Cutting", stage_cutting),
	("stitching", "Stitching", stage_stitching),
	("washing", "Washing", stage_washing),
	("finishing", "Finishing", stage_finishing),
	("packing", "Packing", stage_packing),
	("shipped", "Shipped", stage_shipped),
)


def get_risk(order: frappe._dict, job_map: frappe._dict | None, today) -> str:
	"""overdue: ship date passed; at_risk: ships within 14 days and not ready to cut; else on_track."""
	if order.status in ("Completed", "Cancelled") or not order.ship_date:
		return "on_track"
	days_left = date_diff(order.ship_date, today)
	if days_left < 0:
		return "overdue"
	if days_left <= RISK_WINDOW_DAYS and not (job_map and job_map.ok_to_cut):
		return "at_risk"
	return "on_track"


@frappe.whitelist()
def get_order_tracker(
	customer: str | None = None,
	style: str | None = None,
	status: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	search: str | None = None,
	limit: int = 300,
) -> dict:
	_check_read("Garment Order")
	today = getdate(nowdate())

	filters: list = [["docstatus", "<", 2]]
	if customer:
		filters.append(["customer", "=", customer])
	if style:
		filters.append(["style", "=", style])
	if status:
		filters.append(["status", "=", status])
	else:
		filters.append(["status", "not in", ("Completed", "Cancelled")])
	if from_date:
		filters.append(["ship_date", ">=", from_date])
	if to_date:
		filters.append(["ship_date", "<=", to_date])
	if search:
		filters.append(["name", "like", f"%{search.strip()}%"])

	limit = min(max(cint(limit), 1), 1000)
	orders = frappe.get_list(
		"Garment Order",
		filters=filters,
		fields=[
			"name",
			"docstatus",
			"status",
			"customer",
			"style",
			"style_name",
			"order_type",
			"ship_date",
			"total_order_qty",
			"total_cutting_qty",
		],
		order_by="ship_date asc, name asc",
		limit_page_length=limit + 1,
	)
	truncated = len(orders) > limit
	orders = orders[:limit]

	context = {"job_maps": get_job_map_info([o.name for o in orders]), "today": today}
	stage_results = {key: provider(orders, context) for key, _label, provider in TRACKER_STAGES}

	risk_counts = {"on_track": 0, "at_risk": 0, "overdue": 0}
	rows = []
	for o in orders:
		jm = context["job_maps"].get(o.name)
		risk = get_risk(o, jm, today)
		risk_counts[risk] += 1
		rows.append(
			{
				**o,
				"days_left": date_diff(o.ship_date, today) if o.ship_date else None,
				"job_map": jm.job_map if jm else None,
				"risk": risk,
				"stages": [stage_results[key][o.name] for key, _label, _p in TRACKER_STAGES],
			}
		)

	return {
		"stages": [{"key": key, "label": _(label)} for key, label, _p in TRACKER_STAGES],
		"rows": rows,
		"risk_counts": risk_counts,
		"truncated": truncated,
		"limit": limit,
	}
