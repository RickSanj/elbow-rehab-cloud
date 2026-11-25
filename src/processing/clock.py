"""Board clock -> phone clock mapping, per sensor and segment.

Model: phone_rx_s = device_s + offset + drift * (device_s - device_ref_s) + delay

where delay >= 0 is the BLE/OS latency. In every window of CLOCK_WINDOW_S the
packet with the smallest (phone_rx_s - device_s) had the least delay; those
minima lie close to the line ``offset + drift * (device_s - ref)``. A robust
Theil-Sen line through the minima gives offset and drift.

The fitted offset includes the minimum latency of the link (typically a
fraction of a millisecond to a few ms). It is common to both sensors when
both links behave alike, so it mostly cancels in the A/B alignment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.stats import theilslopes

from src.processing.settings import CLOCK_MAX_FIT_WINDOWS, CLOCK_MIN_WINDOWS, CLOCK_WINDOW_S


@dataclass(frozen=True)
class ClockFit:
    offset_s: float  # phone - device at device_ref_s
    drift: float  # dimensionless rate difference (phone/device - 1)
    device_ref_s: float
    n_windows: int
    offset_only: bool  # too few windows for a drift estimate
    residual_ms: float  # robust spread of the window minima around the fit
    residual_p95_ms: float

    @property
    def drift_ppm(self) -> float:
        return self.drift * 1e6

    def to_phone(self, device_s) -> np.ndarray:
        device_s = np.asarray(device_s, dtype=float)
        return device_s + self.offset_s + self.drift * (device_s - self.device_ref_s)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["drift_ppm"] = self.drift_ppm
        return d


def window_minima(device_s: np.ndarray, phone_rx_s: np.ndarray, window_s: float) -> tuple[np.ndarray, np.ndarray]:
    """(device_s, phone - device) of the least-delayed packet per window."""
    diff = phone_rx_s - device_s
    window = np.floor((device_s - device_s.min()) / window_s).astype(np.int64)
    order = np.lexsort((diff, window))  # by window, then smallest diff first
    first = np.ones(len(order), dtype=bool)
    first[1:] = window[order][1:] != window[order][:-1]
    picked = order[first]
    return device_s[picked], diff[picked]


def fit_clock(
    device_s,
    phone_rx_s,
    *,
    window_s: float = CLOCK_WINDOW_S,
    min_windows: int = CLOCK_MIN_WINDOWS,
    max_fit_windows: int = CLOCK_MAX_FIT_WINDOWS,
) -> ClockFit:
    device_s = np.asarray(device_s, dtype=float)
    phone_rx_s = np.asarray(phone_rx_s, dtype=float)
    if device_s.size == 0:
        raise ValueError("cannot fit a clock without packets")

    x, d = window_minima(device_s, phone_rx_s, window_s)
    ref = float(np.median(x))

    if len(x) >= min_windows:
        step = max(1, int(np.ceil(len(x) / max_fit_windows)))
        slope, intercept, _, _ = theilslopes(d[::step], x[::step] - ref)
        offset, drift, offset_only = float(intercept), float(slope), False
    else:
        offset, drift, offset_only = float(np.median(d)), 0.0, True

    residual = d - (offset + drift * (x - ref))
    mad = float(np.median(np.abs(residual - np.median(residual))))
    return ClockFit(
        offset_s=offset,
        drift=drift,
        device_ref_s=ref,
        n_windows=int(len(x)),
        offset_only=offset_only,
        residual_ms=1.4826 * mad * 1e3,
        residual_p95_ms=float(np.percentile(np.abs(residual), 95)) * 1e3,
    )
