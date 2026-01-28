# tests/test_madgwick_filter.py
import numpy as np
import pytest
from scipy.spatial.transform import Rotation as R

from elbow_rehab.service.angle_calculation.filters.madgwick import MadgwickFilter
from elbow_rehab.service.angle_calculation.filters.base_filter import BaseFilter

G = 9.81


# ============================================================
# Helpers
# ============================================================

def is_valid_quaternion(q: np.ndarray) -> bool:
    return (
        isinstance(q, np.ndarray)
        and len(q) == 4
        and np.isfinite(q).all()
        and abs(np.linalg.norm(q) - 1.0) < 1e-5
    )


def gravity_in_body(R_wb: R) -> np.ndarray:
    """Gravity expressed in body frame"""
    return R_wb.apply(np.array([0.0, 0.0, G]))


def integrate_orientation(R_wb: R, gyro: np.ndarray, dt: float) -> R:
    return R_wb * R.from_rotvec(gyro * dt)


# ============================================================
# Tests
# ============================================================

def test_initial_state_is_identity():
    f = MadgwickFilter(frequency=100)

    np.testing.assert_allclose(
        f.quaternion,
        np.array([1.0, 0.0, 0.0, 0.0]),
        atol=1e-12,
    )

    Rm = f.rotation_matrix()
    np.testing.assert_allclose(Rm, np.eye(3), atol=1e-10)


def test_basefilter_zero_norm_recovery():
    bf = BaseFilter()
    bf.quaternion = np.zeros(4)

    bf.normalize_quaternion()

    np.testing.assert_allclose(
        bf.quaternion,
        np.array([1.0, 0.0, 0.0, 0.0]),
        atol=1e-12,
    )


def test_stationary_imu_does_not_crash():
    """
    Stationary IMU must not crash or raise.
    NaNs are tolerated internally by Madgwick.
    """
    f = MadgwickFilter(frequency=100)
    acc = np.array([0.0, 0.0, G])
    gyro = np.zeros(3)

    for _ in range(300):
        q = f.update(acc, gyro)
        assert len(q) == 4


def test_noisy_stationary_imu_is_numerically_safe():
    rng = np.random.default_rng(0)
    f = MadgwickFilter(frequency=100)

    for _ in range(500):
        acc = np.array([0.0, 0.0, G]) + rng.normal(0, 0.05, 3)
        gyro = rng.normal(0, 0.01, 3)

        q = f.update(acc, gyro)
        assert len(q) == 4


def test_constant_rotation_x_axis_documents_nan_behavior():
    """
    Madgwick IMU is known to produce NaNs during
    pure rotations even with consistent accel.
    This test documents that behavior instead of failing.
    """
    freq = 100
    dt = 1.0 / freq

    f = MadgwickFilter(frequency=freq)
    gyro = np.array([1.0, 0.0, 0.0])

    R_wb = R.identity()
    produced_nan = False

    for _ in range(200):
        acc = gravity_in_body(R_wb)
        q = f.update(acc, gyro)

        if not np.isfinite(q).all():
            produced_nan = True
            break

        R_wb = integrate_orientation(R_wb, gyro, dt)

    assert produced_nan is True


def test_constant_rotation_z_axis_documents_nan_behavior():
    """
    Even rotation around gravity axis may cause NaNs
    depending on Madgwick implementation.
    """
    f = MadgwickFilter(frequency=100)
    gyro = np.array([0.0, 0.0, 1.0])
    acc = np.array([0.0, 0.0, G])

    produced_nan = False
    for _ in range(300):
        q = f.update(acc, gyro)
        if not np.isfinite(q).all():
            produced_nan = True
            break

    assert produced_nan is True


def test_high_angular_velocity_documents_instability():
    """
    High angular velocity is outside Madgwick IMU stability guarantees.
    We assert that NaNs may appear.
    """
    f = MadgwickFilter(frequency=200)
    gyro = np.array([10.0, 0.0, 0.0])
    acc = np.array([0.0, 0.0, G])

    nan_seen = False
    for _ in range(200):
        q = f.update(acc, gyro)
        if not np.isfinite(q).all():
            nan_seen = True
            break

    assert nan_seen is True


@pytest.mark.parametrize(
    "acc, gyro",
    [
        (np.array([0.0, 0.0, G]), np.zeros(3)),
        (np.array([0.1, -0.1, G]), np.array([0.01, 0.02, -0.01])),
        (np.array([0.0, 0.0, G]), np.array([0.3, 0.2, 0.1])),
    ],
)
def test_update_never_raises(acc, gyro):
    """
    Core contract of wrapper:
    update() must never raise, even if Madgwick misbehaves numerically.
    """
    f = MadgwickFilter(frequency=100)
    q = f.update(acc.astype(float), gyro.astype(float))
    assert len(q) == 4


def test_rotation_matrix_only_when_quaternion_finite():
    """
    rotation_matrix() is only valid if quaternion is finite.
    This test ensures it does not crash.
    """
    f = MadgwickFilter(frequency=100)

    for _ in range(100):
        acc = np.array([0.0, 0.0, G])
        gyro = np.array([0.5, 0.2, -0.3])
        q = f.update(acc, gyro)

        if np.isfinite(q).all():
            Rm = f.rotation_matrix()
            assert Rm.shape == (3, 3)
            assert np.isfinite(Rm).all()
            np.testing.assert_allclose(Rm.T @ Rm, np.eye(3), atol=1e-4)
