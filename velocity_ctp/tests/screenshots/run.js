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
const LIBS = path.join(HERE, ".browser-libs", "usr", "lib", "x86_64-linux-gnu");
const WIDTHS = [1920, 1366, 820];
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
		const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: "en-US" });
		const page = await context.newPage();
		let errors = [];
		page.on("pageerror", (e) => errors.push(String(e).split("\n")[0]));
		page.on("console", (m) => {
			if (m.type() === "error" && !/socket\.io|favicon|ERR_CONNECTION_REFUSED/i.test(m.text())) {
				errors.push(m.text().split("\n")[0]);
			}
		});

		const login = await page.request.post(`${BASE}/api/method/login`, {
			form: { usr: info.email, pwd: info.password },
		});
		if (!login.ok()) throw new Error(`Login failed (${login.status()}). Is "bench start" running?`);

		const route = (doctype, name) => `/desk/${doctype}/${encodeURIComponent(name)}`;
		const pages = [
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

		for (const width of WIDTHS) {
			await page.setViewportSize({ width, height: width >= 1366 ? 1000 : 1180 });
			for (const p of pages) {
				for (const theme of THEMES) {
					errors = [];
					await page.goto(BASE + p.url, { waitUntil: "networkidle" });
					await page.evaluate((t) => {
						document.documentElement.setAttribute("data-theme", t);
						document.documentElement.setAttribute("data-theme-mode", t);
					}, theme);
					await page.waitForSelector(p.ready, { timeout: 20000 });
					await page.waitForTimeout(600);

					const shots = [{ name: "", run: null }];
					if (p.extra) shots.push({ name: p.extra.name, run: p.extra.click });
					for (const shot of shots) {
						if (shot.run) {
							const target = page.locator(shot.run).first();
							if (!(await target.count())) continue;
							await target.click();
							await page.waitForTimeout(400);
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
