"""Session metrics on the valid grid points.

Smoothness: SPARC (spectral arc length, Balasubramanian et al. 2015) of the
flexion speed profile, computed per detected repetition and averaged. Values
are negative; closer to 0 is smoother.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.analytics.session_report import get_reps_count
from src.processing.settings import GRID_HZ


@dataclass(frozen=True)
class SessionMetrics:
    duration_s: float | None
    max_flexion: float | None
    max_extension: float | None
    max_pronation: float | None
    max_supination: float | None
    rep_count: int | None
    smoothness: float | None

    def to_dict(self) -> dict:
        return asdict(self)


EMPTY_METRICS = SessionMetrics(None, None, None, None, None, None, None)


def sparc(speed: np.ndarray, fs: float, padlevel: int = 4, fc: float = 10.0, amp_th: float = 0.05) -> float:
    """Spectral arc length of a speed profile (Balasubramanian et al. 2015)."""
    speed = np.asarray(speed, dtype=float)
    if speed.size < 4 or not np.any(speed):
        return float("nan")
    nfft = int(2 ** (np.ceil(np.log2(len(speed))) + padlevel))
    freqs = np.arange(0, fs, fs / nfft)
    spectrum = np.abs(np.fft.fft(speed, nfft))
    spectrum = spectrum / spectrum.max()

    keep = freqs <= fc
    freqs, spectrum = freqs[keep], spectrum[keep]
    above = np.flatnonzero(spectrum >= amp_th)
    freqs = freqs[above[0] : above[-1] + 1]
    spectrum = spectrum[above[0] : above[-1] + 1]
    if len(freqs) < 2:
        return 0.0
    df = np.diff(freqs) / (freqs[-1] - freqs[0])
    return float(-np.sum(np.sqrt(df**2 + np.diff(spectrum) ** 2)))


def flexion_speed(t: np.ndarray, fe: np.ndarray) -> np.ndarray:
    return np.abs(np.gradient(fe, t))


def rep_smoothness(angles: pd.DataFrame, reps: list[dict], fs: float = GRID_HZ) -> float | None:
    values = []
    t = angles["t_s"].to_numpy(dtype=float)
    fe = angles["fe_deg"].to_numpy(dtype=float)
    for rep in reps:
        mask = (t >= rep["start_time"]) & (t <= rep["end_time"])
        if mask.sum() < 10:
            continue
        value = sparc(flexion_speed(t[mask], fe[mask]), fs)
        if np.isfinite(value):
            values.append(value)
    return float(np.mean(values)) if values else None


def compute_metrics(angles: pd.DataFrame, from_t_s: float | None = None) -> SessionMetrics:
    """``angles``: grid rows with t_s, fe_deg, ps_deg, valid.

    Duration is the grid span (time both sensors were recorded), not ingestion
    time. Angle metrics use valid points at/after ``from_t_s`` (the zero pose:
    earlier angles are not referenced to the patient's neutral pose).
    """
    if angles.empty:
        return EMPTY_METRICS
    t = angles["t_s"].to_numpy(dtype=float)
    duration = float(t[-1] - t[0])

    used = angles[angles["valid"]]
    if from_t_s is not None:
        used = used[used["t_s"] >= from_t_s]
    if used.empty:
        return SessionMetrics(duration, None, None, None, None, None, None)

    rep_count, reps = get_reps_count(
        used.rename(columns={"fe_deg": "flexion_deg"}),
        time_col="t_s",
        time_scale=1.0,
        return_details=True,
    )
    return SessionMetrics(
        duration_s=duration,
        max_flexion=float(used["fe_deg"].max()),
        max_extension=float(used["fe_deg"].min()),
        max_pronation=float(used["ps_deg"].max()),
        max_supination=float(used["ps_deg"].min()),
        rep_count=int(rep_count),
        smoothness=rep_smoothness(used, reps),
    )
