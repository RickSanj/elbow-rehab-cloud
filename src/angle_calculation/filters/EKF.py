from ahrs.filters import EKF
import numpy as np
from .base_filter import BaseFilter


class ExtendedKalmanFilter(BaseFilter):
    """
    gyr (numpy.ndarray) - N-by-3 array with measurements of angular velocity in rad/s
    acc (numpy.ndarray) - N-by-3 array with measurements of acceleration in in m/s^2
    """

    def __init__(self, frequency):
        super().__init__()
        self.ekf = EKF(frequency=frequency)

    def update(self, acc_data, gyro_data) -> np.ndarray:
        """
        Update orientation using Madgwick filter.
        Keeps quaternion in [w, x, y, z] internally.
        """
        self.quaternion = self.ekf.update(
            q=self.quaternion, gyr=gyro_data, acc=acc_data
        )
        return self.quaternion
