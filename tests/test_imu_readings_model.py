"""Tests for the legacy v1 ImuReadingSchema Pydantic model."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.models.data_models import ImuReadingSchema

RAW_READING = {
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


def test_imu_reading_model_defaults():
    session_time_iso = "2026-01-01T00:00:00Z"

    imu_reading = ImuReadingSchema(**RAW_READING, session_time_iso=session_time_iso)

    assert imu_reading.session_time_iso == session_time_iso
    # user_id and session_id are filled in by the endpoint, not by the model.
    assert imu_reading.user_id is None
    assert imu_reading.session_id is None

    ingested = datetime.fromisoformat(imu_reading.ingestion_timestamp_iso)
    assert (datetime.now(timezone.utc) - ingested).total_seconds() < 5


def test_imu_reading_model_requires_device_timestamps():
    reading = dict(RAW_READING)
    del reading["esp32_ms_A"]
    with pytest.raises(ValidationError):
        ImuReadingSchema(**reading, session_time_iso="2026-01-01T00:00:00Z")
