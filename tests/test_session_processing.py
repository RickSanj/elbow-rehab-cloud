from pathlib import Path

import pandas as pd
import pytest

from src.angle_calculation.calculations import (
    get_sample_rate,
    prepare_final_angle_columns,
    sort_session_samples,
)


def test_sort_session_samples_orders_by_device_clock_when_session_start_is_constant():
    session_start = "2026-03-19T15:49:44.129000+00:00"
    df = pd.DataFrame(
        {
            "session_time_iso": [session_start, session_start, session_start],
            "ingestion_timestamp_iso": [
                "2026-03-19T15:50:57.444000+00:00",
                "2026-03-19T15:50:57.424000+00:00",
                "2026-03-19T15:50:57.434000+00:00",
            ],
            "esp32_ms_A": [1020, 1000, 1010],
            "esp32_ms_B": [2020, 2000, 2010],
        }
    )

    ordered = sort_session_samples(df)

    assert ordered["esp32_ms_A"].tolist() == [1000, 1010, 1020]


def test_get_sample_rate_uses_device_clock_deltas():
    session_start = "2026-03-19T15:49:44.129000+00:00"
    df = pd.DataFrame(
        {
            "session_time_iso": [session_start] * 4,
            "esp32_ms_A": [1000, 1010, 1020, 1030],
        }
    )

    assert get_sample_rate(df) == pytest.approx(100.0)


def test_prepare_final_angle_columns_normalizes_and_preserves_raw_values():
    df = pd.DataFrame(
        {
            "flexion_deg": [-60332.68890502347, 184.29037642707303, 35.0],
            "pronation_deg": [49947.73130267513, -269.50399436809397, 45.0],
        }
    )

    prepared = prepare_final_angle_columns(df)

    assert prepared["flexion_deg"].between(0.0, 150.0).all()
    assert (prepared["pronation_deg"] >= -90.0).all()
    assert (prepared["pronation_deg"] < 90.0).all()
    assert prepared["flexion_deg_raw"].equals(df["flexion_deg"])
    assert prepared["pronation_deg_raw"].equals(df["pronation_deg"])


def test_prepare_final_angle_columns_bounds_existing_regression_session():
    csv_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "20260319_154944"
        / "angles_by_session.csv"
    )
    df = pd.read_csv(csv_path, usecols=["flexion_deg", "pronation_deg"])

    prepared = prepare_final_angle_columns(df)

    assert prepared["flexion_deg"].between(0.0, 150.0).all()
    assert (prepared["pronation_deg"] >= -90.0).all()
    assert (prepared["pronation_deg"] < 90.0).all()
    assert prepared["flexion_deg_raw"].equals(df["flexion_deg"])
    assert prepared["pronation_deg_raw"].equals(df["pronation_deg"])
