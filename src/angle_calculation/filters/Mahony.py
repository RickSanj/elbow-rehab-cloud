from ahrs.filters import Mahony
import numpy as np
from .base_filter import BaseFilter


class MahonyFilter(BaseFilter):
    """
    gyr (numpy.ndarray) – N-by-3 array with measurements of angular velocity in rad/s
    acc (numpy.ndarray) – N-by-3 array with measurements of acceleration in in m/s^2
    """

    def __init__(self, frequency):
        super().__init__()
        self.mahony = Mahony(frequency=frequency)

    def _impl(self):
        return self.mahony

    def update(self, acc_data, gyro_data, dt: float | None = None) -> np.ndarray:
        """
        Update orientation using the Mahony filter.
        Keeps quaternion in [w, x, y, z] internally.
        """
        self.set_dt(dt)
        self.quaternion = self.mahony.updateIMU(
            q=self.quaternion, gyr=gyro_data, acc=acc_data
        )
        return self.quaternion
