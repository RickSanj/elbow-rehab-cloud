"""Coordinate two IMU sensors and log elbow joint angles."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Callable, Dict
import numpy as np

from elbow_rehab.service.angle_calculation.estimator import AlignmentFreeElbowEstimator
from imu import IMUSensor, SensorSnapshot


class ElbowTracker:
    """Manage sensor updates"""

    def __init__(
        self,
        imuA: IMUSensor,
        imuB: IMUSensor,
        sample_rate_hz: float,
    ) -> None:
        self.imuA = imuA
        self.imuA = imuB
        self.estimator = AlignmentFreeElbowEstimator(sample_rate_hz=sample_rate_hz)

    def update(self) -> None:
        sensor_a = self.sensors["A"]
        sensor_b = self.sensors["B"]

        fe_deg, ps_deg = self.estimator.update(
            sensor_a.latest_rotation,
            sensor_a.latest_gyro_rad,
            sensor_b.latest_rotation,
            sensor_b.latest_gyro_rad,
        )

        print(f"FE {fe_deg:7.2f}°, PS {ps_deg:7.2f}°")
