from ahrs.filters import Madgwick
import numpy as np
from .base_filter import BaseFilter


class MadgwickFilter(BaseFilter):
    """
    gyr (numpy.ndarray) - N-by-3 array with measurements of angular velocity in rad/s
    acc (numpy.ndarray) - N-by-3 array with measurements of acceleration in in m/s^2
    gain (float, default: {0.033}) - Filter gain. Defaults to 0.033 for IMU implementations.
    """

    def __init__(self, frequency, beta=0.033):
        super().__init__()
        self.madgwick = Madgwick(frequency=frequency, beta=beta)

    def update(self, acc_data, gyro_data) -> np.ndarray:
        """
        Update orientation using Madgwick filter.
        Keeps quaternion in [w, x, y, z] internally.
        """
        self.quaternion = self.madgwick.updateIMU(
            self.quaternion, gyr=gyro_data, acc=acc_data
        )
        return self.quaternion
