-- D1 (SQLite) schema for nyc-restrooms reports and confirmations.
-- Raw tables are never exposed by the API; only sql/public_*.sql results are.

CREATE TABLE IF NOT EXISTS places (            -- seeded from the project's places table
  place_id TEXT PRIMARY KEY,
  name     TEXT,
  lat      REAL NOT NULL,
  lon      REAL NOT NULL,
  cell7    TEXT NOT NULL                       -- H3 resolution-7 cell, for area rollups
);

CREATE TABLE IF NOT EXISTS reports (           -- delivery-worker restroom access reports
  id       INTEGER PRIMARY KEY AUTOINCREMENT,  -- submission order (tie-break)
  place_id TEXT NOT NULL REFERENCES places(place_id),
  outcome  TEXT NOT NULL CHECK (outcome IN ('let_in','refused','kitchen_exception','no_restroom')),
  device   TEXT NOT NULL,                      -- HMAC of the browser's random token
  iphash   TEXT NOT NULL,                      -- HMAC of the network address, truncated
  day      TEXT NOT NULL                       -- YYYY-MM-DD (no time of day stored)
);
CREATE INDEX IF NOT EXISTS reports_place ON reports(place_id, day);
CREATE INDEX IF NOT EXISTS reports_ip_day ON reports(iphash, day);

CREATE TABLE IF NOT EXISTS confirmations (     -- public restroom status confirmations
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  restroom_id TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('open','closed','needs_code','clean','dirty')),
  device      TEXT NOT NULL,
  iphash      TEXT NOT NULL,
  day         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conf_restroom ON confirmations(restroom_id, day);
CREATE INDEX IF NOT EXISTS conf_ip_day ON confirmations(iphash, day);

CREATE TABLE IF NOT EXISTS disputes (          -- a business disputing listed reports
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  place_id TEXT NOT NULL REFERENCES places(place_id),
  status   TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','upheld','rejected')),
  day      TEXT NOT NULL
  -- no contact details stored here; reviewers follow up through the project's channel
);
