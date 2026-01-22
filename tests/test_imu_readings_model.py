"""
Test the ImuReading Pydantic model
"""

from datetime import datetime, timezone
from elbow_rehab.service.domain.imu_reading import ImuReading


def test_imu_reading_model():
    user_id = "test_user"
    session_time_iso = "2026-01-01T00:00:00Z"

    raw_reading = {
        "esp32_ms_A": 1000,
        "esp32_ms_B": 1000,
        "ax_A": 0.0,
        "ay_A": 0.0,
        "az_A": 0.0,
        "gx_A": 0.0,
        "gy_A": 0.0,
        "gz_A": 0.0,
        "ax_B": 0.0,
        "ay_B": 0.0,
        "az_B": 0.0,
        "gx_B": 0.0,
        "gy_B": 0.0,
        "gz_B": 0.0,
    }

    imu_reading = ImuReading(**raw_reading, user_id=user_id, session_time_iso=session_time_iso)

    # basic fields
    assert imu_reading.user_id == user_id
    assert imu_reading.session_time_iso == session_time_iso

    # derived session_id
    assert imu_reading.session_id == f"{user_id}_{session_time_iso}"

    # ingestion timestamp sanity checks
    assert imu_reading.ingestion_timestamp_iso is not None
    assert isinstance(imu_reading.ingestion_timestamp_iso, datetime)

    # timestamp should be "recent"
    now = datetime.now(timezone.utc)
    delta = now - imu_reading.ingestion_timestamp_iso.replace(tzinfo=timezone.utc)
    assert delta.total_seconds() < 5
