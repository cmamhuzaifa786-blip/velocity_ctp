# Velocity CTP – development tests

These tools are for development only. The app never imports them, and they do not run on
install or migrate.

## Quantity matrix test

Runs the Garment Order form script in Node with stubbed Frappe objects and checks the colour × size
matrix (rows created, updated and removed from the grid, rates, totals, read-only mode).

```bash
node velocity_ctp/tests/quantity_matrix.test.js
```

## Setup must not change existing records

`setup_masters()` only creates missing records and sets defaults on the records it creates. This test changes
existing values (Washing's colour change, a process type, a warehouse account, Stock Settings, Velocity Settings, a wash
type, a UOM), runs `setup_masters()` again inside a transaction, checks every value is unchanged and rolls back:

```bash
bench --site velocity.local execute velocity_ctp.tests.test_setup_masters.run
```

## Screenshot check

`screenshots/run.js` opens the Velocity pages in a headless Chromium and saves full-page screenshots.

**Covers:** Velocity Home, Order Tracker, the latest Garment Order (plus its Cutting Qty view), the latest
Job Map, Fabric Issue, Cutting Marker, Cut Receive and Bundle, the Bundle list and the Cutting Report, in light and
dark theme, at 1920px, 1366px and 820px (tablet) width; the Scan Station, Production Control Tower, Process Issue,
Process Receive, Packing List and the Process Movement Report likewise; plus the Bundle Ticket (A4 and thermal), Process
Challan and Packing List prints at 1366px; and the Cost Sheet (with its Summary tab), Material Plan (with availability),
Order Costing report and Cost Head list in both themes and all widths. Procurement (Phase 6): Material Request, Purchase
Order (approved and pending), Purchase Receipt, Quality Inspection, Purchase Invoice, Accessory Allocation, Accessory
Issue, Department Issue, the Material Request and Purchase Order lists and the PO Status, GRN Register, Job Accessory
Balance and Supplier Performance reports; plus the Velocity Purchase Order print (approved and UNAPPROVED) at 1366px.

Services and costing (Phase 7): the Contractor Bill Run (with its Contractor Statement print), a Service Purchase
Order and the Contractor Ledger and Accrued Contractor Charges reports.

Shipment and gate (Phase 8): Delivery Note, Sales Invoice with the Commercial Invoice print, Sales Order with the
Proforma Invoice print, Gate Outward and Gate Inward with their slips, and the Shipment Register, Gate Balance and
Order Closing Sheet reports.

`ONLY=key1,key2` runs only the pages whose key contains one of the parts, for example
`ONLY=purchase,report-po node velocity_ctp/tests/screenshots/run.js`.

**Reports:** JavaScript errors, cut-off text, and pages that scroll sideways. Every result is also written to
`screenshots/output/summary.json`. Always look at the screenshots yourself as well: the automatic checks cannot
judge contrast or overlap.

### Run

From the app folder (`apps/velocity_ctp`), with `bench start` running:

```bash
node velocity_ctp/tests/screenshots/run.js
```

Optional environment variables: `SITE` (default `velocity.local`), `BASE_URL` (default `http://<SITE>:8000`),
`BENCH_DIR`, `CHROMIUM_PATH`, `OUT_DIR`.

Screenshots go to `velocity_ctp/tests/screenshots/output/` (git-ignored, replaced on every run).

### Test user

The script creates a temporary user `vt.screenshots@example.com` with the roles **Velocity Merchandiser**, **Velocity Cutting**, **Stock User**,
**Sales User**, **Purchase User**, **Quality Manager** and **Accounts User** and a random password, and always deletes it at the end, also after an error or Ctrl+C.
If a run is killed hard, remove the user with:

```bash
bench --site velocity.local execute velocity_ctp.tests.screenshots.user.delete
```

### Requirements (no sudo)

- **Playwright**: any copy on the bench works; the script looks in `node_modules` of every app
  (for example `apps/crm`), or install it with `npm i -D playwright`.
- **Chromium**: Playwright's browser in `~/.cache/ms-playwright` (`npx playwright install chromium`).
- **Shared libraries**: on a bare WSL/Ubuntu the browser may fail with
  `error while loading shared libraries: libnspr4.so`. Run `bash velocity_ctp/tests/screenshots/fetch_browser_libs.sh`
  once: it downloads the missing libraries with `apt-get download` (no root) into
  `screenshots/.browser-libs/` (git-ignored), and `run.js` uses them automatically.
