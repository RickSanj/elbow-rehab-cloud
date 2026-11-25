"""Storage interfaces used by the v2 API and the processing job.

Production implementations: :mod:`src.repositories.cloud_sql_v2` (session
metadata), :mod:`src.repositories.bigquery_v2` (raw packets, angles) and
:mod:`src.repositories.tasks` (Cloud Tasks). Unit tests use the in-memory
fakes in ``tests/fakes.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

import pandas as pd

from src.models.contract_v2 import PacketBatch, SessionStart

StartOutcome = Literal["created", "exists", "conflict"]
ZeroPoseOutcome = Literal["created", "exists", "not_active"]


@dataclass(frozen=True)
class SessionRecord:
    session_id: UUID
    patient_id: str
    wall_anchor: datetime
    uptime_anchor_s: float
    sensors: dict
    app_version: str | None
    status: str
    stopped_uptime_s: float | None = None
    app_stats: dict | None = None
    processing_attempts: int = 0
    processing_error: str | None = None
    processing_enqueued_at: datetime | None = None
    algorithm_version: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class EventRecord:
    type: str
    uptime_s: float
    wall_iso: datetime


@dataclass(frozen=True)
class StopOutcome:
    first_stop: bool  # this request moved the session from active to stopped
    needs_enqueue: bool  # processing has not been enqueued yet


@dataclass(frozen=True)
class ReportRecord:
    session_id: UUID
    duration_s: float | None = None
    max_flexion: float | None = None
    max_extension: float | None = None
    max_pronation: float | None = None
    max_supination: float | None = None
    rep_count: int | None = None
    smoothness: float | None = None
    pain_level: int | None = None
    quality: dict | None = None
    quality_ok: bool | None = None
    algorithm_version: str | None = None
    computed_at: datetime | None = None


@dataclass(frozen=True)
class ProcessedReport:
    """Everything processing writes to reports_v2 (pain_level is kept)."""

    duration_s: float | None
    max_flexion: float | None
    max_extension: float | None
    max_pronation: float | None
    max_supination: float | None
    rep_count: int | None
    smoothness: float | None
    quality: dict = field(default_factory=dict)
    quality_ok: bool = False
    algorithm_version: str = ""
    computed_at: datetime | None = None


class MetadataRepository(Protocol):
    """Session metadata, events and reports (Cloud SQL)."""

    def start_session(self, user_id: str, start: SessionStart) -> StartOutcome: ...

    def get_session(self, session_id: UUID) -> SessionRecord | None: ...

    def add_zero_pose(self, session_id: UUID, uptime_s: float, wall_iso: datetime) -> ZeroPoseOutcome: ...

    def stop_session(
        self, session_id: UUID, uptime_s: float, wall_iso: datetime, stats: dict | None
    ) -> StopOutcome: ...

    def mark_enqueued(self, session_id: UUID) -> None: ...

    def set_pain(self, session_id: UUID, pain_level: int) -> None: ...

    def get_report(self, session_id: UUID) -> ReportRecord | None: ...

    def list_events(self, session_id: UUID) -> list[EventRecord]: ...

    # -- processing -------------------------------------------------------

    def claim_processing(self, session_id: UUID, lease_s: float) -> SessionRecord | None:
        """Atomically move the session to 'processing' and count an attempt.

        Returns the updated record, or None when the session does not exist,
        is still active, or another attempt holds an unexpired lease.
        """
        ...

    def release_claim(self, session_id: UUID) -> None:
        """Give the claim back without a result (data not ready yet)."""
        ...

    def save_processing_result(self, session_id: UUID, report: ProcessedReport) -> None:
        """Upsert reports_v2 metrics (keeping pain_level) and mark 'done'."""
        ...

    def mark_failed(self, session_id: UUID, error: str) -> None: ...


class PacketStore(Protocol):
    """Raw packets and processed angles (BigQuery)."""

    def insert_packets(self, user_id: str, batch: PacketBatch, ingested_at: datetime) -> None: ...

    def count_packets(self, session_id: UUID, since: datetime | None = None) -> dict[str, int]:
        """Distinct packets per role (same dedup key as processing)."""
        ...

    def load_packets(self, session_id: UUID, since: datetime | None = None) -> pd.DataFrame:
        """Deduplicated raw packets of one session."""
        ...

    def replace_angles(
        self, session_id: UUID, angles: pd.DataFrame, algorithm_version: str, computed_at: datetime
    ) -> None:
        """Make ``angles`` the only angles_v2 rows of this session."""
        ...


class TaskQueue(Protocol):
    def enqueue_processing(self, session_id: UUID) -> None: ...
