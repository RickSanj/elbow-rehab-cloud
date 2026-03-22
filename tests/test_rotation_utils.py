import numpy as np
from scipy.spatial.transform import Rotation as R

from src.angle_calculation.estimator import (
    AlignmentFreeElbowEstimator,
    dcart_drho,
    dcart_dtheta,
    exp_so3,
    log_so3,
    skew,
    spherical_to_cartesian,
    vee,
)


def test_skew_reproduces_cross_product_and_is_skew_symmetric():
    v = np.array([1.2, -0.7, 0.4])
    w = np.array([-0.3, 2.1, 0.9])

    S = skew(v)

    np.testing.assert_allclose(S @ w, np.cross(v, w), atol=1e-12)
    np.testing.assert_allclose(S.T, -S, atol=1e-12)


def test_vee_inverts_skew_and_discards_symmetric_part():
    v = np.array([0.8, -1.5, 2.2])
    symmetric_part = np.array(
        [
            [2.0, -1.0, 0.5],
            [-1.0, 3.0, 1.2],
            [0.5, 1.2, -4.0],
        ]
    )

    np.testing.assert_allclose(vee(skew(v)), v, atol=1e-12)
    np.testing.assert_allclose(vee(skew(v) + symmetric_part), v, atol=1e-12)


def test_exp_so3_matches_scipy_rotation_matrix():
    rotvec = np.array([0.2, -0.4, 0.7])

    expected = R.from_rotvec(rotvec).as_matrix()

    np.testing.assert_allclose(exp_so3(rotvec), expected, atol=1e-10)


def test_exp_so3_uses_first_order_approximation_for_tiny_angles():
    rotvec = np.array([1e-14, -2e-14, 3e-14])

    np.testing.assert_allclose(exp_so3(rotvec), np.eye(3) + skew(rotvec), atol=1e-20)


def test_log_so3_returns_zero_for_identity():
    np.testing.assert_allclose(log_so3(np.eye(3)), np.zeros(3), atol=1e-12)


def test_log_so3_matches_scipy_rotation_vector():
    rotvec = np.array([0.3, -0.2, 0.4])
    rotation_matrix = R.from_rotvec(rotvec).as_matrix()

    np.testing.assert_allclose(log_so3(rotation_matrix), rotvec, atol=1e-10)


def test_exp_and_log_so3_are_inverse_for_regular_rotation():
    rotvec = np.array([-0.25, 0.35, 0.45])

    np.testing.assert_allclose(log_so3(exp_so3(rotvec)), rotvec, atol=1e-10)


def test_spherical_to_cartesian_matches_known_axes():
    np.testing.assert_allclose(
        spherical_to_cartesian(0.0, 0.0),
        np.array([0.0, 0.0, 1.0]),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        spherical_to_cartesian(np.pi / 2.0, 0.0),
        np.array([1.0, 0.0, 0.0]),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        spherical_to_cartesian(np.pi / 2.0, np.pi / 2.0),
        np.array([0.0, 1.0, 0.0]),
        atol=1e-12,
    )


def test_spherical_to_cartesian_returns_unit_vector():
    theta = 1.1
    rho = -0.7

    np.testing.assert_allclose(
        np.linalg.norm(spherical_to_cartesian(theta, rho)),
        1.0,
        atol=1e-12,
    )


def test_dcart_dtheta_matches_finite_difference():
    theta = 1.1
    rho = -0.7
    eps = 1e-7

    finite_difference = (
        spherical_to_cartesian(theta + eps, rho)
        - spherical_to_cartesian(theta - eps, rho)
    ) / (2.0 * eps)

    np.testing.assert_allclose(dcart_dtheta(theta, rho), finite_difference, atol=1e-8)


def test_dcart_drho_matches_finite_difference():
    theta = 1.1
    rho = -0.7
    eps = 1e-7

    finite_difference = (
        spherical_to_cartesian(theta, rho + eps)
        - spherical_to_cartesian(theta, rho - eps)
    ) / (2.0 * eps)

    np.testing.assert_allclose(dcart_drho(theta, rho), finite_difference, atol=1e-8)


