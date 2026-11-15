"""Agent commission accounting for Sales Invoices with a Sales Partner.

On submit of a Sales Invoice with a Sales Partner and a commission, a Journal Entry is made:
  Dr "Commission on Sales - <abbr>" (Indirect Expenses)
  Cr the company's payable account, party = the agent's Supplier
The agent is a Supplier (Sales Partner field "Commission Supplier"; created with the partner's name the
first time if not set), so each agent has a normal payable that shows in Accounts Payable and is paid
with a Payment Entry. The Journal Entry is cancelled when the invoice is cancelled.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

COMMISSION_ACCOUNT = "Commission on Sales"


def commission_account(company: str) -> str:
	account = frappe.db.get_value(
		"Account", {"company": company, "account_name": COMMISSION_ACCOUNT, "is_group": 0}, "name"
	)
	if not account:
		frappe.throw(
			_("Account {0} does not exist for company {1}. Please run the Velocity CTP setup.").format(
				frappe.bold(COMMISSION_ACCOUNT), frappe.bold(company)
			)
		)
	return account


def agent_supplier(sales_partner: str) -> str:
	"""The Supplier that receives the agent's commission (created and linked on first use)."""
	supplier = frappe.db.get_value("Sales Partner", sales_partner, "commission_supplier")
	if supplier:
		return supplier
	name = frappe.db.get_value("Supplier", {"supplier_name": sales_partner}, "name")
	if not name:
		group = frappe.db.get_single_value("Buying Settings", "supplier_group") or frappe.db.get_value(
			"Supplier Group", {"is_group": 0}, "name"
		)
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": sales_partner,
				"supplier_group": group,
				"supplier_type": "Company",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		name = doc.name
	frappe.db.set_value("Sales Partner", sales_partner, "commission_supplier", name)
	return name


def sales_invoice_on_submit(doc, method=None) -> None:
	amount = flt(doc.get("total_commission"), 2)
	if doc.get("is_return") or not doc.get("sales_partner") or amount <= 0:
		return
	supplier = agent_supplier(doc.sales_partner)
	payable = frappe.get_cached_value("Company", doc.company, "default_payable_account")
	cost_center = doc.get("cost_center") or frappe.get_cached_value("Company", doc.company, "cost_center")
	remark = _("Commission {0}% of {1} on Sales Invoice {2} ({3})").format(
		flt(doc.commission_rate, 2), doc.sales_partner, doc.name, doc.customer
	)
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": doc.company,
			"posting_date": doc.posting_date,
			"user_remark": remark,
			"accounts": [
				{
					"account": commission_account(doc.company),
					"debit_in_account_currency": amount,
					"cost_center": cost_center,
					"user_remark": remark,
				},
				{
					"account": payable,
					"party_type": "Supplier",
					"party": supplier,
					"credit_in_account_currency": amount,
					"cost_center": cost_center,
					"user_remark": remark,
				},
			],
		}
	)
	je.flags.ignore_permissions = True  # part of the user's invoice submit
	je.insert()
	je.submit()
	doc.db_set("commission_journal_entry", je.name)


def sales_invoice_on_cancel(doc, method=None) -> None:
	name = doc.get("commission_journal_entry")
	if name and frappe.db.get_value("Journal Entry", name, "docstatus") == 1:
		je = frappe.get_doc("Journal Entry", name)
		je.flags.ignore_permissions = True
		je.cancel()
