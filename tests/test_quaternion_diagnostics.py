import numpy as np
import pytest

from src.analytics.quaternion_diagnostics import (
    compute_pairwise_quaternion_diagnostics,
    compute_quaternion_diagnostics,
    quat_conj,
    quat_mul,
    quaternion_relative_angle_deg,
)


def test_quaternion_relative_angle_is_sign_invariant():
    quarter_turn_z = np.array(
        [np.cos(np.deg2rad(45.0)), 0.0, 0.0, np.sin(np.deg2rad(45.0))]
    )

    assert quaternion_relative_angle_deg(quarter_turn_z, -quarter_turn_z) == pytest.approx(0.0)


def test_compute_quaternion_diagnostics_summarizes_reference_and_step_angles():
    identity = np.array([1.0, 0.0, 0.0, 0.0])
    ten_deg_z = np.array(
        [np.cos(np.deg2rad(5.0)), 0.0, 0.0, np.sin(np.deg2rad(5.0))]
    )

    diagnostics = compute_quaternion_diagnostics(
        np.array([identity, ten_deg_z, -ten_deg_z])
    )

    np.testing.assert_allclose(
        diagnostics["angle_from_reference_deg"],
        np.array([0.0, 10.0, 10.0]),
        atol=1e-6,
    )
    np.testing.assert_allclose(
        diagnostics["sample_change_deg"][1:],
        np.array([10.0, 0.0]),
        atol=1e-6,
    )
    assert diagnostics["max_abs_norm_error"] == pytest.approx(0.0)
    assert diagnostics["reference_index"] == 0


def test_quat_mul_and_conjugate_produce_expected_relative_rotation():
    identity = np.array([1.0, 0.0, 0.0, 0.0])
    twenty_deg_z = np.array(
        [np.cos(np.deg2rad(10.0)), 0.0, 0.0, np.sin(np.deg2rad(10.0))]
    )

    q_rel = quat_mul(quat_conj(identity), twenty_deg_z)
    angle = 2.0 * np.degrees(np.arccos(np.clip(abs(q_rel[0]), -1.0, 1.0)))

    assert angle == pytest.approx(20.0)


def test_compute_pairwise_quaternion_diagnostics_summarizes_sensor_relative_angle():
    identity = np.array([1.0, 0.0, 0.0, 0.0])
    twenty_deg_z = np.array(
        [np.cos(np.deg2rad(10.0)), 0.0, 0.0, np.sin(np.deg2rad(10.0))]
    )

    diagnostics = compute_pairwise_quaternion_diagnostics(
        np.array([identity, identity, identity]),
        np.array([identity, twenty_deg_z, -twenty_deg_z]),
    )

    np.testing.assert_allclose(
        diagnostics["relative_angle_deg"],
        np.array([0.0, 20.0, 20.0]),
        atol=1e-6,
    )
    assert diagnostics["relative_angle_stats"]["min"] == pytest.approx(0.0)
    assert diagnostics["relative_angle_stats"]["max"] == pytest.approx(20.0)
    assert diagnostics["min_relative_angle_index"] == 0
    assert diagnostics["max_relative_angle_index"] == 1
