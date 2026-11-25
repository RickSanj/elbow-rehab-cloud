-- 001: one v1 report per session (needed by the upsert in load_report).
--
-- Run once against the Cloud SQL database, for example:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/postgres/001_v1_reports_unique.sql
--
-- Before this fix load_report never committed, so `reports` is most likely
-- empty. If it is not, check for duplicates first:
--   SELECT session_id, count(*) FROM reports GROUP BY session_id HAVING count(*) > 1;
-- The DELETE below keeps one row per session_id (the physically last one).

BEGIN;

DELETE FROM reports a
USING reports b
WHERE a.session_id = b.session_id
  AND a.ctid < b.ctid;

CREATE UNIQUE INDEX IF NOT EXISTS reports_session_id_key ON reports (session_id);

COMMIT;
