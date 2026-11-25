"""Put both sensors on one 100 Hz grid over their common time span.

Orientation is SLERP-interpolated, gyro linearly. A grid point is valid only
when, for both sensors, the two neighbouring samples are consecutive (no lost
packets, no time gap, same segment). There is no interpolation across gaps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.processing.quaternions import slerp
from src.processing.settings import GRID_HZ


@dataclass
class SensorOnGrid:
    quaternions: np.ndarray  # [M, 4] wxyz (NaN where invalid)
    gyro: np.ndarray  # [M, 3]
    valid: np.ndarray  # [M]


def build_grid(t_a: np.ndarray, t_b: np.ndarray, hz: float = GRID_HZ) -> np.ndarray:
    """Grid over the time overlap of both sensors (empty if they do not overlap)."""
    if len(t_a) == 0 or len(t_b) == 0:
        return np.empty(0)
    start = max(float(np.min(t_a)), float(np.min(t_b)))
    end = min(float(np.max(t_a)), float(np.max(t_b)))
    if end <= start:
        return np.empty(0)
    step = 1.0 / hz
    # Grid points are multiples of the step (stable across re-runs).
    first = np.ceil(start * hz - 1e-9) / hz
    count = int(np.floor((end - first) * hz + 1e-9)) + 1
    return first + np.arange(count) * step


def resample_sensor(
    t: np.ndarray,
    quaternions: np.ndarray,
    gyro: np.ndarray,
    break_before: np.ndarray,
    grid: np.ndarray,
) -> SensorOnGrid:
    t = np.asarray(t, dtype=float)
    m = len(grid)
    out_q = np.full((m, 4), np.nan)
    out_g = np.full((m, 3), np.nan)
    valid = np.zeros(m, dtype=bool)
    if len(t) < 2 or m == 0:
        return SensorOnGrid(out_q, out_g, valid)

    # Interval (i, i+1) is usable when time increases and sample i+1 does not
    # start a new segment / follow a gap.
    usable = (np.diff(t) > 0) & ~np.asarray(break_before, dtype=bool)[1:]

    i = np.searchsorted(t, grid, side="right") - 1
    # A grid point exactly on the last sample belongs to the last interval.
    i = np.where(grid == t[-1], len(t) - 2, i)
    inside = (i >= 0) & (i < len(t) - 1)
    idx = np.clip(i, 0, len(t) - 2)
    ok = inside & usable[idx]

    lo, hi = idx[ok], idx[ok] + 1
    u = (grid[ok] - t[lo]) / (t[hi] - t[lo])
    out_q[ok] = slerp(quaternions[lo], quaternions[hi], u)
    out_g[ok] = gyro[lo] + (gyro[hi] - gyro[lo]) * u[:, None]
    valid[ok] = True
    return SensorOnGrid(out_q, out_g, valid)
