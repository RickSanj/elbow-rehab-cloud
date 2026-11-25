"""Sensor-frame corrections applied during processing, never at ingestion.

Raw packets are stored exactly as the boards send them. Every transform from
board readings to the frame the fusion filters expect lives here, so it can be
changed and old sessions re-processed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.angle_calculation.calibration import ACC_CAL_BIAS, ACC_CAL_SCALE

ACC_COLUMNS = ["ax", "ay", "az"]
GYRO_COLUMNS = ["gx", "gy", "gz"]

# Board mounting: the IMU's z axis is mounted upside down relative to the
# frame assumed by the fusion filters. Rotating the frame by 180 degrees about
# z flips the sign of x and y for both accelerometer and gyroscope (z is
# unchanged). This is the transform v1 applied at ingestion
# ("z axis is swapped").
BOARD_MOUNTING_FLIP_COLUMNS = ("ax", "ay", "gx", "gy")


def apply_board_mounting_transform(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with the board-mounting sign flip applied (ax, ay, gx, gy *= -1)."""
    out = df.copy()
    for column in BOARD_MOUNTING_FLIP_COLUMNS:
        out[column] = -out[column].astype(float)
    return out


def apply_acc_calibration(df: pd.DataFrame) -> pd.DataFrame:
    """Accelerometer bias/scale calibration (same constants as v1)."""
    out = df.copy()
    acc = out[ACC_COLUMNS].to_numpy(dtype=float)
    out[ACC_COLUMNS] = (acc - ACC_CAL_BIAS) @ ACC_CAL_SCALE.T
    return out


def invert_acc_calibration(acc: np.ndarray) -> np.ndarray:
    """Raw accelerometer reading that calibrates to ``acc`` (for synthetic data)."""
    return np.asarray(acc, dtype=float) @ np.linalg.inv(ACC_CAL_SCALE).T + ACC_CAL_BIAS


def to_filter_frame(df: pd.DataFrame) -> pd.DataFrame:
    """All per-sample corrections, in order: mounting flip, then acc calibration."""
    return apply_acc_calibration(apply_board_mounting_transform(df))
