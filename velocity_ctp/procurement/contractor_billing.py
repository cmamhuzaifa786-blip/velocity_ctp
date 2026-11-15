"""Contractor work and its billing state (one source of truth for the Bill Run, reports and the KPI).

Work = submitted Cut Receives with a cutting party and submitted Process Receives of outsourced
processes, per document and garment order: fresh pieces and the contractor charge accrued at submit
(stored as contractor_cost_amount on the piece / bundle rows, credited to Contractor Charges Accrued).

A source document is billed when a Purchase Invoice row links to it (velocity_source_doctype / name):
- "billed" for the GL = the invoice is submitted (it debits Contractor Charges Accrued);
- "taken" for double billing = the invoice is not cancelled (a draft also blocks a second bill).
Cancelling the invoice releases the work for billing again.
"""

from __future__ import annotations

from collections import defaultdict

import frappe
from frappe.utils import cint, flt, getdate

SOURCES = ("Cut Receive", "Process Receive")


def work_rows(
	supplier: str | None = None,
	from_date=None,
	to_date=None,
	company: str | None = None,
) -> list[frappe._dict]:
	"""Contractor work per (source document, garment order), oldest first."""
	values = {"supplier": supplier, "from_date": from_date, "to_date": to_date, "company": company}

	def where(alias: str, party_field: str) -> str:
		parts = [f"{alias}.docstatus = 1", f"ifnull({alias}.{party_field}, '') != ''"]
		if supplier:
			parts.append(f"{alias}.{party_field} = %(supplier)s")
		if from_date:
			parts.append(f"{alias}.posting_date >= %(from_date)s")
		if to_date:
			parts.append(f"{alias}.posting_date <= %(to_date)s")
		if company:
			parts.append(f"{alias}.company = %(company)s")
		return " and ".join(parts)

	rows = frappe.db.sql(
		f"""select 'Cut Receive' as source_doctype, cr.name as source_name, cr.posting_date, cr.cutting_party as supplier,
			'Cutting' as process, crp.garment_order, sum(crp.good_qty) as fresh_qty,
			sum(crp.contractor_cost_amount) as amount, cr.service_order, cr.company
		from `tabCut Receive Piece` crp join `tabCut Receive` cr on cr.name = crp.parent
		where {where("cr", "cutting_party")} and crp.parenttype = 'Cut Receive'
		group by cr.name, crp.garment_order
		union all
		select 'Process Receive', pr.name, pr.posting_date, pr.party, pr.production_process, prb.garment_order,
			sum(prb.fresh_qty), sum(prb.contractor_cost_amount), max(prb.service_order), pr.company
		from `tabProcess Receive Bundle` prb join `tabProcess Receive` pr on pr.name = prb.parent
		where {where("pr", "party")} and prb.parenttype = 'Process Receive'
		group by pr.name, prb.garment_order
		order by posting_date, source_name""",
		values,
		as_dict=True,
	)
	rows = [r for r in rows if flt(r.amount) > 0]
	if not rows:
		return []

	# Service Order rows (for the bill's item and reference)
	so_rows = {}
	orders = list({r.service_order for r in rows if r.service_order})
	if orders:
		for s in frappe.get_all(
			"Purchase Order Item",
			filters={"parent": ("in", orders), "parenttype": "Purchase Order"},
			fields=["name", "parent", "production_process", "garment_order", "item_code", "base_rate"],
		):
			so_rows.setdefault((s.parent, s.production_process, s.garment_order), s)

	status = invoice_status([(r.source_doctype, r.source_name) for r in rows])
	for r in rows:
		r.fresh_qty = cint(r.fresh_qty)
		r.amount = flt(r.amount, 2)
		r.rate = flt(r.amount / r.fresh_qty, 6) if r.fresh_qty else 0
		so = so_rows.get((r.service_order, r.process, r.garment_order))
		r.service_order_item = so.name if so else None
		r.service_item = so.item_code if so else None
		st = status.get((r.source_doctype, r.source_name), {})
		r.billed_on = st.get("submitted")  # submitted invoice
		r.taken_by = st.get("active")  # any invoice that is not cancelled
	return rows


def invoice_status(sources: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
	"""{(doctype, name): {"active": invoice not cancelled, "submitted": submitted invoice}}."""
	if not sources:
		return {}
	names = list({s[1] for s in sources})
	result: dict[tuple[str, str], dict] = defaultdict(dict)
	for doctype, name, invoice, docstatus in frappe.db.sql(
		"""select pii.velocity_source_doctype, pii.velocity_source_name, pi.name, pi.docstatus
		from `tabPurchase Invoice Item` pii join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pi.docstatus < 2 and pii.velocity_source_name in %(names)s""",
		{"names": names},
	):
		entry = result[(doctype, name)]
		entry["active"] = invoice
		if docstatus == 1:
			entry["submitted"] = invoice
	return result


def unbilled(rows: list[frappe._dict]) -> list[frappe._dict]:
	"""Work not on a submitted invoice (still in Contractor Charges Accrued)."""
	return [r for r in rows if not r.billed_on]


def unbilled_total(company: str | None = None) -> float:
	return flt(sum(r.amount for r in unbilled(work_rows(company=company))), 2)


def age_bucket(posting_date, as_of) -> str:
	days = (getdate(as_of) - getdate(posting_date)).days
	if days <= 15:
		return "0-15"
	if days <= 30:
		return "16-30"
	return "31+"


def accrual_gl_balance(company: str, as_of=None) -> float:
	"""Credit balance of Contractor Charges Accrued (positive = owed to contractors)."""
	from velocity_ctp.production.absorption import CONTRACTOR_ACCRUAL, charge_account

	account = charge_account(company, CONTRACTOR_ACCRUAL)
	conditions, values = ["account = %(a)s", "is_cancelled = 0"], {"a": account}
	if as_of:
		conditions.append("posting_date <= %(d)s")
		values["d"] = as_of
	return flt(
		frappe.db.sql(
			f"select ifnull(sum(credit - debit), 0) from `tabGL Entry` where {' and '.join(conditions)}",
			values,
		)[0][0],
		2,
	)


def billed_rate_differences(company: str | None = None) -> list[frappe._dict]:
	"""Submitted invoice rows whose amount differs from the accrued amount of their source document
	(an invoice rate within the tolerance). The difference stays in the accrual account until adjusted."""
	rows = work_rows(company=company)
	billed = {(r.source_doctype, r.source_name, r.garment_order): r for r in rows if r.billed_on}
	if not billed:
		return []
	result = []
	for doctype, name, order, amount, invoice, posting_date in frappe.db.sql(
		"""select pii.velocity_source_doctype, pii.velocity_source_name, pii.garment_order, sum(pii.base_amount),
			pi.name, pi.posting_date
		from `tabPurchase Invoice Item` pii join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pi.docstatus = 1 and ifnull(pii.velocity_source_name, '') != ''
		group by pii.velocity_source_doctype, pii.velocity_source_name, pii.garment_order, pi.name"""
	):
		work = billed.get((doctype, name, order))
		if work and abs(flt(work.amount) - flt(amount)) >= 0.01:
			result.append(
				frappe._dict(
					supplier=work.supplier,
					source_doctype=doctype,
					source_name=name,
					garment_order=order,
					process=work.process,
					posting_date=posting_date,
					purchase_invoice=invoice,
					amount=flt(work.amount - flt(amount), 2),
				)
			)
	return result
