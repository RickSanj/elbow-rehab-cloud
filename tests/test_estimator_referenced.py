"""Angle extraction of the alignment-free estimator on perfect orientations.

The true joint axes are injected and axis learning is disabled, so these
tests check only the decomposition R_AB -> (FE, PS) relative to the zero pose.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.angle_calculation.estimator import AlignmentFreeElbowEstimator
from tests.synthetic import M_A, M_B, body_rates, default_upper_arm, elbow_rotations

TRUE_A = M_A.inv().apply([0.0, 0.0, 1.0])  # FE axis in sensor A
TRUE_B = M_B.inv().apply([0.0, 1.0, 0.0])  # PS axis in sensor B
ZERO_POSE_T = 2.0


def fe_truth(t):
    t = np.asarray(t, dtype=float)
    return np.where(t < 3, 15.0, 70 + 35 * np.sin(2 * np.pi * 0.21 * t) + 15 * np.sin(2 * np.pi * 0.53 * t + 0.4))


def ps_truth(t):
    t = np.asarray(t, dtype=float)
    return np.where(t < 3, 0.0, 30 * np.sin(2 * np.pi * 0.13 * t + 1.0) + 15 * np.sin(2 * np.pi * 0.37 * t))


def with_true_axes(est: AlignmentFreeElbowEstimator) -> AlignmentFreeElbowEstimator:
    def spherical(v):
        return float(np.arccos(np.clip(v[2], -1, 1))), float(np.arctan2(v[1], v[0]))

    est.theta_a, est.rho_a = spherical(TRUE_A)
    est.theta_b, est.rho_b = spherical(TRUE_B)
    est.min_axis_speed = np.inf  # no axis updates
    return est


def run(est, duration=40.0):
    t = np.arange(0.0, duration, 0.01)

    def rot_a(tt):
        return elbow_rotations(tt, fe_truth, ps_truth, default_upper_arm)[0]

    def rot_b(tt):
        return elbow_rotations(tt, fe_truth, ps_truth, default_upper_arm)[1]

    ra, rb = rot_a(t).as_matrix(), rot_b(t).as_matrix()
    ga, gb = body_rates(rot_a, t), body_rates(rot_b, t)
    fe = np.empty(len(t))
    ps = np.empty(len(t))
    zeroed = False
    for i in range(len(t)):
        if not zeroed and t[i] >= ZERO_POSE_T:
            est.set_zero_pose(ra[i], rb[i])
            zeroed = True
        fe[i], ps[i] = est.update_angles(ra[i], ga[i], rb[i], gb[i])
    after = t >= ZERO_POSE_T
    fe_err = fe[after] - (fe_truth(t[after]) - fe_truth(ZERO_POSE_T))
    ps_err = ps[after] - (ps_truth(t[after]) - ps_truth(ZERO_POSE_T))
    return fe_err, ps_err


def rmse(x):
    return float(np.sqrt(np.mean(np.square(x))))


def test_referenced_solve_recovers_angles_exactly_with_true_axes():
    fe_err, ps_err = run(with_true_axes(AlignmentFreeElbowEstimator(100.0)))
    assert rmse(fe_err) < 0.5, rmse(fe_err)
    assert rmse(ps_err) < 0.5, rmse(ps_err)
    assert np.abs(fe_err).max() < 1.0
    assert np.abs(ps_err).max() < 1.0


def test_old_absolute_solve_is_still_available_and_is_worse():
    est = with_true_axes(AlignmentFreeElbowEstimator(100.0))
    est.use_referenced_solve = False
    fe_err, ps_err = run(est)
    # Documents the defect the referenced solve fixes: the absolute model has
    # no term for the sensor-mounting rotation.
    assert max(rmse(fe_err), rmse(ps_err)) > 5.0


def test_angles_are_zero_at_the_zero_pose():
    est = with_true_axes(AlignmentFreeElbowEstimator(100.0))
    fe_err, ps_err = run(est, duration=ZERO_POSE_T + 0.5)
    # Static hold until t = 3 s: angles stay at 0 after zeroing.
    assert np.abs(fe_err).max() < 1e-6
    assert np.abs(ps_err).max() < 1e-6


@pytest.mark.parametrize("use_referenced", [True, False])
def test_estimator_api_unchanged(use_referenced):
    est = AlignmentFreeElbowEstimator(100.0)
    est.use_referenced_solve = use_referenced
    eye = np.eye(3)
    est.set_zero_pose(eye, eye)
    fe, ps = est.update_angles(eye, np.zeros(3), eye, np.zeros(3))
    assert np.isfinite(fe) and np.isfinite(ps)
