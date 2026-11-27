# nyc-restrooms API (Cloudflare Worker + D1)

Stores delivery-worker restroom reports and restroom confirmations, and serves **only aggregated** results. The publishing rule lives in `sql/public_places.sql` (and `public_areas.sql`, `public_confirmations.sql`). It's parity-tested against the Python reference `src/restrooms/reports.py` on 300 random cases (`tests/test_sql_parity.py`).

**Status: local only. Not deployed.** Deploying needs the project owner's Cloudflare account and approval.

## Local development (no account needed)
```bash
cd backend
npm install                      # wrangler pinned in package.json
printf 'DEV="1"\nHMAC_KEY="local-dev-only"\n' > .dev.vars
uv run python -c "from restrooms.backend_seed import write_seed; write_seed()"   # from repo root
npm run db:local && npm run seed:local
npm run dev                      # http://localhost:8787
uv run python backend/smoke_test.py   # from repo root
npx wrangler d1 execute nyc-restrooms --local --command "DELETE FROM reports; DELETE FROM confirmations; DELETE FROM disputes;"
```

## What's stored
- `reports`: place id, outcome (let in / refused / through-kitchen / no restroom), keyed hash of the browser's random token, keyed and truncated hash of the network address, and the **date** (no time). Deleted after 180 days.
- `confirmations`: restroom id, kind (open / closed / needs code / clean / dirty), the same two hashes, and the date. Deleted after 90 days.
- `disputes`: place id, status, date. No contact details.
- No free text, names, emails or precise locations. Cloudflare itself logs requests (including IP addresses) under its own policy.

## Abuse resistance (not abuse-proof)
- Listing needs 3+ distinct device tokens **and** 3+ distinct network hashes reporting refusal, with refusals at least half of that place's reporters.
- Turnstile check on every write (fails closed outside local dev).
- At most 40 writes per network per day.
- A dispute withholds a listing until reviewed.
- One "closed" vote can't hide a restroom: it takes 3 independent votes.

## Deploying (owner only, after approval)
1. `npx wrangler login` (the owner signs in; credentials never pass through the project).
2. `npx wrangler d1 create nyc-restrooms`, then put the id in `wrangler.toml`.
3. `npx wrangler d1 execute nyc-restrooms --remote --file schema.sql`, then the same with `seed/places.sql`.
4. `npx wrangler secret put HMAC_KEY` (random) and `npx wrangler secret put TURNSTILE_SECRET` (needs a Turnstile site key for the Pages domain).
5. `npx wrangler deploy`, then set the API URL in the site's config to turn the buttons on (a separate decision).
