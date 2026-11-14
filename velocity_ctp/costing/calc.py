"""Cost Sheet calculation (per piece). One implementation used by the form, the controller and reports.

Rules (all per piece, PKR rounded to 2 decimals with the site's rounding method):
- Fabric Cost    = sum(fabric usage x unit cost) x (1 + excess %)
- Accessory Cost = sum(accessory usage x unit cost) x (1 + excess %)
- Quoted FOB PKR = quoted FOB (order currency) x exchange rate
- Percent heads  = quoted FOB PKR x percent / 100
- Costed FOB     = Fabric + Accessory + Amount per Piece heads + Percent heads (Freight section excluded)
- Profit FOB     = Quoted FOB - Costed FOB; Profit % = Profit / Quoted x 100
- CNF (price basis CNF): Costed CNF = Costed FOB + Freight; Quoted CNF entered in the order currency
- Every PKR figure is also given in the order currency (PKR / exchange rate, 2 decimals)
"""

from __future__ import annotations

from frappe.utils import cint, flt

FABRIC_HEAD = "Fabric Cost"
ACCESSORY_HEAD = "Accessory Cost"
FREIGHT_SECTION = "Freight"
PERCENT = "Percent of Quoted FOB"
PER_PIECE = "Amount per Piece"
COMPUTED = "Computed"


def money(value) -> float:
	return flt(value, 2)


def to_fc(pkr, rate) -> float:
	return flt(flt(pkr) / flt(rate), 2) if flt(rate) else 0.0


def calculate(doc) -> None:
	"""Fill row amounts and all totals on a Cost Sheet document (in place)."""
	rate = flt(doc.exchange_rate)
	excess = 1 + flt(doc.excess_percent) / 100

	for row in doc.fabrics or []:
		row.amount = money(flt(row.usage_per_pc) * flt(row.unit_cost))
	for row in doc.accessories or []:
		row.amount = money(flt(row.usage_per_pc) * flt(row.unit_cost))
	doc.fabric_cost_pkr = money(sum(flt(r.amount) for r in doc.fabrics or []) * excess)
	doc.accessory_cost_pkr = money(sum(flt(r.amount) for r in doc.accessories or []) * excess)

	doc.quoted_fob_pkr = money(flt(doc.quoted_fob_fc) * rate)
	fob_total = 0.0
	freight = 0.0
	for row in doc.costs or []:
		if row.calculation == COMPUTED:
			row.amount_pkr = {FABRIC_HEAD: doc.fabric_cost_pkr, ACCESSORY_HEAD: doc.accessory_cost_pkr}.get(
				row.cost_head, 0.0
			)
			row.rate_or_percent = 0
		elif row.calculation == PERCENT:
			row.amount_pkr = money(doc.quoted_fob_pkr * flt(row.rate_or_percent) / 100)
		else:
			row.amount_pkr = money(row.rate_or_percent)
		row.amount_fc = to_fc(row.amount_pkr, rate)
		if row.section == FREIGHT_SECTION:
			freight += flt(row.amount_pkr)
		else:
			fob_total += flt(row.amount_pkr)

	doc.costed_fob_pkr = money(fob_total)
	doc.costed_fob_fc = to_fc(doc.costed_fob_pkr, rate)
	doc.profit_fob_pkr = money(doc.quoted_fob_pkr - doc.costed_fob_pkr)
	doc.profit_fob_fc = to_fc(doc.profit_fob_pkr, rate)
	doc.profit_fob_percent = (
		flt(doc.profit_fob_pkr / doc.quoted_fob_pkr * 100, 2) if doc.quoted_fob_pkr else 0
	)

	doc.freight_pkr = money(freight)
	cnf = doc.price_basis == "CNF"
	doc.costed_cnf_pkr = money(doc.costed_fob_pkr + doc.freight_pkr) if cnf else 0
	doc.costed_cnf_fc = to_fc(doc.costed_cnf_pkr, rate) if cnf else 0
	doc.quoted_cnf_pkr = money(flt(doc.quoted_cnf_fc) * rate) if cnf else 0
	doc.profit_cnf_pkr = money(doc.quoted_cnf_pkr - doc.costed_cnf_pkr) if cnf else 0
	doc.profit_cnf_fc = to_fc(doc.profit_cnf_pkr, rate) if cnf else 0
	doc.profit_cnf_percent = (
		flt(doc.profit_cnf_pkr / doc.quoted_cnf_pkr * 100, 2) if cnf and doc.quoted_cnf_pkr else 0
	)

	qty = cint(doc.quantity_pcs)
	costed, quoted = (
		(doc.costed_cnf_pkr, doc.quoted_cnf_pkr) if cnf else (doc.costed_fob_pkr, doc.quoted_fob_pkr)
	)
	doc.total_costed_value = money(costed * qty)
	doc.total_quoted_value = money(quoted * qty)
	doc.total_profit = money(doc.total_quoted_value - doc.total_costed_value)
