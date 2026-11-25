"""Same behaviour checks for the in-memory fake and the Cloud SQL repository.

The Cloud SQL variant runs only when PG_TEST_DSN points to a *throwaway local*
PostgreSQL (it drops and recreates the public schema), for example:

    PG_TEST_DSN=postgresql+pg8000://test@localhost:54329/rehab pytest -m postgres

It refuses any host other than localhost.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models.contract_v2 import SessionStart
from src.repositories.interfaces import ProcessedReport
from tests.fakes import InMemoryMetadataRepository

ROOT = Path(__file__).resolve().parents[1]
WALL = datetime(2026, 10, 16, 15, 0, 14, tzinfo=timezone.utc)


def _postgres_repo():
    dsn = os.environ.get("PG_TEST_DSN")
    if not dsn:
        pytest.skip("PG_TEST_DSN not set")
    import sqlalchemy
    from sqlalchemy import text

    from src.repositories.cloud_sql_v2 import CloudSqlMetadataRepository

    engine = sqlalchemy.create_engine(dsn)
    if engine.url.host not in ("localhost", "127.0.0.1"):
        pytest.fail("PG_TEST_DSN must point to a local throwaway database")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE TABLE patients (patient_id TEXT PRIMARY KEY)"))
    migration = (ROOT / "sql/postgres/002_sessions_v2.sql").read_text()
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        for statement in migration.split(";"):
            body = "\n".join(
                line for line in statement.splitlines() if not line.strip().startswith("--")
            ).strip()
            if body and body.upper() not in ("BEGIN", "COMMIT"):
                cursor.execute(body)
        raw.commit()
    finally:
        raw.close()
    return CloudSqlMetadataRepository(engine)


@pytest.fixture(
    params=[
        "fake",
        pytest.param("postgres", marks=pytest.mark.postgres),
    ]
)
def repo(request):
    if request.param == "fake":
        return InMemoryMetadataRepository()
    return _postgres_repo()


def make_start(session_id=None) -> SessionStart:
    return SessionStart(
        session_id=session_id or uuid.uuid4(),
        wall_iso=WALL,
        uptime_s=5230.991,
        sensors={"A": "ESP32-IMU A", "B": "ESP32-IMU B"},
        app_version="1.2.0",
    )


def test_start_and_get(repo):
    start = make_start()
    assert repo.start_session("u1", start) == "created"
    assert repo.start_session("u1", start) == "exists"
    assert repo.start_session("u2", start) == "conflict"

    session = repo.get_session(start.session_id)
    assert session.patient_id == "u1"
    assert session.status == "active"
    assert session.uptime_anchor_s == pytest.approx(5230.991)
    assert session.sensors == {"A": "ESP32-IMU A", "B": "ESP32-IMU B"}
    assert session.wall_anchor == WALL
    assert repo.get_session(uuid.uuid4()) is None


def test_zero_pose_and_stop(repo):
    start = make_start()
    sid = start.session_id
    repo.start_session("u1", start)

    assert repo.add_zero_pose(sid, 5241.5, WALL) == "created"
    assert repo.add_zero_pose(sid, 5241.5, WALL) == "exists"
    assert repo.add_zero_pose(sid, 5250.0, WALL) == "created"

    first = repo.stop_session(sid, 5930.0, WALL, None)
    assert (first.first_stop, first.needs_enqueue) == (True, True)
    stats = {"A": {"received": 5}, "B": {"received": 6}}
    second = repo.stop_session(sid, 5930.0, WALL, stats)
    assert (second.first_stop, second.needs_enqueue) == (False, True)
    repo.mark_enqueued(sid)
    third = repo.stop_session(sid, 5931.0, WALL, None)
    assert (third.first_stop, third.needs_enqueue) == (False, False)

    session = repo.get_session(sid)
    assert session.status == "stopped"
    assert session.stopped_uptime_s == pytest.approx(5930.0)
    assert session.app_stats == stats  # filled in by the repeated stop
    assert session.processing_enqueued_at is not None
    assert repo.add_zero_pose(sid, 5999.0, WALL) == "not_active"

    events = repo.list_events(sid)
    assert [(e.type, e.uptime_s) for e in events] == [
        ("zero_pose", 5241.5),
        ("zero_pose", 5250.0),
        ("stop", 5930.0),
        ("stop", 5931.0),
    ]


def test_pain_and_processing_lifecycle(repo):
    start = make_start()
    sid = start.session_id
    repo.start_session("u1", start)
    repo.set_pain(sid, 4)
    assert repo.get_report(sid).pain_level == 4
    assert repo.get_report(sid).computed_at is None

    assert repo.claim_processing(sid, lease_s=60) is None  # still active

    repo.stop_session(sid, 10.0, WALL, None)
    claimed = repo.claim_processing(sid, lease_s=60)
    assert claimed.status == "processing"
    assert claimed.processing_attempts == 1
    assert repo.claim_processing(sid, lease_s=60) is None  # lease held

    repo.release_claim(sid)
    assert repo.get_session(sid).status == "stopped"

    claimed = repo.claim_processing(sid, lease_s=60)
    assert claimed.processing_attempts == 2

    computed_at = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    report = ProcessedReport(
        duration_s=600.0,
        max_flexion=120.0,
        max_extension=5.0,
        max_pronation=60.0,
        max_supination=-40.0,
        rep_count=10,
        smoothness=-1.8,
        quality={"A": {"lost_total": 0}},
        quality_ok=True,
        algorithm_version="v-test",
        computed_at=computed_at,
    )
    repo.save_processing_result(sid, report)
    session = repo.get_session(sid)
    assert session.status == "done"
    assert session.algorithm_version == "v-test"
    stored = repo.get_report(sid)
    assert stored.pain_level == 4  # kept by processing
    assert stored.rep_count == 10
    assert stored.quality == {"A": {"lost_total": 0}}
    assert stored.computed_at == computed_at

    repo.set_pain(sid, 7)
    assert repo.get_report(sid).rep_count == 10

    # Re-processing a done session is allowed; failure is recorded.
    assert repo.claim_processing(sid, lease_s=60).processing_attempts == 3
    repo.mark_failed(sid, "boom")
    session = repo.get_session(sid)
    assert session.status == "failed"
    assert session.processing_error == "boom"


def test_expired_lease_can_be_reclaimed(repo):
    start = make_start()
    sid = start.session_id
    repo.start_session("u1", start)
    repo.stop_session(sid, 10.0, WALL, None)
    assert repo.claim_processing(sid, lease_s=60) is not None
    time.sleep(0.05)
    assert repo.claim_processing(sid, lease_s=0.01) is not None
