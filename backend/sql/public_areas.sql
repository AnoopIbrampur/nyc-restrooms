-- Area (H3 res-7) rollups. ?1 today ?2 window days ?3 min votes ?4 min devices (and ip hashes)
WITH win AS (
  SELECT r.id, r.place_id, r.outcome, r.device, r.iphash, r.day, p.cell7
  FROM reports r JOIN places p ON p.place_id = r.place_id
  WHERE r.day > date(?1, '-' || ?2 || ' days') AND r.day <= ?1
),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY device, place_id ORDER BY day DESC, id DESC) AS rn
  FROM win
),
votes AS (SELECT * FROM ranked WHERE rn = 1)
SELECT cell7 AS h3,
       COUNT(*) AS votes,
       SUM(outcome = 'refused') AS refused,
       SUM(outcome IN ('refused','let_in')) AS decided
FROM votes GROUP BY cell7
HAVING COUNT(*) >= ?3 AND COUNT(DISTINCT device) >= ?4 AND COUNT(DISTINCT iphash) >= ?4
   AND SUM(outcome IN ('refused','let_in')) > 0
ORDER BY cell7;
