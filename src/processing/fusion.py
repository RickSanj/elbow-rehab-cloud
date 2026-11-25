"""Per-sensor orientation fusion with the real sample spacing.

* Each step uses dt from device_ts_us (scaled by the clock drift), not a
  fixed 1 / sample_rate, so jitter and single lost packets are integrated
  correctly.
* At a segment start the filter is initialized from the accelerometer.
* After a device-time gap > GAP_THRESHOLD_S nothing is integrated across the
  gap: the tilt is re-initialized from the accelerometer and the heading of
  the last estimate is kept (resetting the heading would change the relative
  heading of the two sensors and corrupt the elbow angles). These samples are
  marked ``reinit``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.angle_calculation.calculations import get_filter
from src.processing.axes import ACC_COLUMNS, GYRO_COLUMNS
from src.processing.quaternions import keep_heading
from src.processing.settings import DEFAULT_FILTER, GRID_HZ


def run_fusion(
    samples: pd.DataFrame,
    filter_type: str = DEFAULT_FILTER,
    nominal_rate_hz: float = GRID_HZ,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (quaternions [N, 4] wxyz, reinit flags [N]) for one sensor."""
    acc = samples[ACC_COLUMNS].to_numpy(dtype=float)
    gyro = samples[GYRO_COLUMNS].to_numpy(dtype=float)
    dt = samples["dt_s"].to_numpy(dtype=float)
    segment = samples["segment"].to_numpy()
    reinit_before = samples["reinit_before"].to_numpy(dtype=bool)

    n = len(samples)
    quaternions = np.empty((n, 4), dtype=float)
    reinit = np.zeros(n, dtype=bool)
    filt = get_filter(filter_type, nominal_rate_hz)

    for i in range(n):
        new_segment = i == 0 or segment[i] != segment[i - 1]
        if new_segment:
            filt.reset(filt.initial_quaternion(acc[i]))
            reinit[i] = True
        elif reinit_before[i] or not np.isfinite(dt[i]) or dt[i] <= 0:
            filt.reset(keep_heading(filt.quaternion, filt.initial_quaternion(acc[i])))
            reinit[i] = True
        else:
            filt.update(acc[i], gyro[i], dt=dt[i])
        quaternions[i] = filt.quaternion
    return quaternions, reinit
