// Display rules shared by the app and worker pages (unit-tested in tests_js/).
// Heuristic, not validated: we show recency and counts, never a reliability percentage.

export const FILTER_KEYS = { acc: "Accessible", chg: "Changing table", gn: "Gender-neutral" };

export function nycNow(date = new Date()) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", weekday: "short", hour: "numeric", hour12: false,
      month: "numeric", day: "numeric", year: "numeric",
    }).formatToParts(date).map((p) => [p.type, p.value]),
  );
  const dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday);
  const hour = Number(parts.hour) % 24;
  const month = Number(parts.month);
  const iso = `${parts.year}-${String(month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
  return { idx: dow * 24 + hour, hour, dow, season: month >= 4 && month <= 10 ? "s" : "w", iso };
}

/** true / false by listed hours, or null when hours are unknown. */
export function openNow(r, now) {
  const m = r[now.season];
  if (!m) return null;
  return m[now.idx] === "1";
}

/**
 * Filters: value "any" | "yes". With "yes", places marked "unknown" are hidden but counted,
 * never treated as "no". "limited" accessibility counts as accessible-with-limits (kept).
 */
export function applyFilters(list, filters, { includeUnknownHours = false, now } = {}) {
  const hidden = { acc: 0, chg: 0, gn: 0, hours: 0 };
  const shown = [];
  for (const r of list) {
    const open = now ? openNow(r, now) : null;
    if (now && open === null && !includeUnknownHours) { hidden.hours++; continue; }
    if (now && open === false) continue;
    let ok = true;
    for (const k of Object.keys(FILTER_KEYS)) {
      if (filters[k] !== "yes") continue;
      const v = r[k];
      if (v === "unknown") { hidden[k]++; ok = false; break; }
      if (v === "no") { ok = false; break; }
    }
    if (ok) shown.push(r);
  }
  return { shown, hidden };
}

function daysBetween(aIso, bIso) {
  return Math.round((Date.parse(bIso) - Date.parse(aIso)) / 86400000);
}

/** Text lines for a restroom's community confirmations (aggregated by the server). */
export function confirmationLines(c, todayIso) {
  if (!c) return ["Not confirmed by anyone recently"];
  const lines = [];
  if (c.open_n > 0 && c.last_open) {
    const d = daysBetween(c.last_open, todayIso);
    const when = d <= 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`;
    lines.push(`Confirmed open ${when} · ${c.open_n} confirmation${c.open_n === 1 ? "" : "s"}`);
  } else {
    lines.push("Not confirmed open recently");
  }
  if (c.closed_n > 0) lines.push(`Reported closed by ${c.closed_n} people in the last 90 days`);
  if (c.needs_code_n > 0) lines.push(`Needs a code or key (${c.needs_code_n} report${c.needs_code_n === 1 ? "" : "s"})`);
  if (c.clean_n + c.dirty_n > 0) lines.push(`Clean ×${c.clean_n} · Dirty ×${c.dirty_n}`);
  return lines;
}

export function km(a, b) {
  const R = 6371, t = Math.PI / 180;
  const dLa = (b[0] - a[0]) * t, dLo = (b[1] - a[1]) * t;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(a[0] * t) * Math.cos(b[0] * t) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** Walking minutes from straight-line km: x1.25 detour (Phase 2 median 1.21), 1.25 m/s. */
export function walkMinutes(kmStraight) {
  return Math.round((kmStraight * 1000 * 1.25) / 1.25 / 60);
}
