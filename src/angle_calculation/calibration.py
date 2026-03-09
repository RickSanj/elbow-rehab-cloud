"""Zero-pose calibration helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from .settings import DEFAULT_CALIBRATION_DURATION_FRAMES
from src.analytics.raw_data_plots import (
    plot_imu_readings,
    plot_gyro_calibration,
    plot_acc_calibration,
)


import numpy as np


def get_acc_bias(df, cols, stationary_window, g_ms2=9.81):
    """
    Estimate accelerometer bias (m/s^2) from a stationary window.

    Assumes:
    - accelerometer outputs are in m/s^2
    - sensor is stationary during the window
    - scale is already calibrated
    """

    if not isinstance(stationary_window, int):
        print("Incorrect stationary_window provided, using default")
        stationary_window = DEFAULT_CALIBRATION_DURATION_FRAMES

    calib = df.iloc[:stationary_window][cols]
    a_mean = calib.mean(axis=0)
    norm = np.linalg.norm(a_mean)

    # Stationarity / sanity check
    if not (0.8 * g_ms2 <= norm <= 1.2 * g_ms2):
        raise ValueError("Not stationary or accelerometer scale is incorrect")

    g_vec = (a_mean / norm) * g_ms2
    bias = a_mean - g_vec
    return bias


def get_gyro_bias(df, cols, stationary_window):
    if not isinstance(stationary_window, int):
        print("Incorrect stationary_window provided using default")
        stationary_window = DEFAULT_CALIBRATION_DURATION_FRAMES
    calib_data = df.iloc[:stationary_window][cols]

    bias = calib_data.mean()
    return bias


def calibrate_gyro_acc(df, window=DEFAULT_CALIBRATION_DURATION_FRAMES):
    gyro_cols_A = ["gx_A", "gy_A", "gz_A"]
    gyro_cols_B = ["gx_B", "gy_B", "gz_B"]
    accel_cols_A = ["ax_A", "ay_A", "az_A"]
    accel_cols_B = ["ax_B", "ay_B", "az_B"]

    b = np.array([0.43000557, 0.71119793, -0.38784999])
    S = np.array(
        [
            [1.00430962, 0.0, 0.0],
            [0.0, 0.99287692, 0.0],
            [0.0, 0.0, 0.99845489],
        ]
    )

    calibrated_df = df.copy()

    # Calibrate sensor A
    # Gyroscope
    bias_df = get_gyro_bias(df, gyro_cols_A, window)
    for col in gyro_cols_A:
        calibrated_df[col] = df[col] - bias_df[col]

    # Accelerometer
    a_raw = df[accel_cols_A].values
    a_cal = (a_raw - b) @ S.T
    calibrated_df[accel_cols_A] = a_cal
    # print("Calibrate sensor A Accelerometer")
    # bias_df = get_acc_bias(df, accel_cols_A, window)
    # print(bias_df)
    # for col in accel_cols_A:
    #     calibrated_df[col] = df[col] - bias_df[col]

    # Calibrate sensor B
    # Gyroscope
    bias_df = get_gyro_bias(df, gyro_cols_B, window)
    for col in gyro_cols_B:
        calibrated_df[col] = df[col] - bias_df[col]

    # Accelerometer
    b_raw = df[accel_cols_B].values
    b_cal = (b_raw - b) @ S.T
    calibrated_df[accel_cols_B] = b_cal

    # print("Calibrate sensor B Accelerometer")
    # bias_df = get_acc_bias(df, accel_cols_B, window)
    # print(bias_df)
    # for col in accel_cols_B:
    #     calibrated_df[col] = df[col] - bias_df[col]

    plot_imu_readings(calibrated_df)
    plot_gyro_calibration(df, calibrated_df)
    plot_acc_calibration(df, calibrated_df)
    return calibrated_df


# @dataclass
# class CalibrationResult:
#     """Holds calibrated angles after offset removal."""

#     fe: float
#     ps: float


# class CalibrationManager:
#     """Collect samples over a fixed window to estimate zero offsets."""

#     def __init__(self, *, duration_s: float = 5.0) -> None:
#         if duration_s <= 0:
#             raise ValueError("duration_s must be positive")

#         self._duration = float(duration_s)
#         self._start: float | None = None
#         self._count = 0
#         self._sum_fe = 0.0
#         self._sum_ps = 0.0
#         self._offset_fe = 0.0
#         self._offset_ps = 0.0
#         self._completed = False

#     @property
#     def is_completed(self) -> bool:
#         return self._completed

#     @property
#     def is_calibrating(self) -> bool:
#         return not self._completed

#     @property
#     def offsets(self) -> tuple[float, float]:
#         return self._offset_fe, self._offset_ps

#     def reset(self) -> None:
#         self._start = None
#         self._count = 0
#         self._sum_fe = 0.0
#         self._sum_ps = 0.0
#         self._offset_fe = 0.0
#         self._offset_ps = 0.0
#         self._completed = False

#     def apply(self, fe: float, ps: float) -> CalibrationResult | None:
#         now = time.monotonic()
#         if self._start is None:
#             self._start = now
#             print(f"🛠️ Starting zero-pose calibration ({self._duration:.1f}s)...")

#         if not self._completed:
#             self._sum_fe += fe
#             self._sum_ps += ps
#             self._count += 1
#             if now - self._start >= self._duration:
#                 self._offset_fe = self._sum_fe / self._count
#                 self._offset_ps = self._sum_ps / self._count
#                 self._completed = True
#                 print(
#                     "✅ Calibration complete: offsets "
#                     f"FE={self._offset_fe:.2f}°, PS={self._offset_ps:.2f}°."
#                 )
#                 return CalibrationResult(
#                     fe=fe - self._offset_fe,
#                     ps=ps - self._offset_ps,
#                 )
#             return None

#         return CalibrationResult(
#             fe=fe - self._offset_fe,
#             ps=ps - self._offset_ps,
#         )
