// Run: node velocity_ctp/tests/quantity_matrix.test.js
// Runs the real garment_order.js in a vm with stubbed frappe/jQuery and checks the
// quantity matrix <-> child table sync, rates, totals and the 12-size layout.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const path = require("node:path");
const SRC = path.join(__dirname, "..", "velocity_ctp", "doctype", "garment_order", "garment_order.js");

function noop$() {
	const p = new Proxy(function () {}, {
		get: (t, k) => (k === "length" ? 0 : k === Symbol.toPrimitive ? () => "" : p),
		apply: () => p,
	});
	return p;
}

let html = "";
const wrapper = new Proxy(function () {}, {
	get: (t, k) => {
		if (k === "html") return (h) => ((html = String(h)), wrapper);
		if (k === "find") return () => noop$();
		return noop$();
	},
});

const locals = { "Garment Order Item": {} };
let seq = 0;
const frm = {
	doc: { doctype: "Garment Order", name: "new-go-1", docstatus: 0, excess_percent: 5, currency: "PKR", items: [] },
	vt_layout: {
		style: "S1",
		customer: "C1",
		colours: ["Dark Indigo", "Black"],
		sizes: ["26", "27", "28", "29", "30", "31", "32", "33", "34", "36", "38", "40"],
	},
	dirty_calls: 0,
	get_field: () => ({ $wrapper: wrapper }),
	add_child(field, values) {
		const row = Object.assign({ doctype: "Garment Order Item", name: `row-${++seq}`, parentfield: field }, values);
		row.idx = this.doc.items.length + 1;
		locals["Garment Order Item"][row.name] = row;
		this.doc.items.push(row);
		return row;
	},
	refresh_fields() {},
	refresh_field() {},
	dirty() {
		this.dirty_calls++;
	},
	toggle_display() {},
};

const ctx = {
	console,
	locals,
	__: (s, args) => (args ? s.replace(/\{(\d+)\}/g, (m, i) => args[i]) : s),
	flt: (v) => parseFloat(v) || 0,
	cint: (v) => parseInt(v, 10) || 0,
	precision: () => 2,
	format_number: (v) => String(v),
	format_currency: (v, c) => `${c} ${v}`,
	CSS: { escape: (s) => s },
	$: noop$(),
	frappe: {
		ui: { form: { on: () => {} } },
		utils: { escape_html: (s) => String(s).replace(/</g, "&lt;") },
		model: {
			clear_doc(dt, dn) {
				delete locals[dt][dn];
				frm.doc.items = frm.doc.items.filter((r) => r.name !== dn);
				frm.doc.items.forEach((r, i) => (r.idx = i + 1));
			},
		},
		defaults: { get_user_default: () => "VT" },
	},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(SRC, "utf8") + "\nthis.__vt = vt_matrix;", ctx);
const m = ctx.__vt;

// Render with 12 sizes: every size header and an input per cell.
m.render(frm);
for (const s of frm.vt_layout.sizes) assert.ok(html.includes(`<th>${s}</th>`), `header ${s}`);
assert.equal((html.match(/class="vt-qty /g) || []).length, 24, "24 qty inputs (2 colours x 12 sizes)");
assert.ok(html.includes("Show detail rows"));

// Typing quantities creates rows with excess/cutting.
m.set_qty(frm, "Dark Indigo", "28", 100);
m.set_qty(frm, "Dark Indigo", "30", 150);
m.set_qty(frm, "Black", "32", 75);
assert.equal(frm.doc.items.length, 3);
assert.deepEqual(frm.doc.items.map((r) => [r.excess_qty, r.cutting_qty]), [[5, 105], [8, 158], [4, 79]]);
assert.equal(frm.doc.total_order_qty, 325);
assert.equal(frm.doc.total_cutting_qty, 342);

// Rate per colour applies to that colour's rows; a new row in that colour inherits it.
m.set_rate(frm, "Dark Indigo", 12.5);
m.set_qty(frm, "Dark Indigo", "40", 10);
const di = frm.doc.items.filter((r) => r.colour === "Dark Indigo");
assert.ok(di.every((r) => r.rate === 12.5), "rate applied to colour");
assert.equal(frm.doc.total_amount, (100 + 150 + 10) * 12.5);
assert.equal(m.colour_rate(frm, "Black").value, "", "black rate unset");

// Updating a qty updates the row in place (no duplicate).
m.set_qty(frm, "Dark Indigo", "28", 120);
assert.equal(frm.doc.items.filter((r) => r.size === "28").length, 1);
assert.equal(frm.doc.items.find((r) => r.size === "28").order_qty, 120);

// Zero removes the row and re-indexes.
m.set_qty(frm, "Black", "32", 0);
assert.equal(frm.doc.items.length, 3);
assert.deepEqual(frm.doc.items.map((r) => r.idx), [1, 2, 3]);
assert.equal(frm.doc.total_order_qty, 280);

// Mixed rates show as "Mixed".
frm.doc.items[0].rate = 11;
assert.equal(m.colour_rate(frm, "Dark Indigo").mixed, true);

// Rows from another style are flagged in the matrix.
frm.add_child("items", { colour: "Red", size: "28", order_qty: 1 });
m.render(frm);
assert.ok(html.includes("1 detail row(s) do not match"));

// Read-only after submit: no inputs.
frm.doc.docstatus = 1;
m.render(frm);
assert.equal((html.match(/<input/g) || []).length, 0, "no inputs when submitted");

// Case-insensitive match between grid and rows.
assert.equal(m.key("BLACK", "28"), m.key("black", "28"));
console.log("matrix tests passed");
