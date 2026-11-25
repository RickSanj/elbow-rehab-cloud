# Task: Backend v2 — per-packet ingestion, session model, async processing

Audience: an AI coding agent working in this repository.
Repo: `elbow-rehab-cloud` (FastAPI, Python 3.11, Cloud Run `elbow-rehab-service`, region `europe-central2`, BigQuery + Cloud SQL PostgreSQL + Firebase Auth).
Legend: ⚠️ = high risk / do not skip, ❓ = open decision (ask the user, do not guess), P0/P1/P2 = priority.
Companion doc: `AGENT_TASK_ios_v2.md` (the iOS app is rebuilt against the same contract in parallel).

---

## 0. Before you start

- ⚠️ The repo lives in an iCloud-synced Desktop folder. Many files are "dataless" (reads fail with `Resource deadlock avoided`). If a read fails, ask the user to download the folder ("Keep Downloaded" in Finder) or move the repo out of iCloud. Do not treat a failed read as an empty file. Note: `cloud_sql_operations.py`, `services/auth.py`, `services/rehab_workflow.py` are really 0 bytes.
- ⚠️ Git state is unknown (the `.git` folder is not readable). Make sure the working tree is committed before changes. If not, stop and ask the user.
- ⚠️ Never open, print, copy or commit `config/credentials.json` or `.env`.
- ⚠️ Do not deploy. Do not run anything against the real GCP project (BigQuery, Cloud SQL, Firebase). Unit tests must use fakes. Give the user the deploy and migration commands; the user runs them.
- One commit per step of section 7. Each commit: `pytest` green, `ruff` clean.

---

## 1. Context

Two ESP32 boards (sensor A = upper arm, sensor B = forearm) stream IMU packets at 100 Hz over BLE to an iPhone. Each packet has `device_ts_us` (board clock, µs) and `seq` (+1 per packet, restarts at 0 on board reboot; ⚠️ treat as uint32, no wrap handling).

The phone stamps every packet with `phone_rx_s` (phone monotonic clock, seconds) and uploads 10 s batches. The phone does **not** pair A and B and does **not** compute angles.

The backend must:
1. store every raw packet unchanged,
2. keep session metadata and events (start, zero pose, stop, pain),
3. after Stop, process the session asynchronously: align the two clocks, compute angles with the existing alignment-free estimator, compute metrics and data-quality figures,
4. be the source of truth for packet loss.

---

## 2. Problems in the current code

### 2.1 Bugs that break the current system (fix even before v2) — P0

| # | Where | Problem | Effect |
|---|---|---|---|
| 1 | `src/main.py` L28–29 | ⚠️ `StaticFiles` is mounted at `"/"` **before** the API routers. Starlette matches routes in order; a mount at `/` matches every path. | All API routes are shadowed. `POST /imu/...` gets 405 from StaticFiles. |
| 2 | `src/main.py` L28–29 | ⚠️ Paths `app/web/auth` and `app/web` are relative to cwd `/app` → `/app/app/web/...`, which does not exist. `StaticFiles` raises at import. | Container with this `main.py` does not start. ❓ The deployed revision is probably older than this file. Ask the user to check (see 8). |
| 3 | `cloud_sql_client.load_report` L105 | ⚠️ `engine.connect()` without `commit()`. In SQLAlchemy 2.0 the transaction is rolled back on close. | Session reports are **never saved**. |
| 4 | `bigquery_operations.load_calculated_angles` L59–64 | ⚠️ `to_gbq(..., if_exists="replace")`. | Every processed session **deletes the angles of all other sessions**. |
| 5 | `api/sessions.calculate_angles` + `ElbowTracker` | ⚠️ `ElbowTracker.zero_pose_timestamp_iso` is never set; the zero pose stored in Cloud SQL is never read. Also the comparison uses `session_time_iso`, which is the same value for every row. | The zero pose is **never applied**. FE/PS offsets are wrong. Thesis results depend on this. |
| 6 | `bigquery_operations` L24–42 | ⚠️ SQL built with f-string from `session_id`, which contains client-supplied `session_time_iso`. | SQL injection. |
| 7 | `api/patients.generate_invite_link` | ⚠️ No authentication. Anyone can create an invite for any `patient_id` and then sign up as that patient's doctor. | Access to patient data by anyone. |
| 8 | `api/sessions.ingest_imu_readings` vs iOS app | ⚠️ Model requires `esp32_ms_A/B`; the current iOS code sends `device_ts_us_A/B` and `seq_A/B`. | Every upload from the current app gets 422; the app ignores the status, so data is lost silently. v2 replaces this path. |
| 9 | `api/sessions.ingest_pain_data` | Full angle processing runs inside the pain request (Python loop per row, plots, file writes). Retried request → report inserted twice. | Slow, can time out, duplicate reports. |
| 10 | `api/sessions` L117–126 | Axis sign flip ("z axis is swapped") is applied at ingestion. | The "raw" table is not raw. The transform cannot be changed for old data. |
| 11 | `bigquery_client.get_bq_client` L18–20 | `bigquery.Client(project=get_table_id())` — passes `project.dataset.table` as project. | Wrong project string. |
| 12 | `analytics/session_report.get_sesion_duration` | Duration = max ingestion time − session start. | Includes upload delay; extra BigQuery query. |
| 13 | `calibration.py` | Gyro/acc bias uses the first N samples, assumes rest at session start. | Wrong bias if the patient moves at start. Plan: rest window around the zero pose. |
| 14 | Filters (`get_filter`) | Fixed `frequency=sample_rate`; dt is constant. | Jitter and lost packets are ignored; time integration is wrong across gaps. |

