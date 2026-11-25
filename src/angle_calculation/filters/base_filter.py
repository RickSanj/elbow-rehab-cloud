import numpy as np
from ahrs.common.orientation import acc2q
from scipy.spatial.transform import Rotation


def _wxyz_to_xyzw(quaternion: np.ndarray) -> np.ndarray:
    """
    Return a `quaternion` reordered for SciPy's `[x, y, z, w]` format.
    """

    w, x, y, z = quaternion
    return np.array([x, y, z, w], dtype=float)


class BaseFilter:
    """Mutable orientation container shared across the AHRS filter wrappers.

    The class stores the latest orientation estimate as a quaternion in
    ``[w, x, y, z]`` order and exposes convenience accessors that mirror SciPy's
    ``Rotation`` API. Concrete filters (e.g. Madgwick, Mahony, EKF) update the
    quaternion directly and rely on these helpers for downstream consumers that
    prefer matrices or Euler angles.

    ``update(acc, gyro, dt=None)``: when ``dt`` (seconds) is given it is used
    for this step instead of the fixed ``1 / frequency``, so jitter and lost
    packets are integrated with the real sample spacing.
    """

    # Sign of the accelerometer reading that the filter treats as "up" when
    # the sensor is level: +1 for z-up (ENU) filters, -1 for the NED EKF.
    GRAVITY_SIGN = 1.0

    def __init__(self) -> None:
        """Initialize the orientation to the identity rotation."""
        self.quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)  # [w, x, y, z]

    def _impl(self):
        raise NotImplementedError

    def set_dt(self, dt: float | None) -> None:
        if dt is not None:
            self._impl().Dt = float(dt)

    def initial_quaternion(self, acc_data) -> np.ndarray:
        """Orientation (yaw = 0) that agrees with a static accelerometer reading."""
        acc = np.asarray(acc_data, dtype=float)
        return np.asarray(acc2q(self.GRAVITY_SIGN * acc), dtype=float)

    def reset(self, quaternion) -> None:
        self.quaternion = np.asarray(quaternion, dtype=float).copy()
        self.normalize_quaternion()

    def normalize_quaternion(self) -> None:
        """Rescale the quaternion in-place to prevent drift from unit length."""
        norm = np.linalg.norm(self.quaternion)
        if norm == 0.0:
            self.quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
            return
        self.quaternion = self.quaternion / norm

    def rotation_matrix(self) -> np.ndarray:
        """Return the current orientation as a 3x3 direction cosine matrix."""
        return Rotation.from_quat(_wxyz_to_xyzw(self.quaternion)).as_matrix()

    def euler_angles(self, degrees: bool = True) -> np.ndarray:
        """Return roll, pitch, yaw for the current orientation estimate.

        Parameters
        ----------
        degrees: bool, default True
            When ``True`` the angles follow the common degree convention used
            throughout the UI layer. Set to ``False`` to obtain radians, which
            matches SciPy's default.
        """

        return Rotation.from_quat(_wxyz_to_xyzw(self.quaternion)).as_euler(
            "xyz", degrees=degrees
        )
