#!/usr/bin/env node
// Velocity CTP screenshot check (development only). See tests/README.md.
//
// Logs in as a temporary user (created and always deleted again through bench), opens
// Velocity Home, Order Tracker, a Garment Order and a Job Map in light and dark theme at
// 1920px, 1366px and tablet width, saves full-page screenshots to tests/screenshots/output/
// (git-ignored) and reports JavaScript errors, cut-off text and horizontal overflow.
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const HERE = __dirname;
const BENCH = process.env.BENCH_DIR || path.resolve(HERE, "..", "..", "..", "..", "..");
const SITE = process.env.SITE || "velocity.local";
const BASE = (process.env.BASE_URL || `http://${SITE}:8000`).replace(/\/$/, "");
const OUT = process.env.OUT_DIR || path.join(HERE, "output");
// A site served without its own host name (for example BASE_URL=http://127.0.0.1:8000) is picked by this header.
const SITE_HEADERS = new URL(BASE).hostname === SITE ? {} : { "X-Frappe-Site-Name": SITE };
const LIBS = path.join(HERE, ".browser-libs", "usr", "lib", "x86_64-linux-gnu");
const WIDTHS = [1920, 1366, 820];
// ONLY=key1,key2 limits the run to pages whose key contains one of the given parts (for example ONLY=purchase,po-).
// Prints are shown with this letter head (LETTER_HEAD= for none).
const LETTER_HEAD = process.env.LETTER_HEAD ?? "Velocity Textiles";
const LH = LETTER_HEAD ? { letterhead: LETTER_HEAD } : { ...LH };
const ONLY = (process.env.ONLY || "").split(",").map((k) => k.trim()).filter(Boolean);
const THEMES = ["light", "dark"];

// ---------------------------------------------------------------- bench helpers

function bench(method) {
	const res = spawnSync("bench", ["--site", SITE, "execute", `velocity_ctp.tests.screenshots.user.${method}`], {
		cwd: BENCH,
		encoding: "utf8",
	});
	if (res.status !== 0) {
		throw new Error(`bench execute ${method} failed:\n${res.stderr || res.stdout}`);
	}
	// bench prints the return value as JSON; take the last JSON object in the output.
	const match = res.stdout.match(/\{[\s\S]*\}\s*$/);
	return match ? JSON.parse(match[0]) : {};
}

let cleanedUp = false;
function cleanup() {
	if (cleanedUp) return;
	cleanedUp = true;
	try {
		bench("delete");
		console.log("Temporary user deleted.");
	} catch (e) {
		console.error("WARNING: could not delete the temporary user. Run:\n" +
			`  bench --site ${SITE} execute velocity_ctp.tests.screenshots.user.delete\n` + e.message);
		process.exitCode = 1;
	}
}
for (const signal of ["SIGINT", "SIGTERM"]) {
	process.on(signal, () => {
		cleanup();
		process.exit(130);
	});
}

// ---------------------------------------------------------------- browser helpers

function loadPlaywright() {
	const candidates = ["playwright"];
	for (const app of fs.readdirSync(path.join(BENCH, "apps"))) {
		candidates.push(path.join(BENCH, "apps", app, "node_modules", "playwright"));
	}
	for (const candidate of candidates) {
		try {
			return require(candidate);
		} catch (e) {
			// try the next one
		}
	}
	throw new Error("Playwright not found. Install it (npm i -D playwright) or set NODE_PATH.");
}

function findChromium(chromium) {
	if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
	try {
		if (fs.existsSync(chromium.executablePath())) return undefined; // Playwright's own build
	} catch (e) {
		// fall through
	}
	const cache = path.join(os.homedir(), ".cache", "ms-playwright");
	if (!fs.existsSync(cache)) return undefined;
	const found = [];
	for (const dir of fs.readdirSync(cache).sort().reverse()) {
		for (const rel of ["chrome-linux/headless_shell", "chrome-headless-shell-linux64/chrome-headless-shell", "chrome-linux/chrome"]) {
			const p = path.join(cache, dir, rel);
			if (fs.existsSync(p)) found.push(p);
		}
	}
	return found[0];
}