def test_spherical_derivatives_are_tangent_to_unit_sphere():
    theta = 1.1
    rho = -0.7
    point = spherical_to_cartesian(theta, rho)

    np.testing.assert_allclose(np.dot(point, dcart_dtheta(theta, rho)), 0.0, atol=1e-12)
    np.testing.assert_allclose(np.dot(point, dcart_drho(theta, rho)), 0.0, atol=1e-12)


def test_current_axes_uses_estimator_spherical_parameters():
    estimator = AlignmentFreeElbowEstimator()
    estimator.theta_a = np.pi / 2.0
    estimator.rho_a = 0.0
    estimator.theta_b = np.pi / 2.0
    estimator.rho_b = np.pi / 2.0

    a_A, b_B = estimator.current_axes()

    np.testing.assert_allclose(a_A, np.array([1.0, 0.0, 0.0]), atol=1e-12)
    np.testing.assert_allclose(b_B, np.array([0.0, 1.0, 0.0]), atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(a_A), 1.0, atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(b_B), 1.0, atol=1e-12)


def test_unwrap_keeps_angle_continuous_across_branch_cut():
    estimator = AlignmentFreeElbowEstimator()
    prev_angle = np.deg2rad(179.0)
    wrapped_measurement = np.deg2rad(-179.0)

    unwrapped = estimator.unwrap(wrapped_measurement, prev_angle)

    np.testing.assert_allclose(unwrapped, np.deg2rad(181.0), atol=1e-12)
    np.testing.assert_allclose(estimator.unwrap(0.7, None), 0.7, atol=1e-12)


def test_relative_returns_pose_and_velocity_in_frame_a():
    estimator = AlignmentFreeElbowEstimator()
    R_A = R.from_euler("x", 30.0, degrees=True).as_matrix()
    R_B = R.from_euler("yz", [20.0, -15.0], degrees=True).as_matrix()
    gyro_A = np.array([0.4, -0.3, 0.2])
    gyro_B = np.array([-0.5, 0.1, 0.7])

    R_BA, omega_r_A = estimator.relative(R_A, R_B, gyro_A, gyro_B)

    expected_R_BA = R_A.T @ R_B
    expected_omega_r_A = -gyro_A + expected_R_BA @ gyro_B

    np.testing.assert_allclose(R_BA, expected_R_BA, atol=1e-12)
    np.testing.assert_allclose(omega_r_A, expected_omega_r_A, atol=1e-12)


def test_solve_angles_from_orientation_returns_initial_guess_when_refinement_disabled():
    estimator = AlignmentFreeElbowEstimator()
    estimator.use_gauss_newton_refinement = False
    estimator.current_axes = lambda: (
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
    )
    estimator.initial_angle_guess = lambda R_BA, a_A, b_A: (0.45, -0.67)

    alpha, beta = estimator.solve_angles_from_orientation(np.eye(3))

    np.testing.assert_allclose([alpha, beta], [0.45, -0.67], atol=1e-12)
    assert estimator.last_orientation_solve_debug["gauss_newton_refinement_enabled"] is False
    assert estimator.last_orientation_solve_debug["gauss_newton_steps"]


