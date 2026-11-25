"""v2 API: ownership, idempotency, validation (task sections 3 and 5.2)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from src.api.v2.dependencies import get_metadata_repo, get_packet_store, get_task_queue
from tests.fakes import InMemoryMetadataRepository, InMemoryPacketStore, RecordingTaskQueue

WALL = "2026-10-16T15:00:14.583Z"


@pytest.fixture
def v2(app, login_as):
    env = SimpleNamespace(
        repo=InMemoryMetadataRepository(),
        store=InMemoryPacketStore(),
        queue=RecordingTaskQueue(),
    )
    app.dependency_overrides[get_metadata_repo] = lambda: env.repo
    app.dependency_overrides[get_packet_store] = lambda: env.store
    app.dependency_overrides[get_task_queue] = lambda: env.queue
    login_as("patient-1")
    env.login_as = login_as
    return env


def start_body(session_id=None):
    return {
        "session_id": str(session_id or uuid.uuid4()),
        "wall_iso": WALL,
        "uptime_s": 5230.991,
        "sensors": {"A": "ESP32-IMU A", "B": "ESP32-IMU B"},
        "app_version": "1.2.0",
    }


def packet(role="A", seq=1, ts=1_000_000, rx=5231.0, **values):
    p = {"role": role, "seq": seq, "device_ts_us": ts, "phone_rx_s": rx,
         "ax": 0.455, "ay": 0.559, "az": -10.176, "gx": -0.254, "gy": 0.093, "gz": -0.023}
    p.update(values)
    return p


def batch_body(session_id, packets=None, batch_id=None):
    return {
        "schema_version": 2,
        "session_id": str(session_id),
        "batch_id": str(batch_id or uuid.uuid4()),
        "packets": packets or [packet()],
    }


def event_body(session_id, type_, uptime_s, stats=None):
    body = {"session_id": str(session_id), "type": type_, "uptime_s": uptime_s, "wall_iso": WALL}
    if stats is not None:
        body["stats"] = stats
    return body


def start(client, session_id=None):
    body = start_body(session_id)
    response = client.post("/imu/v2/sessions", json=body)
    assert response.status_code == 201, response.text
    return uuid.UUID(body["session_id"])


# ------------------------------------------------------------------ start


def test_start_is_idempotent_for_the_same_user(client, v2):
    body = start_body()
    assert client.post("/imu/v2/sessions", json=body).status_code == 201
    response = client.post("/imu/v2/sessions", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "exists"
    assert "patient-1" in v2.repo.patients


def test_start_with_session_id_of_another_user_conflicts(client, v2):
    body = start_body()
    client.post("/imu/v2/sessions", json=body)
    v2.login_as("patient-2")
    assert client.post("/imu/v2/sessions", json=body).status_code == 409


def test_no_token_is_rejected(client, v2):
    v2.login_as(None)
    assert client.post("/imu/v2/sessions", json=start_body()).status_code in (401, 403)
    assert client.post("/imu/v2/packets", json=batch_body(uuid.uuid4())).status_code in (401, 403)


# ---------------------------------------------------------------- packets


def test_packets_are_stored_raw(client, v2):
    sid = start(client)
    response = client.post("/imu/v2/packets", json=batch_body(sid, [packet(seq=7, gx=-0.25, ay=0.5)]))
    assert response.status_code == 201
    assert response.json()["accepted"] == 1

    [row] = v2.store.rows
    # No axis flip or any other transform at ingestion.
    assert row["gx"] == -0.25 and row["ay"] == 0.5
    assert row["user_id"] == "patient-1"
    assert row["session_id"] == str(sid)
    assert row["seq"] == 7


def test_packets_for_unknown_session_get_409(client, v2):
    response = client.post("/imu/v2/packets", json=batch_body(uuid.uuid4()))
    assert response.status_code == 409
    assert v2.store.rows == []


def test_packets_into_another_users_session_are_forbidden(client, v2):
    sid = start(client)
    v2.login_as("patient-2")
    assert client.post("/imu/v2/packets", json=batch_body(sid)).status_code == 403
    assert v2.store.rows == []


def test_user_id_in_body_is_ignored(client, v2):
    sid = start(client)
    body = batch_body(sid)
    body["user_id"] = "patient-2"
    assert client.post("/imu/v2/packets", json=body).status_code == 201
    assert v2.store.rows[0]["user_id"] == "patient-1"


def test_nan_in_packet_json_gives_422(client, v2):
    sid = start(client)
    raw = json.dumps(batch_body(sid)).replace("0.455", "NaN")
    response = client.post(
        "/imu/v2/packets", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert v2.store.rows == []


@pytest.mark.parametrize(
    "bad_packet",
    [packet(role="C"), packet(seq=-1), packet(ts=-5)],
)
def test_invalid_packets_give_422(client, v2, bad_packet):
    sid = start(client)
    assert client.post("/imu/v2/packets", json=batch_body(sid, [bad_packet])).status_code == 422


def test_too_many_packets_give_422(client, v2):
    sid = start(client)
    packets = [packet(seq=i) for i in range(5001)]
    assert client.post("/imu/v2/packets", json=batch_body(sid, packets)).status_code == 422


def test_storage_failure_gives_503_so_the_app_retries(client, v2):
    sid = start(client)
    v2.store.fail_inserts = True
    assert client.post("/imu/v2/packets", json=batch_body(sid)).status_code == 503


def test_late_packets_are_accepted_after_stop(client, v2):
    sid = start(client)
    client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "stop", 6000.0))
    assert client.post("/imu/v2/packets", json=batch_body(sid)).status_code == 201


# ----------------------------------------------------------------- events


def test_zero_pose_is_idempotent(client, v2):
    sid = start(client)
    body = event_body(sid, "zero_pose", 5241.507)
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=body).status_code == 201
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=body).status_code == 200
    assert [e.type for e in v2.repo.list_events(sid)] == ["zero_pose"]


def test_zero_pose_after_stop_conflicts(client, v2):
    sid = start(client)
    client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "stop", 6000.0))
    response = client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "zero_pose", 6001.0))
    assert response.status_code == 409


def test_retried_zero_pose_after_stop_is_still_ok(client, v2):
    sid = start(client)
    zero_pose = event_body(sid, "zero_pose", 5241.507)
    client.post(f"/imu/v2/sessions/{sid}/events", json=zero_pose)
    client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "stop", 6000.0))
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=zero_pose).status_code == 200


def test_stop_twice_enqueues_once(client, v2):
    sid = start(client)
    stats = {"received": 10, "lost_ble": 0, "duplicates": 0, "resets": 0, "malformed": 0, "dropped_overflow": 0}
    body = event_body(sid, "stop", 5930.002, stats={"A": stats, "B": stats})

    first = client.post(f"/imu/v2/sessions/{sid}/events", json=body)
    second = client.post(f"/imu/v2/sessions/{sid}/events", json=body)

    assert first.status_code == 201
    assert second.status_code == 200
    assert v2.queue.enqueued == [sid]
    session = v2.repo.get_session(sid)
    assert session.status == "stopped"
    assert session.stopped_uptime_s == 5930.002
    assert session.app_stats["A"]["received"] == 10


def test_stop_retry_enqueues_when_first_enqueue_failed(client, v2):
    sid = start(client)
    v2.queue.fail = True
    body = event_body(sid, "stop", 5930.0)
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=body).status_code == 503

    v2.queue.fail = False
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=body).status_code == 200
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=body).status_code == 200
    assert v2.queue.enqueued == [sid]


def test_stop_without_stats_is_accepted(client, v2):
    sid = start(client)
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "stop", 1.0)).status_code == 201
    assert v2.repo.get_session(sid).app_stats is None


def test_event_body_must_match_url(client, v2):
    sid = start(client)
    other = uuid.uuid4()
    response = client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(other, "stop", 1.0))
    assert response.status_code == 422


def test_event_on_other_users_session_is_forbidden(client, v2):
    sid = start(client)
    v2.login_as("patient-2")
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "stop", 1.0)).status_code == 403
    assert v2.queue.enqueued == []


def test_event_on_unknown_session_is_404(client, v2):
    sid = uuid.uuid4()
    assert client.post(f"/imu/v2/sessions/{sid}/events", json=event_body(sid, "stop", 1.0)).status_code == 404


# ------------------------------------------------------------------- pain


def pain_body(session_id, level=4):
    return {"session_id": str(session_id), "pain_level": level, "uptime_s": 5932.11, "wall_iso": WALL}


def test_pain_creates_report_row_without_processing(client, v2):
    sid = start(client)
    assert client.post(f"/imu/v2/sessions/{sid}/pain", json=pain_body(sid)).status_code == 201
    assert v2.repo.get_report(sid).pain_level == 4
    assert v2.repo.get_report(sid).computed_at is None
    assert v2.queue.enqueued == []
    assert v2.repo.get_session(sid).status == "active"

    assert client.post(f"/imu/v2/sessions/{sid}/pain", json=pain_body(sid, 6)).status_code == 201
    assert v2.repo.get_report(sid).pain_level == 6


def test_pain_out_of_range_is_422(client, v2):
    sid = start(client)
    assert client.post(f"/imu/v2/sessions/{sid}/pain", json=pain_body(sid, 11)).status_code == 422


def test_pain_on_other_users_session_is_forbidden(client, v2):
    sid = start(client)
    v2.login_as("patient-2")
    assert client.post(f"/imu/v2/sessions/{sid}/pain", json=pain_body(sid)).status_code == 403


# -------------------------------------------------------------------- get


def test_get_session(client, v2):
    sid = start(client)
    client.post(f"/imu/v2/sessions/{sid}/pain", json=pain_body(sid, 3))

    response = client.get(f"/imu/v2/sessions/{sid}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["pain_level"] == 3
    assert body["metrics"] is None


def test_get_other_users_session_is_forbidden(client, v2):
    sid = start(client)
    v2.login_as("patient-2")
    assert client.get(f"/imu/v2/sessions/{sid}").status_code == 403


def test_get_unknown_session_is_404(client, v2):
    assert client.get(f"/imu/v2/sessions/{uuid.uuid4()}").status_code == 404
