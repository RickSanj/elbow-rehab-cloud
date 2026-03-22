"""Helpers for comparing AHRS filter outputs on shared sessions."""

from __future__ import annotations

from collections.abc import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from src.angle_calculation.calibration import calibrate_gyro_acc
from src.angle_calculation.calculations import ElbowTracker
from src.angle_calculation.settings import (
    DEFAULT_ESTIMATOR,
    DEFAULT_SAMPLE_RATE_HZ,
)

ATTITUDE_COLS = ("roll_deg", "pitch_deg", "yaw_deg")
TIME_COLUMN_CANDIDATES = (
    "ingestion_timestamp_iso",
    # "timestamp",
    # "session_time_iso",
    # "esp32_ms_A",
    # "esp32_ms_B",
)


def _select_time_column(df: pd.DataFrame, *, preferred: str | None) -> str:
    if preferred:
        if preferred not in df.columns:
            raise KeyError(f"time_column '{preferred}' not present in dataframe")
        return preferred

    for candidate in TIME_COLUMN_CANDIDATES:
        if candidate in df.columns:
            return candidate
    raise KeyError(
        "Unable to infer a time column. Provide one via the `time_column` parameter."
    )


def _normalize_time_axis(
    series: pd.Series, fallback: pd.Series | None = None
) -> pd.Series:
    if is_numeric_dtype(series):
        base = None
        if fallback is not None:
            parsed = pd.to_datetime(fallback, errors="coerce")
            if parsed.notna().any():
                base = parsed.iloc[0]
        if base is None:
            base = pd.Timestamp("1970-01-01")

        delta = series - series.iloc[0]
        return base + pd.to_timedelta(delta, unit="ms")

    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().any():
        return parsed

    raise ValueError(
        "Could not convert the provided time column to datetimes. "
        "Pass a different column via `time_column`."
    )


def collect_filter_orientations(
    session_df: pd.DataFrame,
    *,
    filter_types: Sequence[str] = ("madgwick", "ekf", "mahony"),
    estimator_type: str = DEFAULT_ESTIMATOR,
    sample_rate: float = DEFAULT_SAMPLE_RATE_HZ,
    attitude_cols: Sequence[str] = ATTITUDE_COLS,
    time_column: str | None = None,
) -> pd.DataFrame:
    """Return stacked roll/pitch/yaw trajectories for several filter choices."""

    if not filter_types:
        raise ValueError("filter_types must contain at least one entry")

    resolved_time_column = _select_time_column(session_df, preferred=time_column)
    base_cols = list(
        dict.fromkeys(
            [
                resolved_time_column,
                "session_time_iso",
                *attitude_cols,
            ]
        )
    )
    calibrated = calibrate_gyro_acc(session_df, visualize=False)
    runs: list[pd.DataFrame] = []

    for filter_name in filter_types:
        tracker = ElbowTracker(
            estimator_type=estimator_type,
            filter_type=filter_name,
            sample_rate=sample_rate,
        )
        processed = tracker.process_session_angles(
            session_df,
            calibrated_session_df=calibrated,
            persist=False,
            visualize=False,
        )

        missing = [col for col in base_cols if col not in processed.columns]
        if missing:
            raise KeyError(
                f"Missing expected columns in processed DataFrame: {missing}"
            )

        subset = processed[base_cols].copy()
        subset["sample_index"] = np.arange(len(subset), dtype=float)
        subset["filter"] = filter_name
        runs.append(subset)

    comparison_df = pd.concat(runs, ignore_index=True)
    fallback_series = (
        comparison_df["session_time_iso"]
        if "session_time_iso" in comparison_df.columns
        else None
    )
    comparison_df["timestamp"] = _normalize_time_axis(
        comparison_df[resolved_time_column], fallback_series
    )
    comparison_df["elapsed_seconds"] = (
        comparison_df["sample_index"] / float(sample_rate)
    )
    return comparison_df


def plot_filter_orientation_comparison(
    session_df: pd.DataFrame,
    *,
    filter_types: Sequence[str] = ("madgwick", "ekf", "mahony"),
    estimator_type: str = DEFAULT_ESTIMATOR,
    sample_rate: float = DEFAULT_SAMPLE_RATE_HZ,
    attitude_cols: Sequence[str] = ATTITUDE_COLS,
    time_column: str | None = None,
    figsize: tuple[float, float] = (12.0, 8.0),
):
    """Plot roll/pitch/yaw curves comparing different filter outputs."""

    comparison_df = collect_filter_orientations(
        session_df,
        filter_types=filter_types,
        estimator_type=estimator_type,
        sample_rate=sample_rate,
        attitude_cols=attitude_cols,
        time_column=time_column,
    )

    fig, axes = plt.subplots(len(attitude_cols), 1, figsize=figsize, sharex=True)
    if len(attitude_cols) == 1:
        axes = [axes]
    else:
        axes = np.asarray(axes).ravel()

    used_elapsed_axis = False
    for idx, col in enumerate(attitude_cols):
        ax = axes[idx]
        for filter_name in filter_types:
            subset = (
                comparison_df[comparison_df["filter"] == filter_name]
                .sort_values("timestamp")
            )
            x_data = subset["timestamp"]
            if x_data.nunique() <= 1 and "elapsed_seconds" in subset:
                x_data = subset["elapsed_seconds"]
                used_elapsed_axis = True
            ax.plot(
                x_data,
                subset[col],
                label=filter_name if idx == 0 else None,
            )

        label = col.replace("_deg", "").replace("_", " ").title()
        ax.set_ylabel(f"{label} [deg]")
        ax.set_title(label)

    axes[-1].set_xlabel("Elapsed Time [s]" if used_elapsed_axis else "Time")
    axes[0].legend(title="Filter", loc="best")
    fig.tight_layout()
    return fig, axes, comparison_df
