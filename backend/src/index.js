// nyc-restrooms API (Cloudflare Worker + D1).
//
// Public:   GET  /v1/public      aggregated reports, area rollups, confirmations
// Writes:   POST /v1/report      delivery-worker restroom access report
//           POST /v1/confirm     restroom status confirmation
//           POST /v1/dispute     a business disputes a listing (auto-withholds it)
// Cron:     purge raw rows older than their windows
//
// Raw tables are never returned. Device tokens and network addresses are stored only as
// keyed hashes (HMAC with the HMAC_KEY secret). No free text is accepted anywhere.

import RULES from "../rules.json";
import PLACES_SQL from "../sql/public_places.sql";
import AREAS_SQL from "../sql/public_areas.sql";
import CONFIRM_SQL from "../sql/public_confirmations.sql";

export const OUTCOMES = ["let_in", "refused", "kitchen_exception", "no_restroom"];
export const KINDS = ["open", "closed", "needs_code", "clean", "dirty"];
const PLACE_ID = /^(osm:(node|way):\d{1,12}|dohmh:\d{1,12}|refuge:\d{1,10}|nyc:[0-9a-f]{6,16})$/;
const RESTROOM_ID = /^(osm:(node|way):\d{1,12}|nyc:[0-9a-f]{6,16})$/;
const TOKEN = /^[A-Za-z0-9_-]{16,64}$/;

export function nycDay(now = new Date()) {
  // YYYY-MM-DD in New York time (no time of day is stored)
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(now);
}

async function hmac(key, msg, hexChars) {
  const k = await crypto.subtle.importKey("raw", new TextEncoder().encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg)));
  return [...sig].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, hexChars);
}

function cors(env, res) {
  const h = new Headers(res.headers);
  h.set("Access-Control-Allow-Origin", env.DEV === "1" ? "*" : env.ALLOWED_ORIGIN);
  h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  h.set("Access-Control-Allow-Headers", "Content-Type");
  h.set("Vary", "Origin");
  return new Response(res.body, { status: res.status, headers: h });
}

const json = (obj, status = 200, extra = {}) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...extra } });

async function verifyTurnstile(env, token, ip) {
  if (!env.TURNSTILE_SECRET) return env.DEV === "1"; // fail closed outside local dev
  if (typeof token !== "string" || token.length > 2048) return false;
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", token);
  if (ip) form.append("remoteip", ip);
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
  const out = await r.json();
  return out.success === true;
}

async function identity(env, req, body) {
  if (!env.HMAC_KEY) throw new Error("HMAC_KEY not configured");
  if (!TOKEN.test(body.device_token || "")) return null;
  const ip = req.headers.get("CF-Connecting-IP") || "local";
  return {
    ip,
    device: await hmac(env.HMAC_KEY, "dev:" + body.device_token, 32),
    iphash: await hmac(env.HMAC_KEY, "ip:" + ip, 16),
  };
}

async function overLimit(env, iphash, day) {
  const q = `SELECT (SELECT COUNT(*) FROM reports WHERE iphash=?1 AND day=?2)
                  + (SELECT COUNT(*) FROM confirmations WHERE iphash=?1 AND day=?2) AS n`;
  const row = await env.DB.prepare(q).bind(iphash, day).first();
  return (row?.n ?? 0) >= RULES.max_writes_per_ip_per_day;
}

async function readBody(req) {
  if (!(req.headers.get("Content-Type") || "").includes("application/json")) return null;
  const text = await req.text();
  if (text.length > 4096) return null;
  try { return JSON.parse(text); } catch { return null; }
}

