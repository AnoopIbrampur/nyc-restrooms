import test from "node:test";
import assert from "node:assert/strict";
import { applyFilters, confirmationLines, nycNow, openNow, walkMinutes } from "../docs/assets/status.js";

const mask = (open) => { const m = Array(168).fill("0"); open.forEach((h) => (m[h] = "1")); return m.join(""); };

test("nycNow uses New York time and season", () => {
  // 2026-07-15 23:30 UTC = Wed 19:30 EDT
  const n = nycNow(new Date("2026-07-15T23:30:00Z"));
  assert.equal(n.dow, 2); assert.equal(n.hour, 19); assert.equal(n.season, "s"); assert.equal(n.iso, "2026-07-15");
  const w = nycNow(new Date("2027-01-27T15:00:00Z")); // Wed 10:00 EST
  assert.equal(w.season, "w"); assert.equal(w.idx, 2 * 24 + 10);
});

test("openNow: true/false/null", () => {
  const now = { season: "s", idx: 10 };
  assert.equal(openNow({ s: mask([10]), w: mask([]) }, now), true);
  assert.equal(openNow({ s: mask([11]), w: mask([]) }, now), false);
  assert.equal(openNow({ s: null, w: null }, now), null);
});

test("filters hide unknown separately and never treat it as no", () => {
  const now = { season: "s", idx: 10 };
  const list = [
    { id: 1, s: mask([10]), acc: "yes", chg: "unknown", gn: "no" },
    { id: 2, s: mask([10]), acc: "unknown", chg: "yes", gn: "yes" },
    { id: 3, s: mask([10]), acc: "no", chg: "yes", gn: "yes" },
    { id: 4, s: mask([10]), acc: "limited", chg: "no", gn: "unknown" },
    { id: 5, s: null, acc: "yes", chg: "yes", gn: "yes" },
    { id: 6, s: mask([11]), acc: "yes", chg: "yes", gn: "yes" },
  ];
  const r = applyFilters(list, { acc: "yes" }, { now });
  assert.deepEqual(r.shown.map((x) => x.id), [1, 4]);
  assert.equal(r.hidden.acc, 1); assert.equal(r.hidden.hours, 1);
  const r2 = applyFilters(list, { acc: "yes" }, { now, includeUnknownHours: true });
  assert.deepEqual(r2.shown.map((x) => x.id), [1, 4, 5]);
});

test("confirmation lines show recency and counts, not percentages", () => {
  assert.deepEqual(confirmationLines(null, "2026-11-27"), ["Not confirmed by anyone recently"]);
  const lines = confirmationLines(
    { open_n: 3, last_open: "2026-11-15", closed_n: 0, needs_code_n: 1, clean_n: 2, dirty_n: 1 }, "2026-11-27");
  assert.equal(lines[0], "Confirmed open 12 days ago · 3 confirmations");
  assert.ok(lines.includes("Needs a code or key (1 report)"));
  assert.ok(lines.includes("Clean ×2 · Dirty ×1"));
  assert.ok(!lines.join(" ").includes("%"));
  const closed = confirmationLines({ open_n: 0, last_open: null, closed_n: 3, needs_code_n: 0, clean_n: 0, dirty_n: 0 }, "2026-11-27");
  assert.ok(closed.includes("Reported closed by 3 people in the last 90 days"));
});

test("walk minutes match the Phase 2 assumptions", () => {
  assert.equal(walkMinutes(1.2), 20); // 1.2 km straight -> 1.5 km walked at 1.25 m/s
});
