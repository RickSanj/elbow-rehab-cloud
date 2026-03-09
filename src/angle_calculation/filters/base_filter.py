import numpy as np
from scipy.spatial.transform import Rotation


def _wxyz_to_xyzw(quaternion: np.ndarray) -> np.ndarray:
    """Convert a `[w, x, y, z]` quaternion to SciPy's `[x, y, z, w]` order."""

    w, x, y, z = quaternion
    return np.array([x, y, z, w], dtype=float)


class BaseFilter:
    """Shared quaternion helpers for the lightweight filter wrappers."""

    def __init__(self) -> None:
        self.quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)  # [w, x, y, z]

    def normalize_quaternion(self) -> None:
        norm = np.linalg.norm(self.quaternion)
        if norm == 0.0:
            self.quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=float)
            return
        self.quaternion = self.quaternion / norm

    def rotation_matrix(self) -> np.ndarray:
        """Return the orientation as a 3×3 rotation matrix."""

        return Rotation.from_quat(_wxyz_to_xyzw(self.quaternion)).as_matrix()

    def euler_angles(self, degrees: bool = True) -> np.ndarray:
        """Return roll, pitch, yaw from the current orientation."""

        return Rotation.from_quat(_wxyz_to_xyzw(self.quaternion)).as_euler(
            "xyz", degrees=degrees
        )
