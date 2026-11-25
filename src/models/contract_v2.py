"""Data contract v2 between the iOS app and the backend.

Shared with AGENT_TASK_ios_v2.md. Rules:

* Unknown fields are ignored (forward compatible with newer app builds).
* Every float must be finite (NaN/inf -> 422).
* ``user_id`` is never part of a request body; it comes from the verified
  Firebase token only.
* Phone times (``phone_rx_s``, ``uptime_s``) are CLOCK_MONOTONIC seconds.
  ``(wall_iso, uptime_s)`` in :class:`SessionStart` anchors them to wall time:
  ``wall_time = wall_iso + (t - uptime_s)``.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SCHEMA_VERSION = 2
MAX_PACKETS_PER_BATCH = 5000
UINT32_MAX = 2**32 - 1
INT64_MAX = 2**63 - 1

Role = Literal["A", "B"]  # A = upper arm, B = forearm
EventType = Literal["zero_pose", "stop"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class SessionStart(ContractModel):
    session_id: UUID
    wall_iso: AwareDatetime
    uptime_s: float = Field(ge=0)
    sensors: dict[Role, str]
    app_version: str | None = Field(default=None, max_length=64)


class Packet(ContractModel):
    role: Role
    seq: int = Field(ge=0, le=UINT32_MAX)  # +1 per packet, restarts at 0 on reboot
    device_ts_us: int = Field(ge=0, le=INT64_MAX)  # board clock
    phone_rx_s: float  # phone monotonic receive time
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


class PacketBatch(ContractModel):
    schema_version: Literal[2]
    session_id: UUID
    batch_id: UUID
    packets: list[Packet] = Field(min_length=1, max_length=MAX_PACKETS_PER_BATCH)


class RoleStats(ContractModel):
    received: int = Field(default=0, ge=0)
    lost_ble: int = Field(default=0, ge=0)
    duplicates: int = Field(default=0, ge=0)
    resets: int = Field(default=0, ge=0)
    malformed: int = Field(default=0, ge=0)
    dropped_overflow: int = Field(default=0, ge=0)


class SessionEvent(ContractModel):
    session_id: UUID
    type: EventType
    uptime_s: float = Field(ge=0)
    wall_iso: AwareDatetime
    # Only sent with "stop"; optional because older app builds omit it.
    stats: dict[Role, RoleStats] | None = None


class PainReport(ContractModel):
    session_id: UUID
    pain_level: int = Field(ge=0, le=10)
    uptime_s: float = Field(ge=0)
    wall_iso: AwareDatetime


# ------------------------------------------------------------------ responses

SessionStatus = Literal["active", "stopped", "processing", "done", "failed"]


class Metrics(BaseModel):
    duration_s: float | None = None
    max_flexion: float | None = None
    max_extension: float | None = None
    max_pronation: float | None = None
    max_supination: float | None = None
    rep_count: int | None = None
    smoothness: float | None = None


class SessionView(BaseModel):
    session_id: UUID
    status: SessionStatus
    pain_level: int | None = None
    metrics: Metrics | None = None
    quality: dict | None = None
    quality_ok: bool | None = None
    algorithm_version: str | None = None
    processing_error: str | None = None


class Ack(BaseModel):
    session_id: UUID
    status: str
    detail: str | None = None
