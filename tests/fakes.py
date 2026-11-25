"""In-memory fakes for the storage interfaces (src/repositories/interfaces.py).

They implement the same observable behaviour as the Cloud SQL / BigQuery /
Cloud Tasks implementations; tests/test_repository_contract.py runs the same
checks against the fake and (opt-in) against a local PostgreSQL.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pandas as pd

from src.models.contract_v2 import PacketBatch, SessionStart
from src.processing.load import dedup_packets
from src.repositories.bigquery_v2 import PACKET_COLUMNS, batch_to_rows
from src.repositories.interfaces import (
    EventRecord,
    ProcessedReport,
    ReportRecord,
    SessionRecord,
    StartOutcome,
    StopOutcome,
    ZeroPoseOutcome,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryMetadataRepository:
    def __init__(self):
        self.patients: set[str] = set()
        self.sessions: dict[UUID, SessionRecord] = {}
        self.events: dict[UUID, list[EventRecord]] = {}
        self.reports: dict[UUID, ReportRecord] = {}
        self._processing_started: dict[UUID, datetime | None] = {}
        self._lock = threading.Lock()

    def start_session(self, user_id: str, start: SessionStart) -> StartOutcome:
        with self._lock:
            self.patients.add(user_id)
            existing = self.sessions.get(start.session_id)
            if existing is not None:
                return "exists" if existing.patient_id == user_id else "conflict"
            self.sessions[start.session_id] = SessionRecord(
                session_id=start.session_id,
                patient_id=user_id,
                wall_anchor=start.wall_iso,
                uptime_anchor_s=start.uptime_s,
                sensors=dict(start.sensors),
                app_version=start.app_version,
                status="active",
                created_at=_now(),
            )
            self.events[start.session_id] = []
            return "created"

    def get_session(self, session_id: UUID) -> SessionRecord | None:
        return self.sessions.get(session_id)

    def _update(self, session_id: UUID, **changes) -> SessionRecord:
        record = replace(self.sessions[session_id], **changes)
        self.sessions[session_id] = record
        return record

    def add_zero_pose(self, session_id: UUID, uptime_s: float, wall_iso: datetime) -> ZeroPoseOutcome:
        with self._lock:
            session = self.sessions[session_id]
            events = self.events[session_id]
            if any(e.type == "zero_pose" and e.uptime_s == uptime_s for e in events):
                return "exists"
            if session.status != "active":
                return "not_active"
            events.append(EventRecord("zero_pose", uptime_s, wall_iso))
            return "created"

    def stop_session(self, session_id: UUID, uptime_s: float, wall_iso: datetime, stats: dict | None) -> StopOutcome:
        with self._lock:
            session = self.sessions[session_id]
            events = self.events[session_id]
            if not any(e.type == "stop" and e.uptime_s == uptime_s for e in events):
                events.append(EventRecord("stop", uptime_s, wall_iso))
            if session.status == "active":
                self._update(
                    session_id,
                    status="stopped",
                    stopped_uptime_s=uptime_s,
                    app_stats=copy.deepcopy(stats),
                )
                return StopOutcome(first_stop=True, needs_enqueue=True)
            if session.app_stats is None and stats is not None:
                self._update(session_id, app_stats=copy.deepcopy(stats))
            return StopOutcome(
                first_stop=False,
                needs_enqueue=session.status == "stopped" and session.processing_enqueued_at is None,
            )

    def mark_enqueued(self, session_id: UUID) -> None:
        with self._lock:
            self._update(session_id, processing_enqueued_at=_now())

    def list_events(self, session_id: UUID) -> list[EventRecord]:
        return sorted(self.events.get(session_id, []), key=lambda e: (e.uptime_s, e.type))

    def set_pain(self, session_id: UUID, pain_level: int) -> None:
        with self._lock:
            report = self.reports.get(session_id) or ReportRecord(session_id=session_id)
            self.reports[session_id] = replace(report, pain_level=pain_level)

    def get_report(self, session_id: UUID) -> ReportRecord | None:
        return self.reports.get(session_id)

    def claim_processing(self, session_id: UUID, lease_s: float) -> SessionRecord | None:
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None or session.status == "active":
                return None
            started = self._processing_started.get(session_id)
            if session.status == "processing" and started is not None:
                if started >= _now() - timedelta(seconds=lease_s):
                    return None
            self._processing_started[session_id] = _now()
            return self._update(
                session_id,
                status="processing",
                processing_attempts=session.processing_attempts + 1,
            )

    def release_claim(self, session_id: UUID) -> None:
        with self._lock:
            if self.sessions[session_id].status == "processing":
                self._processing_started[session_id] = None
                self._update(session_id, status="stopped")

    def save_processing_result(self, session_id: UUID, report: ProcessedReport) -> None:
        with self._lock:
            pain = self.reports.get(session_id).pain_level if session_id in self.reports else None
            self.reports[session_id] = ReportRecord(
                session_id=session_id,
                duration_s=report.duration_s,
                max_flexion=report.max_flexion,
                max_extension=report.max_extension,
                max_pronation=report.max_pronation,
                max_supination=report.max_supination,
                rep_count=report.rep_count,
                smoothness=report.smoothness,
                pain_level=pain,
                quality=copy.deepcopy(report.quality),
                quality_ok=report.quality_ok,
                algorithm_version=report.algorithm_version,
                computed_at=report.computed_at,
            )
            self._processing_started[session_id] = None
            self._update(
                session_id,
                status="done",
                algorithm_version=report.algorithm_version,
                processing_error=None,
            )

    def mark_failed(self, session_id: UUID, error: str) -> None:
        with self._lock:
            self._processing_started[session_id] = None
            self._update(session_id, status="failed", processing_error=error[:2000])


class InMemoryPacketStore:
    """Keeps every inserted row (like BigQuery when row_ids dedup misses)."""

    def __init__(self):
        self.rows: list[dict] = []
        self.angles: dict[str, pd.DataFrame] = {}
        self.insert_calls = 0
        self.fail_inserts = False

    def insert_packets(self, user_id: str, batch: PacketBatch, ingested_at: datetime) -> None:
        if self.fail_inserts:
            raise RuntimeError("simulated BigQuery outage")
        self.insert_calls += 1
        rows, _row_ids = batch_to_rows(user_id, batch, ingested_at)
        for row in rows:
            row["ingested_at"] = ingested_at
        self.rows.extend(rows)

    def _session_rows(self, session_id: UUID) -> pd.DataFrame:
        rows = [r for r in self.rows if r["session_id"] == str(session_id)]
        if not rows:
            return pd.DataFrame(columns=PACKET_COLUMNS)
        return pd.DataFrame(rows)

    def count_packets(self, session_id: UUID, since: datetime | None = None) -> dict[str, int]:
        df = dedup_packets(self._session_rows(session_id))
        return {str(k): int(v) for k, v in df.groupby("role").size().items()}

    def load_packets(self, session_id: UUID, since: datetime | None = None) -> pd.DataFrame:
        return dedup_packets(self._session_rows(session_id))[PACKET_COLUMNS].reset_index(drop=True)

    def replace_angles(
        self, session_id: UUID, angles: pd.DataFrame, algorithm_version: str, computed_at: datetime
    ) -> None:
        out = angles[["t_s", "fe_deg", "ps_deg", "valid"]].copy()
        out.insert(0, "session_id", str(session_id))
        out["algorithm_version"] = algorithm_version
        out["computed_at"] = computed_at
        self.angles[str(session_id)] = out.reset_index(drop=True)


class RecordingTaskQueue:
    def __init__(self):
        self.enqueued: list[UUID] = []
        self.fail = False

    def enqueue_processing(self, session_id: UUID) -> None:
        if self.fail:
            raise RuntimeError("simulated Cloud Tasks outage")
        self.enqueued.append(session_id)
