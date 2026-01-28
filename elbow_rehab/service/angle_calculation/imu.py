"""Helpers for handling BLE packets from a single ESP32 IMU."""

import os
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from numpy.typing import NDArray

from filters.base_filter import BaseFilter
from filters.EKF import ExtendedKalmanFilter
from filters.Madgwick import MadgwickFilter

from preprocess import preprocess
from settings import DEFAULT_SAMPLE_RATE_HZ #todo remove global var from heere, default value should be initialized in calculations


@dataclass(frozen=True)
class SensorSnapshot:
    """Lightweight container for the latest reading coming from one sensor."""

    timestamp_ms: int
    acc_m_s2: Tuple[float, float, float]
    gyr_rad_s: Tuple[float, float, float]


@dataclass
class IMUSensor:
    label: str
    sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ

    def __post_init__(self) -> None:
        self.sample_rate_hz = float(self.sample_rate_hz)
        if self.sample_rate_hz <= 0.0:
            raise ValueError("sample_rate_hz must be positive")
        self.sample_period = 1.0 / self.sample_rate_hz

        self.filter_name, self.filter = self._select_filter()

        self.latest_rotation: Optional[NDArray[np.float64]] = None
        self.latest_gyro_rad: Optional[NDArray[np.float64]] = None
        self.latest_snapshot: Optional[SensorSnapshot] = None

    def _select_filter(self) -> Tuple[str, BaseFilter]:
        env_key = f"ORIENTATION_FILTER_{self.label}"
        default = os.getenv("ORIENTATION_FILTER", "madgwick")
        name = os.getenv(env_key, default).strip().lower()

        if name == "madgwick":
            return name, MadgwickFilter(DEFAULT_SAMPLE_RATE_HZ)
        if name != "ekf":
            print(f"⚠️  Unknown filter name '{name}'; falling back to Madgwick.")
            name = "ekf"
        return name, MadgwickFilter(DEFAULT_SAMPLE_RATE_HZ)

    def process_packet(self, payload: bytearray) -> None:
        """Decode a BLE packet and update the internal orientation state."""

        text = payload.decode("utf-8").strip()
        parts = text.split(",")
        if len(parts) < 7:
            raise ValueError("Expected timestamp + 6 sensor values.")

        esp_ms = int(parts[0])
        ax, ay, az, gx, gy, gz = (float(value) for value in parts[1:7])

        raw_acc = np.array([ax, ay, az], dtype=float)
        raw_gyr = np.array([gx, gy, gz], dtype=float)

        processed_acc, processed_gyro = preprocess(raw_acc, raw_gyr)

        self.filter.update(processed_acc, processed_gyro)

        self.latest_rotation = self.filter.rotation_matrix()
        self.latest_gyro_rad = processed_gyro
        self.latest_snapshot = SensorSnapshot(
            timestamp_ms=esp_ms,
            acc_m_s2=tuple(float(x) for x in processed_acc),
            gyr_rad_s=tuple(float(x) for x in processed_gyro),
        )

    @property
    def is_ready(self) -> bool:
        return (
            self.latest_rotation is not None
            and self.latest_gyro_rad is not None
            and self.latest_snapshot is not None
        )
