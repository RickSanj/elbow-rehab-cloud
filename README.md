# elbow-rehab-cloud

FastAPI backend for the elbow rehabilitation thesis project. Two ESP32 IMU
boards (A = upper arm, B = forearm) stream 100 Hz packets over BLE to the
iPhone app, which uploads them in batches. The backend stores every raw packet
unchanged and, after a session is stopped, processes it asynchronously into
elbow angles (flexion/extension, pronation/supination), metrics and
data-quality figures.

Runs on Cloud Run (`elbow-rehab-service`, `europe-central2`) with BigQuery,
Cloud SQL (PostgreSQL), Firebase Auth and Cloud Tasks.

## How v2 works

```
iPhone app                         Cloud Run (this service)                   storage
----------                         ------------------------                   -------
POST /imu/v2/sessions        ->    create session (active)               ->   Cloud SQL sessions_v2
POST /imu/v2/packets (10 s)  ->    validate, append raw rows             ->   BigQuery raw_imu_packets
POST .../events zero_pose    ->    store event                           ->   Cloud SQL session_events_v2
POST .../events stop         ->    status stopped, enqueue Cloud Task
POST .../pain                ->    store pain level                      ->   Cloud SQL reports_v2
                                   Cloud Task -> POST /internal/v2/process/{id}
                                     wait until all packets are stored (503 + retry)
                                     dedup -> segments/gaps -> clock fit -> bias
                                     -> fusion (real dt) -> 100 Hz grid -> zero pose
                                     -> alignment-free estimator -> metrics, quality
                                                                         ->   BigQuery angles_v2
                                                                         ->   Cloud SQL reports_v2 (status done)
GET /imu/v2/sessions/{id}    <-    status, metrics, quality, pain
```

No API request does heavy computation. The `user_id` always comes from the
verified Firebase ID token, never from a request body.

### API v2

All endpoints need `Authorization: Bearer <Firebase ID token>`. Bodies are
described in `src/models/contract_v2.py` (shared with the iOS task).

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/imu/v2/sessions` | 201 created, 200 already exists (same user) | 409 session id used by another user, 422 |
| POST | `/imu/v2/packets` | 201 | 409 session not started yet (retry), 403 not your session, 422, 503 storage unavailable (retry) |
| POST | `/imu/v2/sessions/{id}/events` | zero_pose: 201 / 200 repeated; stop: 201 first / 200 repeated | 404, 403, 409 zero pose after stop, 422, 503 could not enqueue (retry stop) |
| POST | `/imu/v2/sessions/{id}/pain` | 201 | 404, 403, 422 |
| GET | `/imu/v2/sessions/{id}` | 200 `{status, metrics, quality, quality_ok, pain_level, ...}` | 404, 403 |

Session status: `active -> stopped -> processing -> done | failed`.
Requests without a token get 401/403. Validation errors return 422 without echoing the rejected input.

The v1 endpoints (`/imu/readings`, `/imu/zero-pose`, `/imu/pain`) are still
present for old app builds. v1 results were computed **without** the zero pose.

## Repository layout

```
src/
  main.py                 app, routers, static web pages (mounted last)
  config.py               all settings (pydantic-settings, env vars)
  api/v2/sessions.py      v2 ingestion API
  api/internal.py         Cloud Tasks processing endpoint (OIDC protected)
  api/{sessions,auth,patients}.py   v1 API, doctor auth, invite links
  models/contract_v2.py   data contract v2
  repositories/           Cloud SQL / BigQuery / Cloud Tasks implementations
  processing/             pure processing pipeline (see pipeline.py docstring)
  jobs/process_session.py processing service + CLI
  angle_calculation/      AHRS filters and the alignment-free estimator
  analytics/              local plots/analysis (matplotlib, dev only)
