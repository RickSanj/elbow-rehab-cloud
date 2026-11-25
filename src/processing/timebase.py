"""Map every packet to phone time and session time."""

from __future__ import annotations

import pandas as pd

from src.processing.clock import ClockFit, fit_clock


def map_to_session_time(
    packets: pd.DataFrame, uptime_anchor_s: float
) -> tuple[pd.DataFrame, dict[int, ClockFit]]:
    """Fit one clock per segment and add time columns.

    ``packets`` comes from :func:`assign_segments`. Added columns:
      t_phone_s  a + b * device_s (phone monotonic clock)
      t_s        t_phone_s - uptime_anchor_s (session time, 0 = SessionStart)
      dt_s       device-time step scaled to phone seconds (for the filters)
    """
    out = packets.copy()
    fits: dict[int, ClockFit] = {}
    out["t_phone_s"] = float("nan")
    out["dt_s"] = float("nan")
    for segment, rows in out.groupby("segment", sort=True):
        fit = fit_clock(rows["device_s"].to_numpy(), rows["phone_rx_s"].to_numpy())
        fits[int(segment)] = fit
        out.loc[rows.index, "t_phone_s"] = fit.to_phone(rows["device_s"].to_numpy())
        out.loc[rows.index, "dt_s"] = rows["dt_device_s"].to_numpy() * (1.0 + fit.drift)
    out["t_s"] = out["t_phone_s"] - float(uptime_anchor_s)
    return out, fits
