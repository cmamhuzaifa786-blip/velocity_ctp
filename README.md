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

## Development checks

A git pre-commit hook runs `ruff check` and `ruff format --check` on `velocity_ctp` and blocks the commit on any
problem. It uses `uvx ruff@0.14.10` (or a `ruff` on the PATH). Install it once per clone:

```bash
git config core.hooksPath .githooks
```

Tests and the screenshot check are described in `velocity_ctp/tests/README.md`.