// Elements whose text is cut off (ellipsis or clipped) inside the page content.
function pageChecks() {
	const root = document.querySelector(".page-container:not([style*='display: none']) .layout-main") || document.body;
	const truncated = [];
	for (const el of root.querySelectorAll("*")) {
		if (!el.offsetParent || el.children.length > 2) continue;
		const text = (el.innerText || "").trim();
		if (!text) continue;
		const cs = getComputedStyle(el);
		const clipped = cs.textOverflow === "ellipsis" || cs.overflow === "hidden" || cs.overflowX === "hidden";
		if (clipped && el.scrollWidth > el.clientWidth + 1) {
			truncated.push(text.slice(0, 60));
		}
	}
	// Table column headers (their cells hold several elements, so check them explicitly).
	for (const el of root.querySelectorAll(".grid-heading-row .static-area, .dt-cell__content--header")) {
		if (el.offsetParent && el.scrollWidth > el.clientWidth + 1) {
			truncated.push(`(column header) ${(el.innerText || "").trim().slice(0, 40)}`);
		}
	}
	// Velocity elements that hide content vertically (for example a fixed-height ticket).
	for (const el of document.querySelectorAll('[class*="vt-"]')) {
		const cs = getComputedStyle(el);
		const hidesY = ["hidden", "clip"].includes(cs.overflowY) || ["hidden", "clip"].includes(cs.overflow);
		if (el.offsetParent && hidesY && el.scrollHeight > el.clientHeight + 2) {
			truncated.push(`(clipped height) ${(el.innerText || "").trim().slice(0, 40)}`);
		}
	}
	return {
		truncated: [...new Set(truncated)].slice(0, 15),
		horizontalOverflow: document.documentElement.scrollWidth - window.innerWidth,
	};
}

// ---------------------------------------------------------------- main

