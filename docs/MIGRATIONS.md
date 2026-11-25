# Migrations (run by hand, in order)

The service never changes schemas itself. Run these once per environment,
**before** deploying the v2 code. All steps are additive; v1 tables and rows
are left as they are.

## Cloud SQL (PostgreSQL)

Connect through the Cloud SQL Auth Proxy (or Cloud Shell) and run:

```bash
# 1. v1 fix: one report per session (needed by the load_report upsert)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/postgres/001_v1_reports_unique.sql

# 2. v2 session model: sessions_v2, session_events_v2, reports_v2
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/postgres/002_sessions_v2.sql
```

`001` deletes duplicate v1 report rows if there are any. Run the `SELECT` in
the file's header first to see whether that affects anything.

`002` needs the existing `patients(patient_id)` table (it is the foreign key
target of `sessions_v2.patient_id`).

## BigQuery

The DDL files use the placeholder `PROJECT_ID.DATASET`. Substitute your values
and run them with the `bq` CLI:

```bash
export PROJECT_ID=rehab-project-480112
export DATASET=<your OUTPUT_DATASET>

for f in sql/bigquery/001_raw_imu_packets.sql sql/bigquery/002_angles_v2.sql; do
  sed "s/PROJECT_ID\.DATASET/${PROJECT_ID}.${DATASET}/g" "$f" \
    | bq query --project_id="$PROJECT_ID" --use_legacy_sql=false
done
```

The v1 tables (`IMU_READINGS_TABLE`, `CALCULATED_ANGLES_TABLE`) are not
migrated. v2 code never reads them.

## After the migrations

* Session metadata lives in Cloud SQL (`sessions_v2`, `session_events_v2`,
  `reports_v2`).
* Raw packets live in BigQuery `raw_imu_packets`. Processed per-sample angles
  live in `angles_v2`.
* Existing v1 results were computed **without** the zero pose (the stored zero
  pose was never read, see task bug #5). Re-record sessions with the v2 app if
  zeroed angles are needed.