async function handleWrite(env, req, kind) {
  const body = await readBody(req);
  if (!body) return json({ error: "bad request" }, 400);
  const day = nycDay();
  const id = await identity(env, req, body);
  if (!id) return json({ error: "bad device token" }, 400);
  if (!(await verifyTurnstile(env, body.turnstile, id.ip))) return json({ error: "verification failed" }, 403);
  if (await overLimit(env, id.iphash, day)) return json({ error: "too many submissions today" }, 429);

  if (kind === "report") {
    if (!OUTCOMES.includes(body.outcome) || !PLACE_ID.test(body.place_id || "")) return json({ error: "bad report" }, 400);
    const known = await env.DB.prepare("SELECT 1 FROM places WHERE place_id=?1").bind(body.place_id).first();
    if (!known) return json({ error: "unknown place" }, 404);
    await env.DB.prepare("INSERT INTO reports (place_id, outcome, device, iphash, day) VALUES (?1,?2,?3,?4,?5)")
      .bind(body.place_id, body.outcome, id.device, id.iphash, day).run();
  } else if (kind === "confirm") {
    if (!KINDS.includes(body.kind) || !RESTROOM_ID.test(body.restroom_id || "")) return json({ error: "bad confirmation" }, 400);
    await env.DB.prepare("INSERT INTO confirmations (restroom_id, kind, device, iphash, day) VALUES (?1,?2,?3,?4,?5)")
      .bind(body.restroom_id, body.kind, id.device, id.iphash, day).run();
  } else if (kind === "dispute") {
    if (!PLACE_ID.test(body.place_id || "")) return json({ error: "bad dispute" }, 400);
    const known = await env.DB.prepare("SELECT 1 FROM places WHERE place_id=?1").bind(body.place_id).first();
    if (!known) return json({ error: "unknown place" }, 404);
    const open = await env.DB.prepare("SELECT 1 FROM disputes WHERE place_id=?1 AND status='open'").bind(body.place_id).first();
    if (!open) await env.DB.prepare("INSERT INTO disputes (place_id, day) VALUES (?1, ?2)").bind(body.place_id, day).run();
  }
  return json({ ok: true });
}

export async function publicSummary(env, day = nycDay()) {
  const r = RULES;
  const places = await env.DB.prepare(PLACES_SQL)
    .bind(day, r.window_days, r.min_devices_place, r.min_refused_place, r.min_refused_share).all();
  const areas = await env.DB.prepare(AREAS_SQL).bind(day, r.window_days, r.min_area_reports, r.min_area_devices).all();
  const conf = await env.DB.prepare(CONFIRM_SQL).bind(day, r.confirm_window_days, r.min_closed_votes).all();
  const listed = places.results.filter((p) => !p.disputed);
  return {
    as_of: day,
    window_days: r.window_days,
    rule: {
      min_devices_place: r.min_devices_place, min_refused_place: r.min_refused_place,
      min_refused_share: r.min_refused_share, min_area_reports: r.min_area_reports,
      min_area_devices: r.min_area_devices,
    },
    places: listed.map(({ disputed, ...p }) => p),
    withheld_contested: places.results.length - listed.length,
    areas: areas.results.map((a) => ({ ...a, refused_share: Math.round((a.refused / a.decided) * 100) / 100 })),
    confirmations: conf.results,
  };
}

async function purge(env) {
  const day = nycDay();
  await env.DB.prepare("DELETE FROM reports WHERE day <= date(?1, '-' || ?2 || ' days')").bind(day, RULES.window_days).run();
  await env.DB.prepare("DELETE FROM confirmations WHERE day <= date(?1, '-' || ?2 || ' days')").bind(day, RULES.confirm_window_days).run();
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return cors(env, new Response(null, { status: 204 }));
    try {
      if (req.method === "GET" && url.pathname === "/v1/public") {
        return cors(env, json(await publicSummary(env), 200, { "Cache-Control": "public, max-age=300" }));
      }
      if (req.method === "POST" && url.pathname === "/v1/report") return cors(env, await handleWrite(env, req, "report"));
      if (req.method === "POST" && url.pathname === "/v1/confirm") return cors(env, await handleWrite(env, req, "confirm"));
      if (req.method === "POST" && url.pathname === "/v1/dispute") return cors(env, await handleWrite(env, req, "dispute"));
      return cors(env, json({ error: "not found" }, 404));
    } catch (e) {
      return cors(env, json({ error: "server error" }, 500));
    }
  },
  async scheduled(_event, env) {
    await purge(env);
  },
};
