# elbow_rehab/service/filters/madgwick.py
import numpy as np
from ahrs.filters import Madgwick
from scipy.spatial.transform import Rotation

class MadgwickFilter:
    def __init__(self, frequency=100.0):
        self.madgwick = Madgwick(frequency=frequency)
        self.quaternion = np.array([1.0, 0.0, 0.0, 0.0]) # [w, x, y, z]

    def update(self, acc, gyro):
        self.quaternion = self.madgwick.updateIMU(self.quaternion, gyr=gyro, acc=acc)
        # Normalize
        norm = np.linalg.norm(self.quaternion)
        if norm > 0: self.quaternion /= norm
        return self.quaternion

    def rotation_matrix(self):
        # Convert wxyz to xyzw for scipy
        q = self.quaternion
        scipy_q = np.array([q[1], q[2], q[3], q[0]])
        return Rotation.from_quat(scipy_q).as_matrix()