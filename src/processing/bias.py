"""Gyroscope bias from a rest window (instead of "the first N samples").

With a zero-pose event the patient holds still around that moment: search
[zero_pose - 3 s, zero_pose + 3 s] for the 2-3 s window with the lowest gyro
variance. Without a zero pose, use the lowest-variance 2 s window in the first
30 s and flag ``from_zero_pose = False``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.processing.axes import ACC_COLUMNS, GYRO_COLUMNS
from src.processing.settings import (
    ACC_REST_TOLERANCE,
    GRAVITY_MS2,
    GRID_HZ,
    NO_ZERO_POSE_SEARCH_S,
    NO_ZERO_POSE_WINDOW_S,
    REST_MAX_GYRO_STD,
    REST_MIN_SAMPLE_FRACTION,
    REST_WINDOW_LENGTHS_S,
    REST_WINDOW_STEP_S,
    ZERO_POSE_SEARCH_HALF_WIDTH_S,
)


@dataclass(frozen=True)
class BiasEstimate:
    gyro_bias: tuple[float, float, float]
    found: bool  # False -> no usable rest window, bias = 0 (see `reason`)
    from_zero_pose: bool
    window_start_s: float | None = None
    window_end_s: float | None = None
    gyro_std: float | None = None  # rad/s, mean per-axis std in the window
    acc_norm: float | None = None  # |mean acc| in the window (m/s^2)
    acc_rest_ok: bool | None = None  # acc_norm within tolerance of g
    reason: str | None = None  # why no bias was applied

    def to_dict(self) -> dict:
        return asdict(self)


def find_rest_window(
    t: np.ndarray,
    gyro: np.ndarray,
    breaks: np.ndarray,
    search_start: float,
    search_end: float,
    lengths=REST_WINDOW_LENGTHS_S,
    step: float = REST_WINDOW_STEP_S,
    sample_rate_hz: float = GRID_HZ,
) -> tuple[float, float, float] | None:
    """Lowest-variance window (start, end, score) inside [search_start, search_end]."""
    best = None
    for length in lengths:
        min_samples = REST_MIN_SAMPLE_FRACTION * length * sample_rate_hz
        start = search_start
        while start + length <= search_end + 1e-9:
            lo, hi = np.searchsorted(t, [start, start + length])
            if hi - lo >= min_samples and not breaks[lo + 1 : hi].any():
                score = float(np.mean(np.var(gyro[lo:hi], axis=0)))
                # Prefer the longer window on (near) ties.
                if best is None or score < best[2] * 0.999:
                    best = (start, start + length, score)
            start += step
    return best


def estimate_bias(samples: pd.DataFrame, zero_pose_t_s: float | None) -> BiasEstimate:
    """``samples``: one sensor, ordered, with t_s, break_before and filter-frame gyro/acc."""
    t = samples["t_s"].to_numpy(dtype=float)
    gyro = samples[GYRO_COLUMNS].to_numpy(dtype=float)
    acc = samples[ACC_COLUMNS].to_numpy(dtype=float)
    breaks = samples["break_before"].to_numpy(dtype=bool)
    if len(t) == 0:
        return BiasEstimate(gyro_bias=(0.0, 0.0, 0.0), found=False, from_zero_pose=False, reason="no_samples")

    window = None
    from_zero_pose = False
    if zero_pose_t_s is not None:
        window = find_rest_window(
            t,
            gyro,
            breaks,
            zero_pose_t_s - ZERO_POSE_SEARCH_HALF_WIDTH_S,
            zero_pose_t_s + ZERO_POSE_SEARCH_HALF_WIDTH_S,
        )
        from_zero_pose = window is not None
    if window is None:
        window = find_rest_window(
            t, gyro, breaks, t[0], t[0] + NO_ZERO_POSE_SEARCH_S, lengths=(NO_ZERO_POSE_WINDOW_S,)
        )
    if window is None:
        return BiasEstimate(gyro_bias=(0.0, 0.0, 0.0), found=False, from_zero_pose=False, reason="no_window")

    start, end, _ = window
    lo, hi = np.searchsorted(t, [start, end])
    bias = gyro[lo:hi].mean(axis=0)
    gyro_std = float(np.mean(gyro[lo:hi].std(axis=0)))
    acc_norm = float(np.linalg.norm(acc[lo:hi].mean(axis=0)))
    acc_rest_ok = abs(acc_norm - GRAVITY_MS2) <= ACC_REST_TOLERANCE * GRAVITY_MS2
    still = gyro_std <= REST_MAX_GYRO_STD and acc_rest_ok
    return BiasEstimate(
        gyro_bias=tuple(float(v) for v in bias) if still else (0.0, 0.0, 0.0),
        found=still,
        from_zero_pose=from_zero_pose,
        window_start_s=float(start),
        window_end_s=float(end),
        gyro_std=gyro_std,
        acc_norm=acc_norm,
        acc_rest_ok=acc_rest_ok,
        reason=None if still else "no_rest_window",
    )


def remove_gyro_bias(samples: pd.DataFrame, bias: BiasEstimate) -> pd.DataFrame:
    out = samples.copy()
    out[GYRO_COLUMNS] = out[GYRO_COLUMNS].to_numpy(dtype=float) - np.asarray(bias.gyro_bias)
    return out
