"""Cloud SQL (PostgreSQL) implementation of :class:`MetadataRepository`.

Tables: see sql/postgres/002_sessions_v2.sql. Every write runs inside
``engine.begin()`` so it is committed (or rolled back) as one transaction.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import sqlalchemy
from sqlalchemy import text

from src.models.contract_v2 import SessionStart
from src.repositories.interfaces import (
    EventRecord,
    ProcessedReport,
    ReportRecord,
    SessionRecord,
    StartOutcome,
    StopOutcome,
    ZeroPoseOutcome,
)

_SESSION_COLUMNS = """
    session_id, patient_id, wall_anchor, uptime_anchor_s, sensors, app_version, status,
    stopped_uptime_s, app_stats, processing_attempts, processing_error,
    processing_enqueued_at, algorithm_version, created_at
"""


def _json_obj(value):
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


def _uuid(value) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _session_from_row(row) -> SessionRecord:
    m = row._mapping
    return SessionRecord(
        session_id=_uuid(m["session_id"]),
        patient_id=m["patient_id"],
        wall_anchor=m["wall_anchor"],
        uptime_anchor_s=float(m["uptime_anchor_s"]),
        sensors=_json_obj(m["sensors"]) or {},
        app_version=m["app_version"],
        status=m["status"],
        stopped_uptime_s=m["stopped_uptime_s"],
        app_stats=_json_obj(m["app_stats"]),
        processing_attempts=m["processing_attempts"],
        processing_error=m["processing_error"],
        processing_enqueued_at=m["processing_enqueued_at"],
        algorithm_version=m["algorithm_version"],
        created_at=m["created_at"],
    )


class CloudSqlMetadataRepository:
    def __init__(self, engine: sqlalchemy.engine.Engine):
        self.engine = engine

    # ------------------------------------------------------------ sessions

    def start_session(self, user_id: str, start: SessionStart) -> StartOutcome:
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO patients (patient_id) VALUES (:uid) ON CONFLICT (patient_id) DO NOTHING"),
                {"uid": user_id},
            )
            inserted = conn.execute(
                text(
                    """
                    INSERT INTO sessions_v2
                        (session_id, patient_id, wall_anchor, uptime_anchor_s, sensors, app_version, status)
                    VALUES (:sid, :uid, :wall, :uptime, CAST(:sensors AS JSONB), :app_version, 'active')
                    ON CONFLICT (session_id) DO NOTHING
                    RETURNING session_id
                    """
                ),
                {
                    "sid": start.session_id,
                    "uid": user_id,
                    "wall": start.wall_iso,
                    "uptime": start.uptime_s,
                    "sensors": json.dumps(start.sensors),
                    "app_version": start.app_version,
                },
            ).first()
            if inserted is not None:
                return "created"
            owner = conn.execute(
                text("SELECT patient_id FROM sessions_v2 WHERE session_id = :sid"),
                {"sid": start.session_id},
            ).scalar_one()
        return "exists" if owner == user_id else "conflict"

    def get_session(self, session_id: UUID) -> SessionRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT {_SESSION_COLUMNS} FROM sessions_v2 WHERE session_id = :sid"),
                {"sid": session_id},
            ).first()
        return _session_from_row(row) if row is not None else None

    # -------------------------------------------------------------- events

    def add_zero_pose(self, session_id: UUID, uptime_s: float, wall_iso: datetime) -> ZeroPoseOutcome:
        with self.engine.begin() as conn:
            status = conn.execute(
                text("SELECT status FROM sessions_v2 WHERE session_id = :sid FOR UPDATE"),
                {"sid": session_id},
            ).scalar_one()
            exists = conn.execute(
                text(
                    """
                    SELECT 1 FROM session_events_v2
                    WHERE session_id = :sid AND type = 'zero_pose' AND uptime_s = :uptime
                    """
                ),
                {"sid": session_id, "uptime": uptime_s},
            ).first()
            if exists is not None:
                return "exists"
            if status != "active":
                return "not_active"
            conn.execute(
                text(
                    """
                    INSERT INTO session_events_v2 (session_id, type, uptime_s, wall_iso)
                    VALUES (:sid, 'zero_pose', :uptime, :wall)
                    """
                ),
                {"sid": session_id, "uptime": uptime_s, "wall": wall_iso},
            )
            conn.execute(
                text("UPDATE sessions_v2 SET updated_at = now() WHERE session_id = :sid"),
                {"sid": session_id},
            )
        return "created"

    def stop_session(
        self, session_id: UUID, uptime_s: float, wall_iso: datetime, stats: dict | None
    ) -> StopOutcome:
        stats_json = json.dumps(stats) if stats is not None else None
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT status, processing_enqueued_at FROM sessions_v2
                    WHERE session_id = :sid FOR UPDATE
                    """
                ),
                {"sid": session_id},
            ).one()
            status, enqueued_at = row
            conn.execute(
                text(
                    """
                    INSERT INTO session_events_v2 (session_id, type, uptime_s, wall_iso)
                    VALUES (:sid, 'stop', :uptime, :wall)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"sid": session_id, "uptime": uptime_s, "wall": wall_iso},
            )
            if status == "active":
                conn.execute(
                    text(
                        """
                        UPDATE sessions_v2
                        SET status = 'stopped', stopped_uptime_s = :uptime,
                            app_stats = CAST(:stats AS JSONB), updated_at = now()
                        WHERE session_id = :sid
                        """
                    ),
                    {"sid": session_id, "uptime": uptime_s, "stats": stats_json},
                )
                return StopOutcome(first_stop=True, needs_enqueue=True)

            # Repeated stop: fill in stats an older request did not carry.
            conn.execute(
                text(
                    """
                    UPDATE sessions_v2
                    SET app_stats = COALESCE(app_stats, CAST(:stats AS JSONB)), updated_at = now()
                    WHERE session_id = :sid
                    """
                ),
                {"sid": session_id, "stats": stats_json},
            )
        return StopOutcome(first_stop=False, needs_enqueue=status == "stopped" and enqueued_at is None)

    def mark_enqueued(self, session_id: UUID) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE sessions_v2 SET processing_enqueued_at = now(), updated_at = now()
                    WHERE session_id = :sid
                    """
                ),
                {"sid": session_id},
            )

    def list_events(self, session_id: UUID) -> list[EventRecord]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT type, uptime_s, wall_iso FROM session_events_v2
                    WHERE session_id = :sid ORDER BY uptime_s, type
                    """
                ),
                {"sid": session_id},
            ).all()
        return [EventRecord(type=r[0], uptime_s=float(r[1]), wall_iso=r[2]) for r in rows]

    # ------------------------------------------------------------- reports

    def set_pain(self, session_id: UUID, pain_level: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO reports_v2 (session_id, pain_level) VALUES (:sid, :pain)
                    ON CONFLICT (session_id) DO UPDATE SET pain_level = EXCLUDED.pain_level
                    """
                ),
                {"sid": session_id, "pain": pain_level},
            )

    def get_report(self, session_id: UUID) -> ReportRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT session_id, duration_s, max_flexion, max_extension, max_pronation,
                           max_supination, rep_count, smoothness, pain_level, quality, quality_ok,
                           algorithm_version, computed_at
                    FROM reports_v2 WHERE session_id = :sid
                    """
                ),
                {"sid": session_id},
            ).first()
        if row is None:
            return None
        m = dict(row._mapping)
        m["session_id"] = _uuid(m["session_id"])
        m["quality"] = _json_obj(m["quality"])
        return ReportRecord(**m)

    # ---------------------------------------------------------- processing

    def claim_processing(self, session_id: UUID, lease_s: float) -> SessionRecord | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    f"""
                    UPDATE sessions_v2
                    SET status = 'processing',
                        processing_attempts = processing_attempts + 1,
                        processing_started_at = now(),
                        updated_at = now()
                    WHERE session_id = :sid
                      AND status <> 'active'
                      AND (status <> 'processing'
                           OR processing_started_at IS NULL
                           OR processing_started_at < now() - make_interval(secs => :lease))
                    RETURNING {_SESSION_COLUMNS}
                    """
                ),
                {"sid": session_id, "lease": float(lease_s)},
            ).first()
        return _session_from_row(row) if row is not None else None

    def release_claim(self, session_id: UUID) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE sessions_v2
                    SET status = 'stopped', processing_started_at = NULL, updated_at = now()
                    WHERE session_id = :sid AND status = 'processing'
                    """
                ),
                {"sid": session_id},
            )

    def save_processing_result(self, session_id: UUID, report: ProcessedReport) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO reports_v2 (
                        session_id, duration_s, max_flexion, max_extension, max_pronation,
                        max_supination, rep_count, smoothness, quality, quality_ok,
                        algorithm_version, computed_at)
                    VALUES (
                        :sid, :duration_s, :max_flexion, :max_extension, :max_pronation,
                        :max_supination, :rep_count, :smoothness, CAST(:quality AS JSONB), :quality_ok,
                        :algorithm_version, :computed_at)
                    ON CONFLICT (session_id) DO UPDATE SET
                        duration_s = EXCLUDED.duration_s,
                        max_flexion = EXCLUDED.max_flexion,
                        max_extension = EXCLUDED.max_extension,
                        max_pronation = EXCLUDED.max_pronation,
                        max_supination = EXCLUDED.max_supination,
                        rep_count = EXCLUDED.rep_count,
                        smoothness = EXCLUDED.smoothness,
                        quality = EXCLUDED.quality,
                        quality_ok = EXCLUDED.quality_ok,
                        algorithm_version = EXCLUDED.algorithm_version,
                        computed_at = EXCLUDED.computed_at
                    """
                ),
                {
                    "sid": session_id,
                    "duration_s": report.duration_s,
                    "max_flexion": report.max_flexion,
                    "max_extension": report.max_extension,
                    "max_pronation": report.max_pronation,
                    "max_supination": report.max_supination,
                    "rep_count": report.rep_count,
                    "smoothness": report.smoothness,
                    "quality": json.dumps(report.quality),
                    "quality_ok": report.quality_ok,
                    "algorithm_version": report.algorithm_version,
                    "computed_at": report.computed_at,
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE sessions_v2
                    SET status = 'done', algorithm_version = :algorithm_version,
                        processing_error = NULL, processing_started_at = NULL, updated_at = now()
                    WHERE session_id = :sid
                    """
                ),
                {"sid": session_id, "algorithm_version": report.algorithm_version},
            )

    def mark_failed(self, session_id: UUID, error: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE sessions_v2
                    SET status = 'failed', processing_error = :error,
                        processing_started_at = NULL, updated_at = now()
                    WHERE session_id = :sid
                    """
                ),
                {"sid": session_id, "error": error[:2000]},
            )
