"""Segments (board reboots) and gaps (lost packets) per sensor.

* Packets are first put in arrival order (phone_rx_s, then seq). A new
  segment starts when seq or device_ts_us decreases: the board rebooted and
  its counters restarted. A reboot is not packet loss.
* Inside a segment, packets are ordered by seq; a seq step > 1 is a gap of
  (step - 1) lost packets.
* seq is a uint32 on the board; wrap-around is not handled (it takes over a
  year at 100 Hz).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from src.processing.settings import GAP_THRESHOLD_S


@dataclass(frozen=True)
class Gap:
    segment: int
    after_seq: int
    before_seq: int
    lost: int
    device_start_s: float
    device_end_s: float


@dataclass
class SegmentReport:
    n_packets: int = 0
    n_segments: int = 0
    resets: int = 0
    lost_total: int = 0
    gaps: list[Gap] = field(default_factory=list)

    def to_dict(self, max_gaps: int = 50) -> dict:
        return {
            "n_packets": self.n_packets,
            "n_segments": self.n_segments,
            "resets": self.resets,
            "lost_total": self.lost_total,
            "n_gaps": len(self.gaps),
            "gaps": [asdict(g) for g in self.gaps[:max_gaps]],
        }


def assign_segments(df: pd.DataFrame, gap_threshold_s: float = GAP_THRESHOLD_S) -> tuple[pd.DataFrame, SegmentReport]:
    """Return the packets of one sensor sorted by (segment, seq) plus a report.

    Added columns:
      segment         0, 1, ... (increments at each board reboot)
      device_s        device_ts_us in seconds
      seq_step        seq difference to the previous packet in the segment
      dt_device_s     device time difference to the previous packet
      break_before    True at a segment start, after lost packets, or after a
                      device-time step > gap_threshold_s: nothing may be
                      integrated or interpolated across this boundary
      reinit_before   True at a segment start or after a device-time step >
                      gap_threshold_s: the filter is re-initialized here
    """
    if df.empty:
        out = df.copy()
        for column in ("segment", "device_s", "seq_step", "dt_device_s", "break_before", "reinit_before"):
            out[column] = pd.Series(dtype=float)
        return out, SegmentReport()

    arrival = df.sort_values(["phone_rx_s", "seq", "device_ts_us"], kind="mergesort").reset_index(drop=True)
    seq = arrival["seq"].to_numpy(dtype=np.int64)
    ts = arrival["device_ts_us"].to_numpy(dtype=np.int64)
    restart = np.zeros(len(arrival), dtype=bool)
    restart[1:] = (np.diff(seq) < 0) | (np.diff(ts) < 0)
    arrival["segment"] = np.cumsum(restart)

    ordered = (
        arrival.sort_values(["segment", "seq", "device_ts_us"], kind="mergesort")
        .drop_duplicates(subset=["segment", "seq"], keep="first")
        .reset_index(drop=True)
    )

    ordered["device_s"] = ordered["device_ts_us"].to_numpy(dtype=np.int64) / 1e6
    first_in_segment = ordered["segment"].ne(ordered["segment"].shift())
    seq_step = ordered["seq"].diff()
    dt = ordered["device_s"].diff()
    seq_step[first_in_segment] = np.nan
    dt[first_in_segment] = np.nan
    ordered["seq_step"] = seq_step
    ordered["dt_device_s"] = dt

    lost_gap = seq_step > 1
    time_gap = dt > gap_threshold_s
    ordered["reinit_before"] = first_in_segment | time_gap
    ordered["break_before"] = first_in_segment | time_gap | lost_gap

    report = SegmentReport(
        n_packets=len(ordered),
        n_segments=int(ordered["segment"].max()) + 1,
        resets=int(ordered["segment"].max()),
    )
    for idx in np.flatnonzero(lost_gap.to_numpy()):
        lost = int(seq_step.iloc[idx]) - 1
        report.lost_total += lost
        report.gaps.append(
            Gap(
                segment=int(ordered["segment"].iloc[idx]),
                after_seq=int(ordered["seq"].iloc[idx - 1]),
                before_seq=int(ordered["seq"].iloc[idx]),
                lost=lost,
                device_start_s=float(ordered["device_s"].iloc[idx - 1]),
                device_end_s=float(ordered["device_s"].iloc[idx]),
            )
        )
    return ordered, report
