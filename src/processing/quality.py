"""Data-quality figures per sensor and for the session.

The backend is the source of truth for packet loss: ``lost_total`` comes from
seq gaps in the stored packets. The app's own counters (stop event stats) are
used to split it into loss on the BLE link and loss on upload.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.processing.bias import BiasEstimate
from src.processing.clock import ClockFit
from src.processing.segments import SegmentReport
from src.processing.settings import (
    QUALITY_MAX_CLOCK_RESIDUAL_MS,
    QUALITY_MAX_LOSS_PCT,
    QUALITY_MIN_OVERLAP_RATIO,
)


def clean_json(value):
    """Make nested numpy/NaN values JSON-safe."""
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def sensor_quality(
    samples: pd.DataFrame,
    report: SegmentReport,
    fits: dict[int, ClockFit],
    bias: BiasEstimate,
    reinit: np.ndarray,
    app_stats: dict | None,
) -> dict:
    received = report.n_packets
    lost_total = report.lost_total
    expected = received + lost_total
    loss_pct = 100.0 * lost_total / expected if expected else 100.0

    inside = ~samples["break_before"].to_numpy(dtype=bool)
    dt = samples["dt_device_s"].to_numpy(dtype=float)[inside]
    dt = dt[np.isfinite(dt)]
    spans = samples.groupby("segment")["device_s"].agg(lambda s: s.max() - s.min())
    span_s = float(spans.sum())

    main_segment = int(samples.groupby("segment").size().idxmax()) if received else None
    main_fit = fits.get(main_segment) if main_segment is not None else None
    fitted = [f for f in fits.values() if not f.offset_only]

    quality = {
        "received": received,
        "lost_total": lost_total,
        "loss_pct": loss_pct,
        "resets": report.resets,
        "segments": report.n_segments,
        "gaps": report.to_dict()["gaps"],
        "effective_rate_hz": (received - report.n_segments) / span_s if span_s > 0 else None,
        "jitter_ms": float(np.std(dt) * 1e3) if dt.size else None,
        "drift_ppm": main_fit.drift_ppm if main_fit else None,
        "clock_residual_ms": max((f.residual_ms for f in fits.values()), default=None),
        "clock_offset_only": bool(main_fit.offset_only) if main_fit else None,
        "clock_fits": [dict(segment=k, **f.to_dict()) for k, f in sorted(fits.items())],
        "clock_fitted_segments": len(fitted),
        "filter_reinits": int(reinit.sum()) - report.n_segments if len(reinit) else 0,
        "bias": bias.to_dict(),
        "lost_ble": None,
        "lost_upload": None,
        "missing_vs_app": None,
    }
    if app_stats:
        lost_ble = int(app_stats.get("lost_ble", 0))
        expected_from_app = int(app_stats.get("received", 0)) - int(app_stats.get("dropped_overflow", 0))
        quality.update(
            lost_ble=lost_ble,
            lost_upload=lost_total - lost_ble,
            missing_vs_app=expected_from_app - received,
            app_stats=dict(app_stats),
        )
    return quality


def session_quality(
    sensors: dict[str, dict],
    *,
    grid: np.ndarray,
    valid: np.ndarray,
    session_duration_s: float | None,
    zero_pose: dict,
) -> tuple[dict, bool]:
    overlap_s = float(grid[-1] - grid[0]) if len(grid) > 1 else 0.0
    overlap_ratio = overlap_s / session_duration_s if session_duration_s else None

    reasons = []
    for role in ("A", "B"):
        q = sensors.get(role)
        if q is None or q["received"] == 0:
            reasons.append(f"no_data_{role}")
            continue
        if q["loss_pct"] > QUALITY_MAX_LOSS_PCT:
            reasons.append(f"loss_{role}")
        if q["clock_residual_ms"] is not None and q["clock_residual_ms"] > QUALITY_MAX_CLOCK_RESIDUAL_MS:
            reasons.append(f"clock_residual_{role}")
    if overlap_ratio is None or overlap_ratio < QUALITY_MIN_OVERLAP_RATIO:
        reasons.append("overlap")

    quality = {
        "sensors": sensors,
        "overlap_s": overlap_s,
        "session_duration_s": session_duration_s,
        "overlap_ratio": overlap_ratio,
        "grid_points": int(len(grid)),
        "valid_pct": float(100.0 * valid.mean()) if len(valid) else 0.0,
        "zero_pose": zero_pose,
        "thresholds": {
            "max_loss_pct": QUALITY_MAX_LOSS_PCT,
            "min_overlap_ratio": QUALITY_MIN_OVERLAP_RATIO,
            "max_clock_residual_ms": QUALITY_MAX_CLOCK_RESIDUAL_MS,
        },
        "reasons": reasons,
    }
    return clean_json(quality), not reasons