### 2.2 Security and operations — P1

- `config/credentials.json` is not in `.dockerignore` → service-account key is baked into the image. Use Cloud Run's service account (ADC): `firebase_admin.initialize_app()` without a key file.
- `DB_PASS` is a plain env var. Move to Secret Manager (`--set-secrets`).
- `cloudbuild.yaml` and `deploy-cloud-run.sh` deploy a different service (`elbow-rehab-api`, `us-central1`, 512 Mi). Only `deploy.sh` matches production. ❓ Ask the user, then delete or fix the other two.
- `requirements.txt` mixes runtime and dev tools (pytest, black, ruff, matplotlib). Split into `requirements.txt` and `requirements-dev.txt`.
- Dockerfile: 4 gunicorn workers on 1 Gi with numpy/scipy/pandas → memory risk. Use 2 workers for the API service. `HEALTHCHECK` is ignored by Cloud Run; remove it.
- `logger.exception("... {exc}")` without `f` in `cloud_sql_client.py` (cosmetic).
- `/ping` uses pyrebase `get_account_info`; fine, low priority.

### 2.3 Tests — P1

- `test_imu_readings_ingestion.py` calls a real server on `localhost:8080` and expects 200 (endpoint returns 201).
- `test_imu_readings_model.py` expects `session_id` to be derived by the model (it is not) → fails.
- `test_bq.py` queries real BigQuery; it is a script, not a test.
- Keep `test_session_processing.py`, `test_angle_wrapping.py`, `test_rotation_utils.py`, filter tests.

---

## 3. Data contract v2

Same contract as the iOS task. Put the Pydantic models in `src/models/contract_v2.py`.

Base URL: `https://elbow-rehab-service-1086744305186.europe-central2.run.app`

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/imu/v2/sessions` | SessionStart | 201 (200 if same session already exists for this user) |
| POST | `/imu/v2/packets` | PacketBatch | 201 |
| POST | `/imu/v2/sessions/{session_id}/events` | SessionEvent (`zero_pose` or `stop`) | 201 |
| POST | `/imu/v2/sessions/{session_id}/pain` | PainReport | 201 |
| GET | `/imu/v2/sessions/{session_id}` | — | 200: status, quality, metrics |

```json
// SessionStart
{"session_id": "uuid", "wall_iso": "2026-10-16T15:00:14.583Z", "uptime_s": 5230.991,
 "sensors": {"A": "ESP32-IMU A", "B": "ESP32-IMU B"}, "app_version": "1.2.0"}

// PacketBatch
{"schema_version": 2, "session_id": "uuid", "batch_id": "uuid",
 "packets": [{"role": "A", "seq": 177911, "device_ts_us": 1780475045, "phone_rx_s": 5231.023412,
              "ax": 0.455, "ay": 0.559, "az": -10.176, "gx": -0.254, "gy": 0.093, "gz": -0.023}]}

// SessionEvent
{"session_id": "uuid", "type": "zero_pose", "uptime_s": 5241.507, "wall_iso": "..."}
{"session_id": "uuid", "type": "stop", "uptime_s": 5930.002, "wall_iso": "...",
 "stats": {"A": {"received": 0, "lost_ble": 0, "duplicates": 0, "resets": 0, "malformed": 0, "dropped_overflow": 0},
           "B": {"received": 0, "lost_ble": 0, "duplicates": 0, "resets": 0, "malformed": 0, "dropped_overflow": 0}}}

