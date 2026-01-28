from ahrs.filters import Mahony
import numpy as np
from filters.base_filter import BaseFilter


class MahonyFilter(BaseFilter):
    """
    gyr (numpy.ndarray) – N-by-3 array with measurements of angular velocity in rad/s
    acc (numpy.ndarray) – N-by-3 array with measurements of acceleration in in m/s^2
    """

    def __init__(self, frequency):
        super().__init__()
        self.mahony = Mahony(frequency=frequency)

    def update(self, acc_data, gyro_data) -> np.ndarray:
        """
        Update orientation using Madgwick filter.
        Keeps quaternion in [w, x, y, z] internally.
        """
        self.quaternion = self.mahony.updateIMU(
            self.quaternion, gyr=gyro_data, acc=acc_data
        )
        self.normalize_quaternion()
        return self.quaternion
