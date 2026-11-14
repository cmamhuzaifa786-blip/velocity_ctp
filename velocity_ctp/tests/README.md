# Velocity CTP – development tests

These tools are for development only. The app never imports them, and they do not run on
install or migrate.

## Quantity matrix test

Runs the Garment Order form script in Node with stubbed Frappe objects and checks the colour × size
matrix (rows created, updated and removed from the grid, rates, totals, read-only mode).

```bash
node velocity_ctp/tests/quantity_matrix.test.js
```

## Screenshot check

`screenshots/run.js` opens the Velocity pages in a headless Chromium and saves full-page screenshots.

**Covers:** Velocity Home, Order Tracker, the latest Garment Order (plus its Cutting Qty view) and the latest
Job Map, in light and dark theme, at 1920px, 1366px and 820px (tablet) width.

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

The script creates a temporary user `vt.screenshots@example.com` with the roles **Velocity Merchandiser**
and **Sales User** and a random password, and always deletes it at the end, also after an error or Ctrl+C.
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
