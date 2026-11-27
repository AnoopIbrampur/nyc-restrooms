-- Places with enough independent refusal reports to list publicly.
-- ?1 today (YYYY-MM-DD) ?2 window days ?3 min devices ?4 min refused (devices AND ip hashes)
-- ?5 min refused share. Mirrors restrooms.reports.public_summary (parity-tested).
WITH win AS (
  SELECT id, place_id, outcome, device, iphash, day FROM reports
  WHERE day > date(?1, '-' || ?2 || ' days') AND day <= ?1
),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY device, place_id ORDER BY day DESC, id DESC) AS rn
  FROM win
),
votes AS (SELECT * FROM ranked WHERE rn = 1),
agg AS (
  SELECT place_id,
         COUNT(*)                                             AS reporters,
         SUM(outcome = 'refused')                             AS refused,
         SUM(outcome = 'let_in')                              AS let_in,
         SUM(outcome = 'kitchen_exception')                   AS kitchen_exception,
         COUNT(DISTINCT CASE WHEN outcome = 'refused' THEN iphash END) AS refused_ips,
         MIN(day) AS first, MAX(day) AS last
  FROM votes GROUP BY place_id
)
SELECT a.place_id, p.name, p.lat, p.lon, a.refused, a.let_in, a.kitchen_exception,
       a.reporters, a.first, a.last,
       EXISTS (SELECT 1 FROM disputes d WHERE d.place_id = a.place_id AND d.status = 'open') AS disputed
FROM agg a JOIN places p ON p.place_id = a.place_id
WHERE a.reporters >= ?3 AND a.refused >= ?4 AND a.refused_ips >= ?4
  AND a.refused * 1.0 / a.reporters >= ?5
ORDER BY a.refused DESC, a.place_id;
