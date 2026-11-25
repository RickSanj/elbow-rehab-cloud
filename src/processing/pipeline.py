"""End-to-end processing of one session (pure: DataFrames in, results out).

raw packets
  -> dedup, split by role                       (load)
  -> segments (reboots) and gaps                (segments)
  -> clock fit per segment, session time        (clock, timebase)
  -> mounting transform + acc calibration       (axes)
  -> gyro bias from the rest window             (bias)
  -> orientation per sensor with real dt        (fusion)
  -> common 100 Hz grid, valid mask             (resample)
  -> zero pose + alignment-free estimator       (here)
  -> metrics and quality                        (metrics, quality)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.angle_calculation.calculations import normalize_fe, normalize_ps
from src.angle_calculation.estimator import AlignmentFreeElbowEstimator
from src.processing.axes import GYRO_COLUMNS, to_filter_frame
from src.processing.bias import estimate_bias, remove_gyro_bias
from src.processing.fusion import run_fusion
from src.processing.load import split_by_role
from src.processing.metrics import EMPTY_METRICS, SessionMetrics, compute_metrics
from src.processing.quaternions import to_matrices
from src.processing.quality import sensor_quality, session_quality
from src.processing.resample import build_grid, resample_sensor
from src.processing.segments import assign_segments
from src.processing.settings import DEFAULT_FILTER, GRID_HZ
from src.processing.timebase import map_to_session_time

ANGLE_COLUMNS = ["t_s", "fe_deg", "ps_deg", "valid"]


@dataclass
class PipelineResult:
    angles: pd.DataFrame  # t_s, fe_deg, ps_deg, valid
    metrics: SessionMetrics
    quality: dict
    quality_ok: bool


def select_zero_pose(zero_pose_uptimes: list[float]) -> float | None:
    """Several zero poses in one session: use the last one (default; confirm)."""
    return max(zero_pose_uptimes) if zero_pose_uptimes else None


def compute_angles(
    grid: np.ndarray,
    quat_a: np.ndarray,
    gyro_a: np.ndarray,
    quat_b: np.ndarray,
    gyro_b: np.ndarray,
    valid: np.ndarray,
    zero_pose_t_s: float | None,
) -> tuple[pd.DataFrame, float | None]:
    """Run the alignment-free estimator over the valid grid points.

    The zero pose is set at the first valid grid point at/after
    ``zero_pose_t_s``. Returns the angle rows and the time it was applied.
    """
    estimator = AlignmentFreeElbowEstimator(GRID_HZ)
    fe = np.full(len(grid), np.nan)
    ps = np.full(len(grid), np.nan)
    zero_applied_at = None

    idx = np.flatnonzero(valid)
    rot_a = to_matrices(quat_a[idx]) if len(idx) else np.empty((0, 3, 3))
    rot_b = to_matrices(quat_b[idx]) if len(idx) else np.empty((0, 3, 3))
    for k, i in enumerate(idx):
        if zero_pose_t_s is not None and zero_applied_at is None and grid[i] >= zero_pose_t_s:
            estimator.set_zero_pose(rot_a[k], rot_b[k])
            zero_applied_at = float(grid[i])
        alpha, beta = estimator.update_angles(rot_a[k], gyro_a[i], rot_b[k], gyro_b[i])
        fe[i] = normalize_fe(float(alpha))
        ps[i] = normalize_ps(float(beta))

    angles = pd.DataFrame({"t_s": grid, "fe_deg": fe, "ps_deg": ps, "valid": valid.astype(bool)})
    return angles, zero_applied_at


def run_pipeline(
    packets: pd.DataFrame,
    *,
    uptime_anchor_s: float,
    stopped_uptime_s: float | None = None,
    zero_pose_uptimes: list[float] | None = None,
    app_stats: dict | None = None,
    filter_type: str = DEFAULT_FILTER,
) -> PipelineResult:
    zero_pose_uptime = select_zero_pose(list(zero_pose_uptimes or []))
    zero_pose_t = zero_pose_uptime - uptime_anchor_s if zero_pose_uptime is not None else None

    by_role = split_by_role(packets)
    prepared: dict[str, pd.DataFrame] = {}
    fused: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    sensors_quality: dict[str, dict] = {}
    for role, raw in by_role.items():
        if raw.empty:
            continue
        segmented, report = assign_segments(raw)
        timed, fits = map_to_session_time(segmented, uptime_anchor_s)
        samples = to_filter_frame(timed)
        bias = estimate_bias(samples, zero_pose_t)
        samples = remove_gyro_bias(samples, bias)
        quaternions, reinit = run_fusion(samples, filter_type=filter_type)
        prepared[role] = samples
        fused[role] = (quaternions, reinit)
        role_stats = (app_stats or {}).get(role)
        sensors_quality[role] = sensor_quality(samples, report, fits, bias, reinit, role_stats)

    if stopped_uptime_s is not None:
        session_duration = stopped_uptime_s - uptime_anchor_s
    elif prepared:
        session_duration = max(float(s["t_s"].max()) for s in prepared.values())
    else:
        session_duration = None

    if "A" in prepared and "B" in prepared:
        a, b = prepared["A"], prepared["B"]
        grid = build_grid(a["t_s"].to_numpy(), b["t_s"].to_numpy())
        on_a = resample_sensor(a["t_s"].to_numpy(), fused["A"][0], a[GYRO_COLUMNS].to_numpy(), a["break_before"].to_numpy(), grid)
        on_b = resample_sensor(b["t_s"].to_numpy(), fused["B"][0], b[GYRO_COLUMNS].to_numpy(), b["break_before"].to_numpy(), grid)
        valid = on_a.valid & on_b.valid
        angles, zero_applied_at = compute_angles(
            grid, on_a.quaternions, on_a.gyro, on_b.quaternions, on_b.gyro, valid, zero_pose_t
        )
        metrics = compute_metrics(angles, from_t_s=zero_applied_at)
    else:
        grid, valid = np.empty(0), np.empty(0, dtype=bool)
        angles = pd.DataFrame({c: pd.Series(dtype=float) for c in ANGLE_COLUMNS})
        angles["valid"] = angles["valid"].astype(bool)
        zero_applied_at = None
        metrics = EMPTY_METRICS

    quality, quality_ok = session_quality(
        sensors_quality,
        grid=grid,
        valid=valid,
        session_duration_s=session_duration,
        zero_pose={
            "events": len(zero_pose_uptimes or []),
            "event_t_s": zero_pose_t,
            "applied_at_t_s": zero_applied_at,
            "applied": zero_applied_at is not None,
            "bias_from_zero_pose": {r: q["bias"]["from_zero_pose"] for r, q in sensors_quality.items()},
        },
    )
    return PipelineResult(angles=angles, metrics=metrics, quality=quality, quality_ok=quality_ok)