async function main() {
	const { chromium } = loadPlaywright();
	const info = bench("create");
	console.log(`Temporary user ${info.email} created.`);

	fs.rmSync(OUT, { recursive: true, force: true });
	fs.mkdirSync(OUT, { recursive: true });

	const env = { ...process.env };
	if (fs.existsSync(LIBS)) env.LD_LIBRARY_PATH = [LIBS, env.LD_LIBRARY_PATH].filter(Boolean).join(":");
	const browser = await chromium.launch({ executablePath: findChromium(chromium), env });
	const results = [];
	try {
		// Headless Chromium can report no locale, which breaks Frappe's keyboard shortcut setup.
		const context = await browser.newContext({
			viewport: { width: 1920, height: 1080 },
			locale: "en-US",
			extraHTTPHeaders: SITE_HEADERS,
		});
		const page = await context.newPage();
		let errors = [];
		page.on("pageerror", (e) => errors.push(String(e).split("\n")[0]));
		// Name the failing URL ("Failed to load resource" in the console does not say which one).
		page.on("response", (r) => {
			if (r.status() >= 400 && !/socket\.io|favicon/i.test(r.url())) errors.push(`HTTP ${r.status()} ${r.url().replace(BASE, "")}`);
		});
		page.on("console", (m) => {
			if (m.type() === "error" && !/socket\.io|favicon|ERR_CONNECTION_REFUSED/i.test(m.text())) {
				errors.push(m.text().split("\n")[0]);
			}
		});

		// The login page (logged out) shows the app logo.
		if (!ONLY.length || ONLY.some((k) => "login".includes(k))) {
			for (const theme of THEMES) {
				await page.setViewportSize({ width: 1366, height: 1000 });
				await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 60000 });
				await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
				await page.waitForSelector(".app-logo", { timeout: 30000 });
				await page.waitForTimeout(600);
				const file = `login-${theme}-1366.png`;
				await page.screenshot({ path: path.join(OUT, file), fullPage: true });
				const favicon = await page.evaluate(() => document.querySelector("link[rel~='icon']")?.getAttribute("href"));
				console.log(`Login page logo: ${await page.getAttribute(".app-logo", "src")}; favicon: ${favicon}`);
				results.push({ file, errors: [], truncated: [], horizontalOverflow: 0 });
			}
		}

		const login = await page.request.post(`${BASE}/api/method/login`, {
			form: { usr: info.email, pwd: info.password },
		});
		if (!login.ok()) throw new Error(`Login failed (${login.status()}). Is "bench start" running?`);

		const route = (doctype, name) => `/desk/${doctype}/${encodeURIComponent(name)}`;
		const pages = [
			{ key: "desktop", url: "/desk", ready: "#brand-logo", settle: 1200 },
			{ key: "velocity-home", url: "/desk/velocity-home", ready: ".vt-kpi" },
			{ key: "order-tracker", url: "/desk/order-tracker", ready: ".vt-tracker, .vt-empty" },
		];
		if (info.garment_order) {
			pages.push({
				key: "garment-order",
				url: route("garment-order", info.garment_order),
				ready: ".vt-matrix",
				extra: { name: "cutting-qty", click: '[data-matrix-mode="cutting"]' },
			});
		} else {
			console.log("No Garment Order found: skipping the Garment Order form.");
		}
		if (info.job_map) {
			pages.push({ key: "job-map", url: route("job-map", info.job_map), ready: ".vt-approvals" });
		} else {
			console.log("No Job Map found: skipping the Job Map form.");
		}
		// Cutting (Phase 3)
		const optional = [
			["fabric_issue", { key: "fabric-issue", url: () => route("fabric-issue", info.fabric_issue), ready: '[data-fieldname="items"] .grid-body' }],
			["cutting_marker", { key: "cutting-marker", url: () => route("cutting-marker", info.cutting_marker), ready: '[data-fieldname="size_ratio"] .grid-body' }],
			["cut_receive", { key: "cut-receive", url: () => route("cut-receive", info.cut_receive), ready: '[data-fieldname="pieces"] .grid-body' }],
			["bundle", { key: "bundle", url: () => route("bundle", info.bundle), ready: '[data-fieldname="history"] .grid-body' }],
		];
		for (const [field, page] of optional) {
			if (info[field]) pages.push({ ...page, url: page.url() });
			else console.log(`No ${field.replace("_", " ")} found: skipping it.`);
		}
		pages.push({ key: "bundle-list", url: "/desk/bundle", ready: ".list-row-container, .no-result" });
		// Costing and planning (Phase 5)
		if (info.cost_sheet) {
			pages.push({
				key: "cost-sheet",
				url: route("cost-sheet", info.cost_sheet),
				ready: '[data-fieldname="customer"]',
				extra: { name: "summary", click: '.form-tabs .nav-link:has-text("Summary")', wait: ".vt-costing" },
			});
		}
		if (info.material_plan) {
			pages.push({
				key: "material-plan",
				url: route("material-plan", info.material_plan),
				ready: '[data-fieldname="fabrics"] .grid-body',
				extra: { name: "availability", click: 'button:has-text("Check Availability")', wait: '[data-fieldname="availability_html"] table' },
			});
		}
		pages.push({ key: "order-costing", url: "/desk/query-report/Order Costing", ready: ".dt-row, .no-result, .report-wrapper", settle: 1500 });
		pages.push({ key: "cost-head-list", url: "/desk/cost-head", ready: ".list-row-container, .no-result" });
		// Production (Phase 4)
		pages.push({ key: "scan-station", url: "/desk/scan-station", ready: ".vt-choice" });
		pages.push({ key: "control-tower", url: "/desk/production-control", ready: ".vt-kpi, .vt-empty" });
		pages.push({ key: "movement-report", url: "/desk/query-report/Process Movement Report", ready: ".dt-row, .no-result, .report-wrapper", settle: 1500 });
		const production = [
			["process_issue", "process-issue", '[data-fieldname="bundles"] .grid-body', "Process Challan"],
			["process_receive", "process-receive", '[data-fieldname="bundles"] .grid-body', null],
			["packing_list", "packing-list", '[data-fieldname="cartons"] .grid-body', "Packing List"],
		];
		for (const [field, slug, ready, format] of production) {
			if (!info[field]) {
				console.log(`No ${field.replace("_", " ")} found: skipping it.`);
				continue;
			}
			pages.push({ key: slug, url: route(slug, info[field]), ready });
			if (format) {
				const doctype = slug.split("-").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
				const params = new URLSearchParams({ doctype, name: info[field], format, ...LH });
				pages.push({ key: `print-${slug}`, url: `/printview?${params}`, ready: ".vt-doc", print: true });
			}
		}
		pages.push({ key: "cutting-report", url: "/desk/query-report/Cutting Report", ready: ".dt-row, .no-result, .report-wrapper", settle: 1500 });
		if (info.cut_receive) {
			for (const size of ["a4", "thermal"]) {
				const params = new URLSearchParams({ doctype: "Cut Receive", name: info.cut_receive, format: "Bundle Ticket", ...LH, ticket_size: size });
				pages.push({ key: `bundle-ticket-${size}`, url: `/printview?${params}`, ready: ".vt-ticket, .vt-empty-tickets", print: true });
			}
		}

		// Procurement (Phase 6)
		const procurement = [
			["material_request", "material-request", '[data-fieldname="items"] .grid-body'],
			["purchase_order", "purchase-order", '[data-fieldname="items"] .grid-body'],
			["pending_purchase_order", "purchase-order", '[data-fieldname="items"] .grid-body', "pending-purchase-order"],
			["purchase_receipt", "purchase-receipt", '[data-fieldname="items"] .grid-body'],
			["quality_inspection", "quality-inspection", '[data-fieldname="item_code"]'],
			["purchase_invoice", "purchase-invoice", '[data-fieldname="items"] .grid-body'],
			["accessory_allocation", "accessory-allocation", '[data-fieldname="items"] .grid-body'],
			["accessory_issue", "accessory-issue", '[data-fieldname="items"] .grid-body'],
			["department_issue", "department-issue", '[data-fieldname="items"] .grid-body'],
		];
		for (const [field, slug, ready, key] of procurement) {
			if (!info[field]) {
				console.log(`No ${field.replace(/_/g, " ")} found: skipping it.`);
				continue;
			}
			pages.push({ key: key || slug, url: route(slug, info[field]), ready });
		}
		for (const [field, key] of [["purchase_order", "print-purchase-order"], ["pending_purchase_order", "print-purchase-order-unapproved"]]) {
			if (!info[field]) continue;
			const params = new URLSearchParams({ doctype: "Purchase Order", name: info[field], format: "Velocity Purchase Order", ...LH });
			pages.push({ key, url: `/printview?${params}`, ready: ".vt-doc", print: true });
		}
		pages.push({ key: "material-request-list", url: "/desk/material-request", ready: ".list-row-container, .no-result" });
		pages.push({ key: "purchase-order-list", url: "/desk/purchase-order", ready: ".list-row-container, .no-result" });
		for (const report of ["PO Status", "GRN Register", "Job Accessory Balance", "Supplier Performance"]) {
			pages.push({
				key: "report-" + report.toLowerCase().replace(/ /g, "-"),
				url: `/desk/query-report/${report}`,
				ready: ".dt-row, .no-result, .report-wrapper",
				settle: 1500,
			});
		}
		// Services and costing (Phase 7)
		if (info.contractor_bill_run) {
			pages.push({ key: "contractor-bill-run", url: route("contractor-bill-run", info.contractor_bill_run), ready: '[data-fieldname="items"] .grid-body' });
			const params = new URLSearchParams({ doctype: "Contractor Bill Run", name: info.contractor_bill_run, format: "Contractor Statement", ...LH });
			pages.push({ key: "print-contractor-statement", url: `/printview?${params}`, ready: ".vt-doc", print: true });
		}
		if (info.service_order) {
			pages.push({ key: "service-order", url: route("purchase-order", info.service_order), ready: '[data-fieldname="items"] .grid-body' });
		}
		for (const report of ["Contractor Ledger", "Accrued Contractor Charges"]) {
			pages.push({ key: "report-" + report.toLowerCase().replace(/ /g, "-"), url: `/desk/query-report/${report}`, ready: ".dt-row, .no-result, .report-wrapper", settle: 1500 });
		}
		// Shipment and gate (Phase 8)
		const shipping = [
			["delivery_note", "delivery-note", '[data-fieldname="items"] .grid-body', "Delivery Note", null],
			["sales_invoice", "sales-invoice", '[data-fieldname="items"] .grid-body', "Sales Invoice", "Commercial Invoice"],
			["sales_order", "sales-order", '[data-fieldname="items"] .grid-body', "Sales Order", "Proforma Invoice"],
			["gate_outward", "gate-outward", '[data-fieldname="items"] .grid-body', "Gate Outward", "Gate Outward Slip"],
			["gate_inward", "gate-inward", '[data-fieldname="items"] .grid-body', "Gate Inward", "Gate Inward Slip"],
		];
		for (const [field, slug, ready, doctype, format] of shipping) {
			if (!info[field]) {
				console.log(`No ${field.replace(/_/g, " ")} found: skipping it.`);
				continue;
			}
			pages.push({ key: slug, url: route(slug, info[field]), ready });
			if (format) {
				const params = new URLSearchParams({ doctype, name: info[field], format, ...LH });
				pages.push({ key: `print-${slug}`, url: `/printview?${params}`, ready: ".vt-doc", print: true });
			}
		}
		for (const report of ["Shipment Register", "Gate Balance", "Order Closing Sheet"]) {
			pages.push({ key: "report-" + report.toLowerCase().replace(/ /g, "-"), url: `/desk/query-report/${report}`, ready: ".dt-row, .no-result, .report-wrapper", settle: 1500 });
		}
		if (ONLY.length) {
			const keep = pages.filter((p) => ONLY.some((k) => p.key.includes(k)));
			pages.length = 0;
			pages.push(...keep);
			console.log(`ONLY=${ONLY.join(",")}: ${pages.length} pages.`);
		}

		for (const width of WIDTHS) {
			await page.setViewportSize({ width, height: width >= 1366 ? 1000 : 1180 });
			for (const p of pages) {
				if (p.print && width !== 1366) continue;
				for (const theme of p.print ? ["light"] : THEMES) {
					errors = [];
					// Desk pages keep background requests open; wait for the page's own ready selector instead.
					for (let attempt = 1; ; attempt++) {
						try {
							await page.goto(BASE + p.url, { waitUntil: "domcontentloaded", timeout: 60000 });
							break;
						} catch (e) {
							if (attempt >= 2) throw e;
							console.log(`Retrying ${p.key} at ${width}px after: ${e.message.split("\n")[0]}`);
						}
					}
					await page.evaluate((t) => {
						document.documentElement.setAttribute("data-theme", t);
						document.documentElement.setAttribute("data-theme-mode", t);
					}, theme);
					await page.waitForSelector(p.ready, { timeout: 45000 });
					await page.waitForTimeout(p.settle || 600);

					const shots = [{ name: "", run: null }];
					if (p.extra) shots.push({ name: p.extra.name, run: p.extra.click });
					for (const shot of shots) {
						if (shot.run) {
							// Only visible controls (narrow screens move form buttons into a menu): skip the shot otherwise.
							const target = page.locator(`${shot.run} >> visible=true`).first();
							if (!(await target.count())) {
								console.log(`Note: "${shot.name}" control not visible for ${p.key} at ${width}px; that view is skipped.`);
								continue;
							}
							await target.click();
							if (p.extra.wait) await page.waitForSelector(p.extra.wait, { timeout: 15000 }).catch(() => {});
							await page.waitForTimeout(500);
						}
						const file = `${p.key}${shot.name ? "-" + shot.name : ""}-${theme}-${width}.png`;
						await page.screenshot({ path: path.join(OUT, file), fullPage: true });
						const checks = await page.evaluate(pageChecks);
						results.push({ file, errors: [...new Set(errors)], ...checks });
					}
				}
			}
		}
	} finally {
		await browser.close();
	}

	fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(results, null, 1));
	let problems = 0;
	for (const r of results) {
		const issues = [];
		if (r.errors.length) issues.push(`JS errors: ${r.errors.join(" | ")}`);
		if (r.truncated.length) issues.push(`cut-off text: ${r.truncated.map((t) => JSON.stringify(t)).join(", ")}`);
		if (r.horizontalOverflow > 0) issues.push(`page scrolls sideways by ${r.horizontalOverflow}px`);
		problems += issues.length ? 1 : 0;
		console.log(`${issues.length ? "CHECK" : "OK   "} ${r.file}${issues.length ? "\n      " + issues.join("\n      ") : ""}`);
	}
	console.log(`\n${results.length} screenshots in ${OUT}; ${problems} with findings to review.`);
}

main()
	.catch((e) => {
		console.error(e.message || e);
		process.exitCode = 1;
	})
	.finally(cleanup);
