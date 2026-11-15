"""Backend for the Velocity Home and Order Tracker pages.

Every query is set based: lists are read once with frappe.get_list (so user permissions apply)
and joined in Python. There are no queries inside per-row loops.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from velocity_ctp.api.procurement import get_procurement_summary
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
	cut_today = None
	wip_pieces = None
	pending_sheets = None
	costing_roles = {"Velocity Costing", "Velocity Costing Approver", "System Manager"}
	if costing_roles & set(frappe.get_roles()) and frappe.has_permission("Cost Sheet", "read"):
		pending_sheets = frappe.db.count("Cost Sheet", {"status": "Pending Approval"})
	if frappe.has_permission("Bundle", "read"):
		from velocity_ctp.api.production import pieces_in_wip

		wip_pieces = pieces_in_wip()
	if frappe.has_permission("Cut Receive", "read"):
		cut_today = cint(
			frappe.get_list(
				"Cut Receive",
				filters={"docstatus": 1, "posting_date": today},
				fields=[_agg("total_cut_qty", "SUM", "qty")],
			)[0].qty
		)

	shipping = None
	open_returnables = None
	ready = None
	if frappe.has_permission("Delivery Note", "read"):
		from velocity_ctp.shipping.dashboard import ready_to_ship, shipped_this_month

		shipping = shipped_this_month(get_default_company(throw=False))
		ready = ready_to_ship()
	if frappe.has_permission("Gate Outward", "read"):
		from velocity_ctp.shipping.gate import open_returnables as returnables

		open_returnables = len(returnables())

	unbilled_work = None
	if frappe.has_permission("Contractor Bill Run", "read"):
		from velocity_ctp.procurement.contractor_billing import unbilled_total

		unbilled_work = unbilled_total(get_default_company(throw=False))

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
				"key": "cost_sheets_pending",
				"label": _("Cost Sheets Pending Approval"),
				"sub": _("Waiting for an approver"),
				"value": pending_sheets,
				"tone": "warn",
				"doctype": "Cost Sheet",
				"filters": {"status": "Pending Approval"},
				"hidden": pending_sheets is None,
			},
			{
				"key": "pieces_in_wip",
				"label": _("Pieces in WIP"),
				"sub": _("Cut, not yet packed"),
				"value": wip_pieces,
				"tone": "info",
				"route": "production-control",
				"hidden": wip_pieces is None,
			},
			{
				"key": "pieces_cut_today",
				"label": _("Pieces Cut Today"),
				"sub": _("From today's Cut Receives"),
				"value": cut_today,
				"tone": "ok",
				"doctype": "Cut Receive",
				"filters": {"docstatus": 1, "posting_date": str(today)},
				"hidden": cut_today is None,
			},
			{
				"key": "shipped_this_month",
				"label": _("Shipped This Month"),
				"sub": _("pcs · {0} value").format(
					frappe.format(shipping["value"], {"fieldtype": "Currency"}) if shipping else ""
				),
				"value": shipping["pcs"] if shipping else None,
				"tone": "ok",
				"doctype": "Delivery Note",
				"filters": {"docstatus": 1, "is_return": 0, "posting_date": [">=", shipping["from"]]}
				if shipping
				else {},
				"hidden": shipping is None,
			},
			{
				"key": "returnables_pending",
				"label": _("Returnable Items Pending"),
				"sub": _("Out on gate passes, not back yet"),
				"value": open_returnables,
				"tone": "warn",
				"route": "query-report/Gate Balance",
				"hidden": open_returnables is None,
			},
			{
				"key": "unbilled_contractor_work",
				"label": _("Unbilled Contractor Work"),
				"sub": _("PKR accrued, not invoiced yet"),
				"value": unbilled_work,
				"tone": "warn",
				"route": "query-report/Accrued Contractor Charges",
				"hidden": unbilled_work is None,
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
		"margin_watch": get_margin_watch(),
		"cutting": get_cutting_status() if frappe.has_permission("Cut Receive", "read") else None,
		"pipeline": get_approval_pipeline() if can_read_job_map else None,
		"procurement": get_procurement_summary(),
		"ready_to_ship": ready,
	}


def get_margin_watch(limit: int = 20) -> dict:
	"""Open orders whose estimated profit % (from the Cost Sheet) is below the target margin."""
	from velocity_ctp.cutting.settings import get_settings

	target = flt(get_settings().target_margin_percent)
	rows = frappe.get_list(
		"Garment Order",
		filters={
			"docstatus": 1,
			"status": ("in", ACTIVE_STATUSES),
			"cost_sheet": ("is", "set"),
			"estimated_profit_percent": ("<", target),
		},
		fields=[
			"name",
			"customer",
			"style",
			"cost_sheet",
			"estimated_profit_percent",
			"quoted_fob",
			"costed_fob",
			"currency",
			"ship_date",
		],
		order_by="estimated_profit_percent asc",
		limit_page_length=limit,
	)
	return {"target": target, "rows": rows}


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


def get_cutting_status() -> dict:
	"""Active (not closed) Job Maps with cutting activity or ready to cut: fabric and pieces."""
	from velocity_ctp.cutting.ledger import job_fabric
	from velocity_ctp.cutting.settings import get_settings

	maps = frappe.get_list(
		"Job Map",
		filters={"job_closed": 0},
		fields=["name", "status", "priority"],
		order_by="modified desc",
		limit_page_length=50,
	)
	names = [m.name for m in maps]
	fabric = job_fabric(names)
	planned = {
		r.job_map: cint(r.pcs)
		for r in frappe.get_all(
			"Cutting Marker",
			filters={"job_map": ("in", names or [""]), "docstatus": 1},
			fields=["job_map", _agg("total_planned_pieces", "SUM", "pcs")],
			group_by="job_map",
		)
	}
	cut = {
		r.job_map: r
		for r in frappe.get_all(
			"Cut Receive",
			filters={"job_map": ("in", names or [""]), "docstatus": 1},
			fields=[
				"job_map",
				_agg("total_cut_qty", "SUM", "pcs"),
				_agg("total_fabric_required", "SUM", "required"),
				_agg("total_fabric_used", "SUM", "used"),
			],
			group_by="job_map",
		)
	}
	alert = flt(get_settings().fabric_wastage_alert_percent)
	rows = []
	for m in maps:
		values = fabric.get(m.name, {})
		issued = sum(v["issued"] - v["returned"] for v in values.values())
		used = sum(v["used"] for v in values.values())
		receive = cut.get(m.name)
		if not (issued or m.name in planned or receive or m.status == "Ready to Cut"):
			continue
		required = flt(receive.required) if receive else 0
		wastage = flt((flt(receive.used) - required) / required * 100, 2) if receive and required else None
		rows.append(
			{
				"job_map": m.name,
				"status": m.status,
				"fabric_issued": flt(issued, 2),
				"fabric_used": flt(used, 2),
				"pieces_cut": cint(receive.pcs) if receive else 0,
				"pieces_planned": planned.get(m.name, 0),
				"wastage_percent": wastage,
				"wastage_alert": bool(wastage is not None and alert and wastage > alert),
			}
		)
	return {"rows": rows, "alert": alert}


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


class StageState(TypedDict, total=False):
	state: str  # "done" | "active" | "blocked" | "pending"
	detail: str
	hint: str  # extra text for the tooltip (for example pieces in repair)


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


def stage_material(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Material stage: Not planned / Planned (shortfall) / Covered / Issued, from the Material Plan."""
	from velocity_ctp.api.procurement import stage_material as material

	return material(orders, context)


