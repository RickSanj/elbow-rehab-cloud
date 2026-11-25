"""Validation rules of the v2 data contract (task section 3)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.models.contract_v2 import PacketBatch, PainReport, SessionEvent, SessionStart


def make_packet(**overrides) -> dict:
    packet = {
        "role": "A",
        "seq": 177911,
        "device_ts_us": 1780475045,
        "phone_rx_s": 5231.023412,
        "ax": 0.455,
        "ay": 0.559,
        "az": -10.176,
        "gx": -0.254,
        "gy": 0.093,
        "gz": -0.023,
    }
    packet.update(overrides)
    return packet


def make_batch(packets=None, **overrides) -> dict:
    batch = {
        "schema_version": 2,
        "session_id": str(uuid.uuid4()),
        "batch_id": str(uuid.uuid4()),
        "packets": packets if packets is not None else [make_packet()],
    }
    batch.update(overrides)
    return batch


def test_valid_batch():
    batch = PacketBatch.model_validate(make_batch())
    assert batch.packets[0].seq == 177911
    assert batch.packets[0].role == "A"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_float_rejected(value):
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch([make_packet(gx=value)]))


def test_nan_from_json_rejected():
    raw = (
        '{"schema_version": 2, "session_id": "%s", "batch_id": "%s", "packets": '
        '[{"role": "A", "seq": 1, "device_ts_us": 1, "phone_rx_s": NaN, '
        '"ax": 0, "ay": 0, "az": 0, "gx": 0, "gy": 0, "gz": 0}]}'
    ) % (uuid.uuid4(), uuid.uuid4())
    with pytest.raises(ValidationError):
        PacketBatch.model_validate_json(raw)


def test_unknown_role_rejected():
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch([make_packet(role="C")]))


@pytest.mark.parametrize("field", ["seq", "device_ts_us"])
def test_negative_counters_rejected(field):
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch([make_packet(**{field: -1})]))


def test_seq_above_uint32_rejected():
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch([make_packet(seq=2**32)]))


def test_batch_size_limits():
    PacketBatch.model_validate(make_batch([make_packet(seq=i) for i in range(5000)]))
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch([make_packet(seq=i) for i in range(5001)]))
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch([]))


def test_ids_must_be_uuids():
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch(session_id="user_2026-01-01T00:00:00Z"))
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch(batch_id="not-a-uuid"))


def test_schema_version_must_be_2():
    with pytest.raises(ValidationError):
        PacketBatch.model_validate(make_batch(schema_version=1))


def test_unknown_fields_ignored_and_user_id_never_read_from_body():
    batch = PacketBatch.model_validate(
        make_batch([make_packet(rssi=-60)], user_id="someone-else", future_field=1)
    )
    assert not hasattr(batch, "user_id")
    assert not hasattr(batch.packets[0], "rssi")


def test_stop_without_stats_accepted():
    event = SessionEvent.model_validate(
        {
            "session_id": str(uuid.uuid4()),
            "type": "stop",
            "uptime_s": 5930.002,
            "wall_iso": "2026-10-16T15:11:44.000Z",
        }
    )
    assert event.stats is None


def test_stop_with_stats():
    stats = {"received": 10, "lost_ble": 1, "duplicates": 0, "resets": 0, "malformed": 0, "dropped_overflow": 0}
    event = SessionEvent.model_validate(
        {
            "session_id": str(uuid.uuid4()),
            "type": "stop",
            "uptime_s": 5930.002,
            "wall_iso": "2026-10-16T15:11:44.000Z",
            "stats": {"A": stats, "B": stats},
        }
    )
    assert event.stats["A"].lost_ble == 1


def test_unknown_event_type_rejected():
    with pytest.raises(ValidationError):
        SessionEvent.model_validate(
            {
                "session_id": str(uuid.uuid4()),
                "type": "pause",
                "uptime_s": 1.0,
                "wall_iso": "2026-10-16T15:11:44Z",
            }
        )


@pytest.mark.parametrize("level", [-1, 11, 4.5])
def test_pain_level_out_of_range_rejected(level):
    with pytest.raises(ValidationError):
        PainReport.model_validate(
            {
                "session_id": str(uuid.uuid4()),
                "pain_level": level,
                "uptime_s": 1.0,
                "wall_iso": "2026-10-16T15:11:44Z",
            }
        )


def test_session_start_requires_timezone():
    base = {
        "session_id": str(uuid.uuid4()),
        "uptime_s": 5230.991,
        "sensors": {"A": "ESP32-IMU A", "B": "ESP32-IMU B"},
        "app_version": "1.2.0",
    }
    SessionStart.model_validate({**base, "wall_iso": "2026-10-16T15:00:14.583Z"})
    with pytest.raises(ValidationError):
        SessionStart.model_validate({**base, "wall_iso": "2026-10-16T15:00:14.583"})
