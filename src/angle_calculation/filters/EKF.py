from ahrs.filters import EKF
import numpy as np
from .base_filter import BaseFilter


class ExtendedKalmanFilter(BaseFilter):
    """
    gyr (numpy.ndarray) - N-by-3 array with measurements of angular velocity in rad/s
    acc (numpy.ndarray) - N-by-3 array with measurements of acceleration in in m/s^2

    Runs in the ahrs default NED frame: a level, static sensor reads az = -g.
    """

    GRAVITY_SIGN = -1.0

    def __init__(self, frequency):
        super().__init__()
        self.ekf = EKF(frequency=frequency)

    def _impl(self):
        return self.ekf

    def update(self, acc_data, gyro_data, dt: float | None = None) -> np.ndarray:
        """
        Update orientation using the extended Kalman filter.
        Keeps quaternion in [w, x, y, z] internally.
        """
        self.set_dt(dt)
        self.quaternion = self.ekf.update(
            q=self.quaternion, gyr=gyro_data, acc=acc_data
        )
        return self.quaternion