// PainReport
{"session_id": "uuid", "pain_level": 4, "uptime_s": 5932.110, "wall_iso": "..."}
```

Validation (return 422 on failure):
- `session_id`, `batch_id`: UUID. `role` ∈ {A, B}. `seq ≥ 0`. `device_ts_us ≥ 0`.
- All floats finite (`ConfigDict(allow_inf_nan=False)`).
- `packets`: 1…5000 items. `pain_level`: int 0–10. `type` ∈ {`zero_pose`, `stop`}.
- `stats` optional (older app builds). Unknown fields: ignore.
- ⚠️ `user_id` comes only from the verified Firebase token, never from the body.
- Gzip request bodies: **not supported** (FastAPI does not decompress requests). Do not add it.

Phone clock: `phone_rx_s` and `uptime_s` are from `CLOCK_MONOTONIC` (continues during sleep). `(wall_iso, uptime_s)` in SessionStart is the anchor: `wall_time = wall_iso + (t − uptime_s)`.

---

## 4. Storage

### 4.1 Decision: where session metadata lives
Recommended (confirm with the user ❓): **Cloud SQL** for sessions, events, reports (small, transactional, needed for ownership checks on every request). **BigQuery** for raw packets and per-sample processed data.

### 4.2 Cloud SQL (PostgreSQL) — new migration file `sql/postgres/002_sessions_v2.sql`
The existing `sessions` table (`session_id, patient_id, started_at, zero_pose_at`) is v1. Create v2 tables; do not alter v1 rows.

```sql
sessions_v2(
  session_id UUID PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  wall_anchor TIMESTAMPTZ NOT NULL, uptime_anchor_s DOUBLE PRECISION NOT NULL,
  sensors JSONB NOT NULL, app_version TEXT,
  status TEXT NOT NULL CHECK (status IN ('active','stopped','processing','done','failed')),
  stopped_uptime_s DOUBLE PRECISION, app_stats JSONB,
  processing_attempts INT NOT NULL DEFAULT 0, processing_error TEXT,
  algorithm_version TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())
session_events_v2(
  session_id UUID REFERENCES sessions_v2, type TEXT CHECK (type IN ('zero_pose','stop')),
  uptime_s DOUBLE PRECISION NOT NULL, wall_iso TIMESTAMPTZ NOT NULL, received_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (session_id, type, uptime_s))
reports_v2(
  session_id UUID PRIMARY KEY REFERENCES sessions_v2,
  duration_s, max_flexion, max_extension, max_pronation, max_supination DOUBLE PRECISION,
  rep_count INT, smoothness DOUBLE PRECISION, pain_level INT,
  quality JSONB, quality_ok BOOLEAN, algorithm_version TEXT, computed_at TIMESTAMPTZ)