def test_log_orientation_solution_writes_requested_fields(tmp_path):
    estimator = AlignmentFreeElbowEstimator()
    log_path = tmp_path / "angle_debug_log.txt"

    estimator.set_debug_log_path(log_path)
    estimator.last_orientation_solve_debug = {
        "gauss_newton_refinement_enabled": True,
        "R_BA": np.eye(3),
        "a_A": np.array([1.0, 0.0, 0.0]),
        "b_B": np.array([0.0, 1.0, 0.0]),
        "b_A": np.array([0.0, 1.0, 0.0]),
        "r_err_norm": 0.0123,
        "initial_alpha": 0.45,
        "initial_beta": -0.67,
        "initial_residual": np.array([0.1, -0.2, 0.3]),
        "initial_residual_norm": 0.374166,
        "gauss_newton_steps": [
            {
                "iteration": 1,
                "r_err_before": np.array([0.4, 0.2, -0.1]),
                "r_err_before_norm": 0.5,
                "J": np.array([[1.0, 0.0], [0.0, 1.0], [0.1, -0.2]]),
                "d_unclipped": [0.11, -0.21],
                "d_clipped": [0.1, -0.2],
                "r_err_after": np.array([0.1, 0.0, -0.173205]),
                "r_err_after_norm": 0.2,
                "trial_residuals": {
                    "plus_unclipped": 0.19,
                    "minus_unclipped": 0.71,
                    "plus_clipped": 0.2,
                    "minus_clipped": 0.68,
                },
            },
            {
                "iteration": 2,
                "r_err_before": np.array([0.1, 0.0, -0.173205]),
                "r_err_before_norm": 0.2,
                "J": np.array([[0.8, 0.1], [0.1, 0.9], [0.0, -0.3]]),
                "d_unclipped": [-0.05, 0.03],
                "d_clipped": [-0.05, 0.03],
                "r_err_after": np.array([0.05, -0.02, 0.05831]),
                "r_err_after_norm": 0.08,
                "trial_residuals": {
                    "plus_unclipped": 0.08,
                    "minus_unclipped": 0.33,
                    "plus_clipped": 0.08,
                    "minus_clipped": 0.33,
                },
            },
        ],
        "final_iteration_residuals": [
            {"iteration": 1, "r_err_after": np.array([0.1, 0.0, -0.173205]), "r_err_norm_after": 0.2},
            {"iteration": 2, "r_err_after": np.array([0.05, -0.02, 0.05831]), "r_err_norm_after": 0.08},
        ],
    }
    estimator.log_orientation_solution(0.5, -0.25)

    content = log_path.read_text(encoding="utf-8")

    assert "alpha raw (rad): 0.5" in content
    assert "beta raw  (rad): -0.25" in content
    assert "alpha deg:" in content
    assert "Gauss-Newton refinement enabled: True" in content
    assert "R_BA:" in content
    assert "a_A:" in content
    assert "b_B:" in content
    assert "b_A:" in content
    assert "||r_err||: 0.0123" in content
    assert "alpha0 from initial_angle_guess (rad): 0.45" in content
    assert "beta0 from initial_angle_guess (rad): -0.67" in content
    assert "residual norm at initial guess: 0.374166" in content
    assert "r_err_before_norm (iter 1): 0.5" in content
    assert "J (iter 1):" in content
    assert "d_unclipped (iter 1): [ 0.11, -0.21]" in content
    assert "d_clipped (iter 1): [ 0.1, -0.2]" in content
    assert "r_err_after_norm (iter 1): 0.2" in content
    assert "one-step trial residuals (iter 1): plus_unclipped=0.190000" in content
    assert "r_err_before_norm (iter 2): 0.2" in content
    assert "d_unclipped (iter 2): [-0.05,  0.03]" in content
    assert "final residual after 1 iteration: 0.2" in content
    assert "final residual after 2 iterations: 0.08" in content


def test_log_orientation_solution_can_filter_to_chosen_samples(tmp_path):
    estimator = AlignmentFreeElbowEstimator()
    log_path = tmp_path / "angle_debug_log.txt"

    estimator.set_debug_log_path(log_path, sample_indices={2})
    estimator.last_orientation_solve_debug = {
        "gauss_newton_refinement_enabled": False,
        "R_BA": np.eye(3),
        "a_A": np.array([1.0, 0.0, 0.0]),
        "b_B": np.array([0.0, 1.0, 0.0]),
        "b_A": np.array([0.0, 1.0, 0.0]),
        "r_err_norm": 0.1,
        "initial_alpha": 0.1,
        "initial_beta": 0.2,
        "initial_residual": np.zeros(3),
        "initial_residual_norm": 0.0,
        "gauss_newton_steps": [],
        "final_iteration_residuals": [],
    }
    estimator.log_orientation_solution(0.1, 0.2)
    estimator.log_orientation_solution(0.3, 0.4)

    content = log_path.read_text(encoding="utf-8")

    assert "sample: 1" not in content
    assert "sample: 2" in content
