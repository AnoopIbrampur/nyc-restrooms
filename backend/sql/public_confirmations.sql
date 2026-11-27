-- Restroom status confirmations, last ?2 days. One vote per device per restroom (latest).
-- "closed" is published only with >= ?3 devices AND >= ?3 ip hashes saying closed, so one
-- person can never hide a restroom. ?1 today.
WITH win AS (
  SELECT id, restroom_id, kind, device, iphash, day FROM confirmations
  WHERE day > date(?1, '-' || ?2 || ' days') AND day <= ?1
),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY device, restroom_id ORDER BY day DESC, id DESC) AS rn
  FROM win
),
votes AS (SELECT * FROM ranked WHERE rn = 1)
SELECT restroom_id,
       SUM(kind = 'open')       AS open_n,
       MAX(CASE WHEN kind = 'open' THEN day END) AS last_open,
       CASE WHEN SUM(kind = 'closed') >= ?3
             AND COUNT(DISTINCT CASE WHEN kind = 'closed' THEN iphash END) >= ?3
            THEN SUM(kind = 'closed') ELSE 0 END AS closed_n,
       SUM(kind = 'needs_code') AS needs_code_n,
       SUM(kind = 'clean')      AS clean_n,
       SUM(kind = 'dirty')      AS dirty_n
FROM votes GROUP BY restroom_id
ORDER BY restroom_id;