sql/postgres/, sql/bigquery/   DDL, applied by hand (docs/MIGRATIONS.md)
tests/                     pytest suite (no network), fakes, synthetic sessions
web/                       doctor login/signup pages
```

## Local development

Python 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### Tests and lint

```bash
pytest          # no network; GCP clients are blocked in tests
ruff check src tests
```

The Cloud SQL repository can also be checked against a **throwaway local**
PostgreSQL (the test drops and recreates the `public` schema; it refuses any
host other than localhost):

```bash
initdb -D /tmp/pgtest -U test --auth=trust
pg_ctl -D /tmp/pgtest -o "-p 54329 -c listen_addresses=localhost" -l /tmp/pgtest.log start
createdb -h localhost -p 54329 -U test rehab
PG_TEST_DSN=postgresql+pg8000://test@localhost:54329/rehab pytest tests/test_repository_contract.py
```

### Run the API locally

Running locally talks to the real GCP project configured in your environment.

```bash
export PROJECT_ID=... OUTPUT_DATASET=... LOCATION=europe-central2 INSTANCE_NAME=...
export DB_USER=... DB_PASS=... DB_NAME=...
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json   # local only; not used on Cloud Run
uvicorn src.main:app --reload --port 8080
```

### Re-process a session (CLI)

Runs the same code as the Cloud Tasks endpoint:

```bash
python -m src.jobs.process_session <session_id>            # process and store
python -m src.jobs.process_session <session_id> --force    # skip the "all packets uploaded" check
python -m src.jobs.process_session <session_id> --dry-run --out angles.csv   # thesis experiments: write nothing to GCP
```

Re-processing replaces only that session's rows in `angles_v2` and its metrics
in `reports_v2` (the pain level is kept). The result carries
`algorithm_version` (`ALGORITHM_VERSION` + git SHA).

## Configuration

All settings are read once from environment variables in `src/config.py`.

| Variable | Meaning |
|---|---|
| `PROJECT_ID`, `LOCATION` | GCP project, region (`europe-central2`) |
| `OUTPUT_DATASET` | BigQuery dataset |
| `RAW_PACKETS_TABLE`, `ANGLES_V2_TABLE` | v2 tables (default `raw_imu_packets`, `angles_v2`) |
| `IMU_READINGS_TABLE`, `CALCULATED_ANGLES_TABLE` | v1 tables |
| `INSTANCE_NAME`, `DB_USER`, `DB_NAME`, `DB_PASS` | Cloud SQL; on Cloud Run `DB_PASS` comes from Secret Manager |
| `PRIVATE_IP` | connect to Cloud SQL over private IP |
| `SERVICE_URL` | public URL of this service (invite links, Cloud Tasks target and OIDC audience) |
| `TASKS_QUEUE`, `TASKS_LOCATION` | Cloud Tasks queue (default `session-processing`, `LOCATION`) |
| `TASKS_SERVICE_ACCOUNT` | service account whose OIDC token the internal endpoint accepts |
| `TASKS_AUDIENCE` | OIDC audience (default `SERVICE_URL`) |
| `ALGORITHM_VERSION`, `GIT_SHA` | stored with every processed result |
| `FIREBASE_CRED` | optional key file path for local runs only |

Processing constants and the quality thresholds (loss <= 2 %, overlap >= 90 %,
clock residual <= 5 ms) are in `src/processing/settings.py`.

## Migrations

See [docs/MIGRATIONS.md](docs/MIGRATIONS.md). Run them before deploying v2.

## One-time GCP setup (run by hand)

```bash
PROJECT_ID=rehab-project-480112
REGION=europe-central2
SERVICE=elbow-rehab-service
RUNTIME_SA=$(gcloud run services describe $SERVICE --region=$REGION --format='value(spec.template.spec.serviceAccountName)')
# (empty -> the default compute service account: <project-number>-compute@developer.gserviceaccount.com)

# 1. DB password in Secret Manager
printf '%s' "<db password>" | gcloud secrets create db-pass --data-file=- --replication-policy=automatic
gcloud secrets add-iam-policy-binding db-pass \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor

# 2. Cloud Tasks queue and the service account that signs the task's OIDC token
gcloud tasks queues create session-processing --location=$REGION \
  --max-attempts=20 --min-backoff=30s --max-backoff=600s --max-concurrent-dispatches=2
gcloud iam service-accounts create tasks-invoker --display-name="Cloud Tasks -> elbow-rehab-service"
TASKS_SA=tasks-invoker@$PROJECT_ID.iam.gserviceaccount.com

# the service creates tasks ...
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/cloudtasks.enqueuer
# ... that carry an OIDC token for TASKS_SA (needs actAs on it)
gcloud iam service-accounts add-iam-policy-binding $TASKS_SA \
  --member="serviceAccount:$RUNTIME_SA" --role=roles/iam.serviceAccountUser
# TASKS_SA may invoke the service
gcloud run services add-iam-policy-binding $SERVICE --region=$REGION \
  --member="serviceAccount:$TASKS_SA" --role=roles/run.invoker

# 3. Remove the old plain env vars once (DB_PASS becomes a secret; key file no longer used)
gcloud run services update $SERVICE --region=$REGION \
  --remove-env-vars=DB_PASS,FIREBASE_CRED,OUTPUT_TABLE,INSTANCE_UNIX_SOCKET
```

Add to `.env`: `SERVICE_URL=https://elbow-rehab-service-1086744305186.europe-central2.run.app`,
`TASKS_SERVICE_ACCOUNT=tasks-invoker@<project>.iam.gserviceaccount.com` (and optionally
`DB_PASS_SECRET`, `TASKS_QUEUE`, `RAW_PACKETS_TABLE`, `ANGLES_V2_TABLE`).

## Deploy

```bash
./deploy.sh
```

It builds `europe-central2-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME:<git sha>`
and deploys it with 2 GiB memory, a 30 min request timeout (processing route),
`DB_PASS` from Secret Manager and the v2 env vars. The image contains no key
files (`.dockerignore`); Firebase Admin and BigQuery use the Cloud Run service
account.

Check what is deployed:

```bash
curl -s https://elbow-rehab-service-1086744305186.europe-central2.run.app/openapi.json \
  | python -m json.tool | grep '"/'
```