```
- ⚠️ Use `engine.begin()` for every write.
- ❓ Multiple zero poses in one session: use the **last** one before the first real movement? Ask the user. Default: last `zero_pose` event.

### 4.3 BigQuery — DDL in `sql/bigquery/`
- `raw_imu_packets`: `user_id STRING, session_id STRING, role STRING, seq INT64, device_ts_us INT64, phone_rx_s FLOAT64, ax, ay, az, gx, gy, gz FLOAT64, batch_id STRING, schema_version INT64, ingested_at TIMESTAMP`. Partition `DATE(ingested_at)`, cluster `user_id, session_id, role`. Append-only.
- `angles_v2`: `session_id, t_s FLOAT64, fe_deg, ps_deg FLOAT64, valid BOOL, algorithm_version STRING, computed_at TIMESTAMP`. Partition by `DATE(computed_at)`, cluster by `session_id`.
- ⚠️ Write per session: `DELETE WHERE session_id = @id` then insert (or load into a temp table + `MERGE`). Never `if_exists="replace"`.
- Ingestion uses `insert_rows_json(..., row_ids=[f"{session_id}:{role}:{seq}:{device_ts_us}"])` (best-effort dedup for retries).
- ⚠️ Processing always deduplicates: `QUALIFY ROW_NUMBER() OVER (PARTITION BY session_id, role, seq, device_ts_us ORDER BY ingested_at) = 1`. Including `device_ts_us` keeps packets from before and after a board reboot (same `seq`, different time).
- All queries use query parameters (`@session_id`), never f-strings.
- Old table (v1 paired rows): leave it. Do not migrate. v2 code never reads it.

---

## 5. Requirements

### 5.1 Fix P0 bugs from 2.1 (#1–#7, #11) — P0
- [ ] `main.py`: include routers first; mount static files last, at absolute paths built from `ROOT_DIR`; ❓ or remove the static mounts if the web pages are hosted elsewhere (ask).
- [ ] `load_report`: `engine.begin()`. Add `UNIQUE(session_id)` / upsert.
- [ ] Angles: per-session delete + insert.
- [ ] Parameterized BigQuery queries.
- [ ] Invite endpoint: require auth; `user_id` must equal `patient_id`, else 403.
- [ ] BigQuery client: `bigquery.Client(project=PROJECT_ID)`.
- [ ] v1 zero pose (#5) is not fixed in v1; v2 handles zero pose correctly (5.5). Tell the user that existing v1 results were computed without zero pose.

### 5.2 API v2 — P0
- [ ] Router `src/api/v2/` with the endpoints in section 3.
- [ ] Every endpoint with `{session_id}` or a body `session_id`: load the session, 404 if missing, 403 if `patient_id != user_id`.
- [ ] SessionStart: create patient if missing; insert session `active`. Same `session_id` + same user again → 200 (idempotent). Same `session_id` + other user → 409.
- [ ] Packets: session must exist (else 409, the app retries later). Accept in any status (late packets are fine; processing can be re-run). Only validate and write raw rows. No transforms, no processing in the request.
- [ ] Event `zero_pose`: insert (idempotent by PK). Allowed while `active`; else 409.
- [ ] Event `stop`: idempotent. First stop: save `stopped_uptime_s`, `app_stats`, status `stopped`, enqueue processing. Second stop: 200, no new task.
- [ ] Pain: upsert `reports_v2.pain_level` (row may not exist yet → create it with only pain). Never triggers processing.
- [ ] GET session: status, `quality`, metrics, pain.

### 5.3 Processing trigger — P0
- [ ] ⚠️ Do not use FastAPI `BackgroundTasks`: Cloud Run throttles CPU after the response.
- [ ] Default: **Cloud Tasks** queue → `POST /internal/v2/process/{session_id}` on the same service, OIDC-authenticated (verify the token audience and the Cloud Tasks service account; reject everything else with 403). Dispatch deadline 30 min.
- [ ] ❓ Alternative: Cloud Run Job. Ask the user if a session can take longer than 30 min to process.
- [ ] Readiness check at start: compare stored packet count per role with `app_stats[role].received − dropped_overflow`. If fewer and attempts < 5 → return 503 (Cloud Tasks retries with backoff). After 5 attempts → process what exists and mark quality.
- [ ] Idempotent: re-running for a session replaces its `angles_v2` rows and `reports_v2` metrics (keeps `pain_level`). Store `algorithm_version` (git SHA or constant).
- [ ] Status: `stopped → processing → done | failed` (+ `processing_error`).
- [ ] Add a CLI `python -m src.jobs.process_session <session_id>` that runs the same function (for re-processing old sessions and for the thesis experiments).

### 5.4 Processing pipeline (`src/processing/`) — P0
Pure functions on DataFrames; I/O only at the edges.

1. [ ] Load raw packets (parameterized query, dedup with `QUALIFY`), split by role, sort by `(segment, seq)`.
2. [ ] Segments and gaps: a new segment starts when `seq` or `device_ts_us` decreases (board reboot). Inside a segment, gap where `seq` jumps by >1. Store gap list and `lost_total` per role.
3. [ ] ⚠️ Clock fit per sensor and segment: `phone_rx_s ≈ a + b·device_s`. Per 2 s window take the packet with minimum `phone_rx_s − device_s` (least BLE delay), robust linear fit (e.g. Theil–Sen or Huber) → offset + drift. Guards: ≥ 10 windows, else offset-only with flag. Store residual (ms) and drift (ppm).
4. [ ] Map every packet to phone time `t = a + b·device_s`; convert to session time `t − uptime_anchor_s`.
5. [ ] ⚠️ Bias: gyro mean (and acc check) over a rest window around the zero-pose event: take 2–3 s inside [zero_pose − 3 s, zero_pose + 3 s] with the lowest gyro variance. If no zero pose: lowest-variance 2 s window in the first 30 s; flag `bias_from_zero_pose=false`.
6. [ ] Fusion per sensor with **per-sample dt** from `device_ts_us` (reuse EKF/Madgwick/Mahony; add a `dt` argument to `update`). Do not integrate across a gap: reset or re-initialize from accelerometer after a gap > 50 ms, and mark samples.
7. [ ] Resample both quaternion streams onto one 100 Hz grid over the time overlap of A and B (SLERP). Grid points inside a gap of either sensor → `valid=false`, no interpolation across gaps.
8. [ ] Zero pose: map the event `uptime_s` to session time; call `estimator.set_zero_pose(R_A, R_B)` at the first grid point ≥ that time.
9. [ ] Angles: run `AlignmentFreeElbowEstimator` on valid grid points (reuse the existing class; remove `print`, plots and file writes from the service path: `persist=False, visualize=False`).
10. [ ] Metrics on valid points: duration (from grid time, not ingestion time), max FE/PS, reps (reuse `get_reps_count` with `t_s` instead of `esp32_ms_A`), smoothness (❓ ask the user which metric: SPARC or log dimensionless jerk; default SPARC).
11. [ ] Quality per sensor: effective rate, jitter (std of Δdevice_ts), `lost_total`, `lost_ble` (from app stats), `lost_upload = lost_total − lost_ble`, resets, drift ppm, clock-fit residual, overlap duration, % valid grid points. `quality_ok = false` if loss > 2 %, overlap < 90 % of session, or fit residual > 5 ms (thresholds in `settings.py`; ❓ confirm with the user).
12. [ ] Axis convention: apply the board-mounting sign transform (currently `ax, ay, gx, gy *= -1`) **here**, as one named, documented function, not at ingestion.

### 5.5 Security and config — P1
- [ ] Firebase Admin via ADC on Cloud Run; local dev via `GOOGLE_APPLICATION_CREDENTIALS`. Add `config/` key files to `.dockerignore`.
- [ ] `DB_PASS` from Secret Manager in `deploy.sh`.
- [ ] All config in one `src/config.py` (pydantic-settings), read once.

### 5.6 Cleanup — P2
- [ ] Remove empty files (`cloud_sql_operations.py`, `services/auth.py`, `services/rehab_workflow.py`) or fill them as the new repository layer.
- [ ] Split requirements; matplotlib only in dev/analytics.
- [ ] Dockerfile: 2 workers, no HEALTHCHECK, `--timeout` ≥ 1800 for the internal processing route.
- [ ] Fix or delete `cloudbuild.yaml` / `deploy-cloud-run.sh` (❓ ask).

---

## 6. Tests (pytest, no network)

- Fakes: in-memory repositories for Cloud SQL and BigQuery behind small interfaces; `app.dependency_overrides` for auth.
- [ ] Contract: valid batch; `nan`; role `C`; negative `seq`; 5001 packets; missing `stats` accepted.
- [ ] Auth: other user's session → 403; no token → 401/403; invite for another patient → 403.
- [ ] Idempotency: start ×2; stop ×2 → one task; same batch ×2 → processed output identical.
- [ ] ⚠️ Clock fit (synthetic): two clocks with known offset and drift (e.g. +40 ppm), BLE delay bursty (deliveries every ~30 ms, occasional 90 ms gaps, exponential jitter). Recovered offset within 1 ms, drift within 5 ppm.
- [ ] Gaps: remove a block of `seq` → those grid points `valid=false`, no interpolation across.
- [ ] Reboot: `seq` restarts at 0 mid-session → two segments, not counted as loss.
- [ ] Zero pose: synthetic session where the true angles at the zero-pose time are known → angles near 0 after the event.
- [ ] Readiness: fewer stored packets than app stats → 503 until attempt 5.
- [ ] Rewrite or delete the broken tests listed in 2.3.

---

## 7. Order of work (one commit each)

1. Test infrastructure (fakes, overrides) + fix broken tests.
2. P0 bug fixes (5.1).
3. Contract models + SQL/BigQuery DDL files + migration notes for the user.
4. v2 API endpoints with ownership and idempotency (5.2).
5. Processing pipeline as pure functions with tests (5.4 steps 1–7).
6. Zero pose, estimator integration, metrics, quality (5.4 steps 8–12).
7. Processing trigger: internal endpoint, Cloud Tasks enqueue, CLI (5.3).
8. Security/config (5.5) and cleanup (5.6). Update `README.md` with run, test, migrate and deploy steps.

## 8. Things only the user can do (list them in your final report)

- Check what is deployed now: `curl -s $BASE/openapi.json | python -m json.tool | grep '"/'`.
- Run the Cloud SQL migration and BigQuery DDL.
- Create the Cloud Tasks queue and give the service account `roles/cloudtasks.enqueuer` and `roles/run.invoker`.
- Create the Secret Manager secret for `DB_PASS`.
- Deploy.

## 9. Definition of done

- A session recorded by the v2 iOS app ends with `status = done`, rows in `angles_v2` for that session only, a `reports_v2` row with metrics, pain and quality.
- Re-running processing gives identical output.
- Processing a session never touches another session's rows.
- No API request does heavy computation. All tests pass without network.

## 10. Out of scope

iOS app, firmware, clinician dashboard UI (`web/`), migration of v1 data, changes to the estimator mathematics beyond the integration points above.
