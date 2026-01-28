"""Zero-pose calibration helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from .settings import DEFAULT_CALIBRATION_DURATION_FRAMES
from elbow_rehab.service.analytics.raw_data_plots import plot_imu_readings, plot_gyro_calibration


def get_gyro_bias(df, gyro_cols, stationary_window):
    if not isinstance(stationary_window, int):
        print("Incorrect stationary_window provided using default") 
        stationary_window = DEFAULT_CALIBRATION_DURATION_FRAMES
    calib_data = df.iloc[:stationary_window][gyro_cols]

    bias = calib_data.mean()
    return bias


def calibrate_gyro(df, window=DEFAULT_CALIBRATION_DURATION_FRAMES):
    gyro_cols_A = ["gx_A", "gy_A", "gz_A"]
    gyro_cols_B = ["gx_B", "gy_B", "gz_B"]
    accel_cols_A = ["ax_A", "ay_A", "az_A"]
    accel_cols_B = ["ax_B", "ay_B", "az_B"]

    calibrated_df = df.copy()

    # Calibrate sensor A
    bias_df = get_gyro_bias(df, gyro_cols_A, window)
    for col in gyro_cols_A:
        calibrated_df[col] = df[col] - bias_df[col]

    # Calibrate sensor B
    bias_df = get_gyro_bias(df, gyro_cols_B, window)
    for col in gyro_cols_B:
        calibrated_df[col] = df[col] - bias_df[col]

    plot_imu_readings(calibrated_df)
    plot_gyro_calibration(df, calibrated_df)
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
