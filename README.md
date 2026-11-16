### Velocity CTP

Cut-to-Pack garment manufacturing app for Velocity Textiles

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch Develop
bench install-app velocity_ctp
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/velocity_ctp
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit

### Procurement settings (run once per site)

Procurement uses standard ERPNext buying documents (Material Request, Purchase Order, Purchase Receipt,
Quality Inspection, Purchase Invoice) with Velocity fields, checks and approval workflows. A few standard
ERPNext settings are recommended for it. They change existing settings, so they are **not** part of the
setup or of migrate: run them once, on purpose, per site:

```bash
bench --site <site> execute velocity_ctp.setup.procurement_settings.apply --kwargs "{'dry_run': True}"  # only show
bench --site <site> execute velocity_ctp.setup.procurement_settings.apply
```

It prints every value it changes (old -> new) and leaves values that are already right alone:

| Settings | Setting | Value |
|---|---|---|
| Buying Settings | Purchase Order Required for Purchase Receipt | Yes |
| Buying Settings | Purchase Receipt Required for Purchase Invoice | Yes |
| Buying Settings | Maintain Same Rate Throughout the Purchase Cycle | On, action Stop |
| Buying Settings | Role allowed to override the stop | Velocity PO Approver L2 |
| Stock Settings | Over Delivery/Receipt Allowance | 2 % |
| Stock Settings | Role allowed to over-deliver/receive | Stock Manager |
| Accounts Settings | Over Billing Allowance | 2 % (so a receipt within the 2 % tolerance can be invoiced in full) |

### Demo site

The demo runs on its own site, `velocity-demo.local`; `velocity.local` stays the development sandbox. To create
it from scratch (or recreate it before a demo, so all dates are current):

```bash
cd ~/frappe-bench
# only when recreating: removes the old demo site and its database (asks for the MariaDB root password)
bench drop-site velocity-demo.local --force
# new site with ERPNext and Velocity CTP (asks for the MariaDB root password)
bench new-site velocity-demo.local --install-app erpnext --install-app velocity_ctp --admin-password 'Velocity@2026'
# company, masters, recommended procurement settings and the letter head
bench --site velocity-demo.local execute velocity_ctp.demo.setup_site.run
# demo data (safe to run again)
bench --site velocity-demo.local execute velocity_ctp.demo.seed.run
```

The seed only runs on a site whose name contains "demo". It posts everything through the normal documents as the
demo users, with dates relative to the day it runs, and records each finished step, so running it again creates
nothing new. `--kwargs "{'dry_run': True}"` runs it and rolls everything back. It writes the logins, the
order numbers and the best record for each feature to `velocity_ctp/demo/DEMO_DATA.md`.

Add `127.0.0.1 velocity-demo.local` to `/etc/hosts` (and to the Windows hosts file when browsing from Windows) to
open it at `http://velocity-demo.local:8000`. The letter head "Velocity Textiles" has a placeholder for the logo:
upload the logo and replace the `vt-lh-logo` block in the Letter Head with an `<img>` of it.

### Shipment and export documents

Deliveries are standard Delivery Notes made from Packing Lists; the Commercial Invoice is the standard Sales
Invoice with export fields (LC, Form E, vessel / BL, cartons and weights) and the "Commercial Invoice" print;
agent commission uses ERPNext's Sales Partner. **FBR e-invoicing (Digital Invoicing) for local sales is out of
scope** of this app: local Sales Invoices (Invoice Category "Local") are not sent to FBR by Velocity CTP; use an
FBR-integrated solution for that.

### Approval workflows

Standard Frappe workflows (fixtures), self-approval off on every approve and reject step:

- **Velocity Material Request Approval** (Purchase requests): Draft -> Pending Approval -> Approved (submitted) or
  Rejected (with a reason) -> Revise -> Draft. Approver: Velocity Requisition Approver. Other request types are
  submitted directly.
- **Velocity Purchase Order Approval**: Draft -> Pending 1st Approval (Velocity PO Approver L1) -> Approved when the
  grand total in company currency is at most *PO Second Approval Limit* (Velocity Settings, default 500,000), else
  -> Pending 2nd Approval (Velocity PO Approver L2) -> Approved. A rejection returns the PO to Draft with the reason
  as a comment. An amended PO goes through the workflow again.

Approvers also need the standard role that may submit the document (Purchase User for requests and POs). On an
approved PO, only Velocity PO Approver L1 may change items, rates or quantities with Update Items.

## Development rules

- Site `velocity.local` only; run `bench --site velocity.local ...` (never a plain `bench migrate` or `bench update`).
- No custom permissions on core ERPNext DocTypes: use standard ERPNext roles for core access (custom fields via
  fixtures are fine).
- `setup_masters()` only creates missing records; it never changes existing values.
- **Real data:** never delete submitted or numbered documents (to reuse a number or to tidy up). Cancel them
  instead, and amend if a corrected document is needed. Numbers stay unique and the audit trail stays complete.
- Do not leave `bench start` running after a task that started it.

## Development checks

A git pre-commit hook runs `ruff check` and `ruff format --check` on `velocity_ctp` and blocks the commit on any
problem. It uses `uvx ruff@0.14.10` (or a `ruff` on the PATH). Install it once per clone:

```bash
git config core.hooksPath .githooks
```

Tests and the screenshot check are described in `velocity_ctp/tests/README.md`.