def stage_cutting(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Cutting stage from submitted Cut Receives: cut pieces against the order's cutting quantity.

	Not started: nothing cut. In progress: "x/y · z%" (cut of cutting quantity). Done: cut >= cutting quantity.
	"""
	from velocity_ctp.cutting.ledger import order_cut_totals

	cut = order_cut_totals([o.name for o in orders])
	result: dict[str, StageState] = {}
	for o in orders:
		done, target = cint(cut.get(o.name)), cint(o.total_cutting_qty)
		percent = round(done / target * 100) if target else 0
		if not done:
			result[o.name] = {"state": "pending", "detail": _("Not started")}
		elif target and done >= target:
			result[o.name] = {"state": "done", "detail": _("{0} pcs · {1}%").format(done, percent)}
		else:
			result[o.name] = {
				"state": "active",
				"detail": _("{0}/{1} · {2}%").format(done, target, percent),
			}
	return result


def stage_stitching(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Stitching: pieces received (fresh + rejected) of pieces issued or still on their way; repair in the hint."""
	from velocity_ctp.api.production import stage_for_process

	return stage_for_process(orders, context, "Stitching")


def stage_washing(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Washing: pieces received (fresh + rejected) of pieces issued or still on their way; repair in the hint."""
	from velocity_ctp.api.production import stage_for_process

	return stage_for_process(orders, context, "Washing")


def stage_finishing(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Finishing: pieces received (fresh + rejected) of pieces issued or still on their way; repair in the hint."""
	from velocity_ctp.api.production import stage_for_process

	return stage_for_process(orders, context, "Finishing")


def stage_packing(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Packing: pieces on submitted Packing Lists of the order's good pieces."""
	from velocity_ctp.api.production import stage_packing_progress

	return stage_packing_progress(orders, context)


def stage_shipped(orders: list[frappe._dict], context: dict) -> dict[str, StageState]:
	"""Shipped stage: pieces on submitted Delivery Notes of the order quantity (invoiced in the tooltip)."""
	from velocity_ctp.shipping.dashboard import stage_shipped as shipped

	return shipped(orders, context)


# Order of this list is the order of the pipeline on the page.
TRACKER_STAGES: tuple[tuple[str, str, StageProvider], ...] = (
	("order", "Order", stage_order),
	("approvals", "Approvals", stage_approvals),
	("material", "Material", stage_material),
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
			"cost_sheet",
			"estimated_profit_percent",
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
		"target_margin": _target_margin(),
	}


def _target_margin() -> float:
	from velocity_ctp.cutting.settings import get_settings

	return flt(get_settings().target_margin_percent)
