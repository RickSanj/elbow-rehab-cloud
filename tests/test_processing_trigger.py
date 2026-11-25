"""Processing trigger: OIDC-protected internal endpoint, readiness, CLI, Cloud Tasks."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.api.v2.dependencies import get_metadata_repo, get_packet_store, get_task_queue
from tests.conftest import TEST_SERVICE_URL, TEST_TASKS_SA
from tests.fakes import InMemoryMetadataRepository, InMemoryPacketStore, RecordingTaskQueue
from tests.synthetic import ANCHOR_UPTIME_S, constant, simulate_session, static_upper_arm

WALL = "2026-10-16T15:00:14.583Z"
GOOD_TOKEN = "Bearer good-token"


def fe_profile(t):
    t = np.asarray(t, dtype=float)
    return np.where((t >= 8) & (t < 14), 50.0, 60 + 40 * np.sin(2 * np.pi * 0.3 * t))


@pytest.fixture(scope="module")
def recording():
    return simulate_session(25.0, fe_profile, constant(10.0), upper_arm=static_upper_arm)


@pytest.fixture
def env(app, login_as, monkeypatch):
    import src.api.internal as internal

    seen = {}

    def fake_verify(token, _request, audience=None):
        seen["audience"] = audience
        if token == "good-token":
            return {"email": TEST_TASKS_SA, "email_verified": True}
        if token == "other-sa":
            return {"email": "someone@else.iam.gserviceaccount.com", "email_verified": True}
        if token == "unverified":
            return {"email": TEST_TASKS_SA, "email_verified": False}
        raise ValueError("Token has wrong audience")

    monkeypatch.setattr(internal.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(internal, "_google_transport", lambda: object())

    e = SimpleNamespace(
        repo=InMemoryMetadataRepository(), store=InMemoryPacketStore(), queue=RecordingTaskQueue(), seen=seen
    )
    app.dependency_overrides[get_metadata_repo] = lambda: e.repo
    app.dependency_overrides[get_packet_store] = lambda: e.store
    app.dependency_overrides[get_task_queue] = lambda: e.queue
    login_as("patient-1")
    return e


def packet_dicts(df: pd.DataFrame) -> list[dict]:
    cols = ["role", "seq", "device_ts_us", "phone_rx_s", "ax", "ay", "az", "gx", "gy", "gz"]
    records = df[cols].to_dict(orient="records")
    for r in records:
        r["seq"], r["device_ts_us"] = int(r["seq"]), int(r["device_ts_us"])
    return records


def record_session(client, recording, *, send_twice=False, stats_extra=0, skip_rows=0):
    sid = uuid.uuid4()
    start = {
        "session_id": str(sid),
        "wall_iso": WALL,
        "uptime_s": ANCHOR_UPTIME_S,
        "sensors": {"A": "ESP32-IMU A", "B": "ESP32-IMU B"},
        "app_version": "2.0.0",
    }
    assert client.post("/imu/v2/sessions", json=start).status_code == 201
    zero_pose = {"session_id": str(sid), "type": "zero_pose", "uptime_s": ANCHOR_UPTIME_S + 11.0, "wall_iso": WALL}
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=zero_pose).status_code == 201

    packets = recording.packets.sort_values("phone_rx_s")
    uploaded = packets.iloc[: len(packets) - skip_rows] if skip_rows else packets
    for start_row in range(0, len(uploaded), 2000):
        batch = {
            "schema_version": 2,
            "session_id": str(sid),
            "batch_id": str(uuid.uuid4()),
            "packets": packet_dicts(uploaded.iloc[start_row : start_row + 2000]),
        }
        assert client.post("/imu/v2/packets", json=batch).status_code == 201
        if send_twice:
            assert client.post("/imu/v2/packets", json=batch).status_code == 201

    counts = packets.groupby("role").size()
    stats = {
        role: {"received": int(counts[role]) + stats_extra, "lost_ble": 0, "duplicates": 0, "resets": 0,
               "malformed": 0, "dropped_overflow": 0}
        for role in ("A", "B")
    }
    stop = {"session_id": str(sid), "type": "stop", "uptime_s": ANCHOR_UPTIME_S + 25.0, "wall_iso": WALL, "stats": stats}
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=stop).status_code == 201
    pain = {"session_id": str(sid), "pain_level": 3, "uptime_s": ANCHOR_UPTIME_S + 26.0, "wall_iso": WALL}
    assert client.post(f"/imu/v2/sessions/{sid}/pain", json=pain).status_code == 201
    return sid


def trigger(client, sid, token=GOOD_TOKEN):
    headers = {"Authorization": token} if token else {}
    return client.post(f"/internal/v2/process/{sid}", headers=headers)


# -------------------------------------------------------------------- auth


@pytest.mark.parametrize("token", [None, "Basic abc", "Bearer wrong-audience", "Bearer other-sa", "Bearer unverified"])
def test_internal_endpoint_rejects_everything_but_the_tasks_identity(client, env, token):
    sid = uuid.uuid4()
    assert trigger(client, sid, token=token).status_code == 403


def test_internal_endpoint_checks_the_configured_audience(client, env):
    trigger(client, uuid.uuid4())
    assert env.seen["audience"] == TEST_SERVICE_URL


def test_firebase_user_token_cannot_trigger_processing(client, env, recording):
    sid = record_session(client, recording)
    # A patient's Firebase token is not a Google OIDC token for the tasks SA.
    assert trigger(client, sid, token="Bearer firebase-id-token-of-patient").status_code == 403
    assert env.repo.get_session(sid).status == "stopped"


# ------------------------------------------------------------- end to end


def test_stop_then_process_end_to_end(client, env, recording):
    other = record_session(client, recording)
    env.store.angles[str(other)] = pd.DataFrame({"t_s": [0.0], "sentinel": [True]})

    sid = record_session(client, recording)
    assert env.queue.enqueued == [other, sid]

    response = trigger(client, sid)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "done"

    body = client.get(f"/imu/v2/sessions/{sid}").json()
    assert body["status"] == "done"
    assert body["pain_level"] == 3
    assert body["metrics"]["duration_s"] == pytest.approx(24.7, abs=0.05)
    assert body["quality_ok"] is True, body["quality"]["reasons"]
    assert body["quality"]["zero_pose"]["applied"]
    assert body["algorithm_version"] == "test-algo"

    angles = env.store.angles[str(sid)]
    assert len(angles) == pytest.approx(2470, abs=2)
    assert (angles["session_id"] == str(sid)).all()
    assert "sentinel" in env.store.angles[str(other)]  # other session untouched


def test_reprocessing_gives_identical_output_and_keeps_pain(client, env, recording):
    sid = record_session(client, recording)
    trigger(client, sid)
    first = env.store.angles[str(sid)].drop(columns="computed_at")
    first_report = env.repo.get_report(sid)

    assert trigger(client, sid).status_code == 200
    second = env.store.angles[str(sid)].drop(columns="computed_at")
    pd.testing.assert_frame_equal(first, second)
    report = env.repo.get_report(sid)
    assert report.pain_level == 3

    def without_attempts(quality):
        return {k: v for k, v in quality.items() if k != "readiness"}

    assert (report.rep_count, report.max_flexion, without_attempts(report.quality)) == (
        first_report.rep_count,
        first_report.max_flexion,
        without_attempts(first_report.quality),
    )
    assert report.quality["readiness"]["attempts"] == 2


def test_same_batches_twice_give_identical_output(client, env, recording):
    once = record_session(client, recording)
    twice = record_session(client, recording, send_twice=True)
    trigger(client, once)
    trigger(client, twice)

    a = env.store.angles[str(once)].drop(columns=["session_id", "computed_at"])
    b = env.store.angles[str(twice)].drop(columns=["session_id", "computed_at"])
    pd.testing.assert_frame_equal(a, b)
    qa, qb = env.repo.get_report(once).quality, env.repo.get_report(twice).quality
    assert qa["sensors"]["A"]["received"] == qb["sensors"]["A"]["received"]


# --------------------------------------------------------------- readiness


def test_not_ready_returns_503_until_the_fifth_attempt(client, env, recording):
    sid = record_session(client, recording, stats_extra=40)

    for attempt in range(1, 5):
        response = trigger(client, sid)
        assert response.status_code == 503, attempt
        assert response.json()["missing"] == {"A": 40, "B": 40}
        assert env.repo.get_session(sid).status == "stopped"

    response = trigger(client, sid)
    assert response.status_code == 200
    report = env.repo.get_report(sid)
    assert report.quality_ok is False
    assert "incomplete_upload" in report.quality["reasons"]
    assert report.quality["readiness"]["attempts"] == 5


def test_ready_as_soon_as_all_packets_arrived(client, env, recording):
    sid = record_session(client, recording)
    assert trigger(client, sid).status_code == 200
    assert env.repo.get_session(sid).processing_attempts == 1


# ------------------------------------------------------- failures / leases


def test_processing_error_marks_failed_and_asks_for_retry(client, env, recording):
    sid = record_session(client, recording)

    def boom(*_args, **_kwargs):
        raise RuntimeError("BigQuery unavailable")

    env.store.load_packets = boom
    response = trigger(client, sid)
    assert response.status_code == 500
    session = env.repo.get_session(sid)
    assert session.status == "failed"
    assert "BigQuery unavailable" in session.processing_error
    assert client.get(f"/imu/v2/sessions/{sid}").json()["processing_error"] == session.processing_error


def test_concurrent_attempt_is_not_run_twice(client, env, recording):
    sid = record_session(client, recording)
    env.repo.claim_processing(sid, lease_s=3600)  # another attempt is running
    response = trigger(client, sid)
    assert response.status_code == 200
    assert response.json()["status"] == "busy"
    assert str(sid) not in env.store.angles


def test_active_session_is_not_processed(client, env):
    sid = uuid.uuid4()
    start = {"session_id": str(sid), "wall_iso": WALL, "uptime_s": 1.0, "sensors": {"A": "a", "B": "b"}}
    client.post("/imu/v2/sessions", json=start)
    assert trigger(client, sid).json()["status"] == "active"


# ---------------------------------------------------------------------- CLI


def test_cli_dry_run_writes_csv_and_nothing_else(client, env, recording, tmp_path, capsys):
    from src.jobs.process_session import main

    sid = record_session(client, recording, stats_extra=40)  # not "ready"
    out = tmp_path / "angles.csv"

    code = main([str(sid), "--force", "--dry-run", "--out", str(out)], repo=env.repo, store=env.store)

    assert code == 0
    assert '"status": "done"' in capsys.readouterr().out
    assert len(pd.read_csv(out)) == pytest.approx(2470, abs=2)
    assert env.repo.get_session(sid).status == "stopped"
    assert str(sid) not in env.store.angles


def test_cli_processes_and_stores(client, env, recording):
    from src.jobs.process_session import main

    sid = record_session(client, recording)
    assert main([str(sid)], repo=env.repo, store=env.store) == 0
    assert env.repo.get_session(sid).status == "done"


# ----------------------------------------------------------- Cloud Tasks


def test_cloud_tasks_payload(isolated_settings):
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2

    from src.repositories.tasks import CloudTasksQueue

    class FakeTasksClient:
        def __init__(self):
            self.created = []

        @staticmethod
        def queue_path(project, location, queue):
            return f"projects/{project}/locations/{location}/queues/{queue}"

        def create_task(self, parent, task):
            if any(t.name == task.name for _, t in self.created):
                raise AlreadyExists("exists")
            self.created.append((parent, task))

    fake = FakeTasksClient()
    queue = CloudTasksQueue(isolated_settings, client_factory=lambda: fake)
    sid = uuid.uuid4()
    queue.enqueue_processing(sid)
    queue.enqueue_processing(sid)  # duplicate is swallowed

    [(parent, task)] = fake.created
    assert parent == "projects/test-project/locations/europe-central2/queues/session-processing"
    assert task.name == f"{parent}/tasks/process-{sid}-stop"
    assert task.http_request.url == f"{TEST_SERVICE_URL}/internal/v2/process/{sid}"
    assert task.http_request.http_method == tasks_v2.HttpMethod.POST
    assert task.http_request.oidc_token.service_account_email == TEST_TASKS_SA
    assert task.http_request.oidc_token.audience == TEST_SERVICE_URL
    assert task.dispatch_deadline.total_seconds() == 1800
