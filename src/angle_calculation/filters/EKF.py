"""Extended Kalman orientation filter sharing the BaseFilter interface."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.spatial.transform import Rotation

from filters.base_filter import BaseFilter

_FLOAT_EPS: float = 1e-9
_GRAVITY_BODY_Z: NDArray[np.float64] = np.array([0.0, 0.0, 1.0], dtype=np.float64)


def _skew(vector: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return the skew-symmetric matrix associated with `vector × x`."""

    x, y, z = vector
    return np.array(
        [
            [0.0, -z, y],
            [z, 0.0, -x],
            [-y, x, 0.0],
        ],
        dtype=np.float64,
    )


def _quat_multiply(
    q_left: NDArray[np.float64], q_right: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Hamilton product of two `[w, x, y, z]` quaternions."""

    w1, x1, y1, z1 = q_left
    w2, x2, y2, z2 = q_right
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=np.float64,
    )


def _small_angle_quaternion(delta_theta: NDArray[np.float64]) -> NDArray[np.float64]:
    """Map a small rotation vector to a unit quaternion."""

    angle = np.linalg.norm(delta_theta)
    if angle < _FLOAT_EPS:
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    axis = delta_theta / angle
    half = 0.5 * angle
    return np.array(
        [np.cos(half), *(np.sin(half) * axis)],
        dtype=np.float64,
    )


def _normalize_quaternion(quaternion: NDArray[np.float64]) -> NDArray[np.float64]:
    """Ensure a quaternion remains on the unit sphere."""

    norm = np.linalg.norm(quaternion)
    if norm < _FLOAT_EPS:
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    return quaternion / norm


def _wxyz_to_xyzw(quaternion: NDArray[np.float64]) -> NDArray[np.float64]:
    """Convert `[w, x, y, z]` to SciPy's `[x, y, z, w]` ordering."""

    w, x, y, z = quaternion
    return np.array([x, y, z, w], dtype=np.float64)


class ExtendedKalmanFilter(BaseFilter):
    """Error-state EKF using the same logic as `Filters.filter_ekf`."""

    def __init__(
        self,
        frequency: float,
        *,
        gyro_noise: float = 0.02,
        bias_rw: float = 0.001,
        acc_noise: float = 0.03,
        initial_covariance: NDArray[np.float64] | None = None,
    ) -> None:
        super().__init__()
        if frequency <= 0.0:
            raise ValueError("Sampling frequency must be positive.")

        self.dt = 1.0 / float(frequency)
        self.gyro_noise = float(gyro_noise)
        self.bias_rw = float(bias_rw)
        self.acc_noise = float(acc_noise)

        self._set_initial_covariance(initial_covariance)
        self.reset()

    def _set_initial_covariance(self, covariance: NDArray[np.float64] | None) -> None:
        if covariance is None:
            self._covariance_template = np.eye(6, dtype=np.float64) * 0.01
        else:
            cov = np.asarray(covariance, dtype=np.float64)
            if cov.shape != (6, 6):
                raise ValueError("Initial covariance must be a 6x6 matrix.")
            self._covariance_template = cov
        self._covariance = self._covariance_template.copy()

    def reset(
        self, *, quaternion: ArrayLike | None = None, bias: ArrayLike | None = None
    ) -> None:
        """Reset nominal orientation, bias estimate, and covariance."""

        if quaternion is None:
            self.quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        else:
            quat = np.asarray(quaternion, dtype=np.float64).reshape(-1)
            if quat.size != 4:
                raise ValueError("Quaternion must have four components.")
            self.quaternion = _normalize_quaternion(quat)

        if bias is None:
            self._bias = np.zeros(3, dtype=np.float64)
        else:
            arr = np.asarray(bias, dtype=np.float64).reshape(-1)
            if arr.size != 3:
                raise ValueError("Gyroscope bias must have three components.")
            self._bias = arr

        self._covariance = self._covariance_template.copy()

    def update(self, acc_data: ArrayLike, gyro_data: ArrayLike) -> NDArray[np.float64]:
        """Process the next accelerometer/gyroscope sample."""

        acc = np.asarray(acc_data, dtype=np.float64).reshape(-1)
        gyro = np.asarray(gyro_data, dtype=np.float64).reshape(-1)
        if acc.size != 3 or gyro.size != 3:
            raise ValueError("Expected 3-element accelerometer and gyroscope vectors.")

        self._predict(gyro, self.dt)
        self._update_with_acc(acc)
        self.normalize_quaternion()
        return self.quaternion

    def _predict(self, gyro_rad_s: NDArray[np.float64], dt: float) -> None:
        omega = gyro_rad_s - self._bias
        w, x, y, z = self.quaternion
        wx, wy, wz = omega
        q_dot = 0.5 * np.array(
            [
                -x * wx - y * wy - z * wz,
                w * wx + y * wz - z * wy,
                w * wy - x * wz + z * wx,
                w * wz + x * wy - y * wx,
            ],
            dtype=np.float64,
        )
        self.quaternion = _normalize_quaternion(self.quaternion + q_dot * dt)

        f_matrix = np.zeros((6, 6), dtype=np.float64)
        f_matrix[0:3, 0:3] = -_skew(omega)
        f_matrix[0:3, 3:6] = -np.eye(3, dtype=np.float64)

        transition = np.eye(6, dtype=np.float64) + f_matrix * dt
        gyro_noise = (self.gyro_noise**2) * dt * np.eye(3, dtype=np.float64)
        bias_noise = (self.bias_rw**2) * dt * np.eye(3, dtype=np.float64)
        process_noise = np.block(
            [
                [gyro_noise, np.zeros((3, 3), dtype=np.float64)],
                [np.zeros((3, 3), dtype=np.float64), bias_noise],
            ]
        )
        self._covariance = transition @ self._covariance @ transition.T + process_noise

    def _update_with_acc(self, acc: NDArray[np.float64]) -> None:
        norm = np.linalg.norm(acc)
        if norm < _FLOAT_EPS:
            return

        measurement = acc / norm
        rotation_body_to_world = Rotation.from_quat(
            _wxyz_to_xyzw(self.quaternion)
        ).as_matrix()
        predicted = rotation_body_to_world.T @ _GRAVITY_BODY_Z
        innovation = measurement - predicted

        measurement_matrix = np.zeros((3, 6), dtype=np.float64)
        measurement_matrix[:, 0:3] = -_skew(predicted)

        accel_cov = (self.acc_noise**2) * np.eye(3, dtype=np.float64)

        ph_t = self._covariance @ measurement_matrix.T
        innovation_cov = measurement_matrix @ ph_t + accel_cov
        kalman_gain = np.linalg.solve(innovation_cov.T, ph_t.T).T

        correction = kalman_gain @ innovation
        delta_theta = correction[0:3]
        delta_bias = correction[3:6]

        self.quaternion = _normalize_quaternion(
            _quat_multiply(self.quaternion, _small_angle_quaternion(delta_theta))
        )
        self._bias = self._bias + delta_bias

        identity = np.eye(6, dtype=np.float64)
        temp = identity - kalman_gain @ measurement_matrix
        self._covariance = (
            temp @ self._covariance @ temp.T + kalman_gain @ accel_cov @ kalman_gain.T
        )

    def get_bias(self) -> NDArray[np.float64]:
        """Return the current gyroscope bias estimate."""

        return self._bias.copy()
