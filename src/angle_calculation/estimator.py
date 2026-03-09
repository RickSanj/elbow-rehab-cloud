# calculate_angles.py
# Simple calculation
from __future__ import annotations
import numpy as np
from scipy.spatial.transform import Rotation as R
# from torch import atan2


class SimpleElbowEstimator:
    def __init__(self, sample_rate_hz: float = 100.0):
        pass

    def rpy_to_matrix(self, roll, pitch, yaw):
        """Convert roll, pitch, yaw to a 3×3 rotation matrix."""
        return R.from_euler("xyz", [roll, pitch, yaw], degrees=True).as_matrix()

    def normalize_fe(self, angle_deg: float) -> float:
        return (angle_deg + 180) % 360 - 180

    def normalize_ps(self, angle_deg: float) -> float:
        return (angle_deg + 180) % 360 - 180

    def median_smooth(self, series, window=10):
        smoothed = []
        for idx in range(len(series)):
            start = max(0, idx - window + 1)
            window_values = series[start : idx + 1]
            smoothed.append(float(np.median(np.sort(window_values))))
        return np.array(smoothed, dtype=float)

    def orthonormalize(self, Rm):
        """Project a noisy 3x3 matrix back onto SO(3) (proper rotation)."""
        U, _, Vt = np.linalg.svd(Rm)
        Rn = U @ Vt
        if np.linalg.det(Rn) < 0:
            U[:, -1] *= -1
            Rn = U @ Vt
        return Rn

    def rotation_mean(self, mats):
        """
        Average a list of rotation matrices properly (not elementwise).
        Uses scipy Rotation.mean() to compute a valid mean rotation.
        """
        rots = R.from_matrix(mats)
        return rots.mean().as_matrix()

    # def update_angles(
    #     self, R_A: np.ndarray, gyro_A: np.ndarray, R_B: np.ndarray, gyro_B: np.ndarray
    # ):
    #     """Compute elbow flexion/extension and pronation/supination."""
    #     R_rel = R_A.T @ R_B
    #     flexion = np.degrees(np.arctan2(R_rel[2, 1], R_rel[2, 2]))
    #     # theta_fe = atan2(
    #     #     np.dot(a, np.cross(ref_vec, rotated_vec)),
    #     #     np.dot(ref_vec, rotated_vec)
    #     # )

    #     pronation = np.degrees(np.arctan2(R_rel[1, 0], R_rel[0, 0]))
    #     return flexion, pronation

    def update_angles(
        self,
        R_A: np.ndarray,
        gyro_A: np.ndarray,
        R_B: np.ndarray,
        gyro_B: np.ndarray,
    ):
        """
        Compute elbow flexion/extension and pronation/supination
        using axis projection (Euler-free).
        """

        # Relative rotation of forearm in upper-arm frame
        R_rel = R_A.T @ R_B

        # --- Define anatomical axes ---
        # Flexion axis (in upper-arm frame)
        a_FE = np.array([1.0, 0.0, 0.0])   # EDIT if needed

        # Pronation axis (in forearm frame)
        b_PS = np.array([1.0, 0.0, 0.0])   # EDIT if needed

        # --- FLEXION / EXTENSION ---
        # Choose a reference vector orthogonal to FE axis
        # (e.g., humerus longitudinal axis)
        ref_FE = np.array([0.0, 0.0, 1.0])  # EDIT if needed

        # Rotate forearm reference into upper-arm frame
        ref_FE_rot = R_rel @ ref_FE

        # Signed angle around FE axis
        flexion = np.degrees(
            np.arctan2(
                np.dot(a_FE, np.cross(ref_FE, ref_FE_rot)),
                np.dot(ref_FE, ref_FE_rot),
            )
        )

        # --- PRONATION / SUPINATION ---
        # Bring PS axis into upper-arm frame
        b_PS_in_A = R_rel @ b_PS

        # Choose reference orthogonal to PS axis
        ref_PS = np.array([0.0, 1.0, 0.0])  # EDIT if needed

        ref_PS_rot = R_rel @ ref_PS

        pronation = np.degrees(
            np.arctan2(
                np.dot(b_PS_in_A, np.cross(ref_PS, ref_PS_rot)),
                np.dot(ref_PS, ref_PS_rot),
            )
        )

        return flexion, pronation


# Alignment-free, self-calibrating elbow FE/PS angles (Müller et al., 2016)
# - Real-time axis estimation via gradient descent on the windowed cost
# - Two-stage step size, low-pass filtered cost, motion thresholds
# - Angle extraction via small Gauss-Newton solve on orientation (no orthogonality assumption)
#
# Inputs per sample (from main): R_A, gyro_A, R_B, gyro_B
# Outputs: flexion_deg, pronation_deg


# ----------------------- Rotation utilities -----------------------
import numpy as np


def skew(v: np.ndarray) -> np.ndarray:
    x, y, z = v
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])


def vee(M: np.ndarray) -> np.ndarray:
    """Return the vector whose cross-product matrix equals ``M``'s skew part."""
    return 0.5 * np.array(
        [M[2, 1] - M[1, 2], M[0, 2] - M[2, 0], M[1, 0] - M[0, 1]]
    )


def exp_so3(v: np.ndarray) -> np.ndarray:
    """Exponential map SO(3): rotation matrix from rotation vector v."""
    theta = np.linalg.norm(v)
    if theta < 1e-12:
        return np.eye(3) + skew(v)
    k = v / theta
    K = skew(k)
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def log_so3(R: np.ndarray) -> np.ndarray:
    """Return the axis-angle vector associated with a 3x3 rotation matrix.

    The function evaluates the principal matrix logarithm on ``SO(3)`` so that
    the resulting vector ``w`` encodes the rotation axis in its direction and
    the rotation magnitude (radians) in its norm. Close to the identity rotation
    we short-circuit to the zero vector to avoid numerical blow-ups in the
    ``sin(theta)`` denominator.

    Parameters
    ----------
    R : np.ndarray
        Proper 3x3 rotation matrix.

    Returns
    -------
    np.ndarray
        Axis-angle vector ``w`` whose norm equals the rotation angle in radians.
    """
    cos_theta = (np.trace(R) - 1.0) * 0.5
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    theta = np.arccos(cos_theta)
    if theta < 1e-12:
        return np.array([0.0, 0.0, 0.0])
    w = (1 / (2 * np.sin(theta))) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]
    )
    return theta * w


def normalize(v: np.ndarray) -> np.ndarray:
    """Return the input vector normalized to unit length, guarding zero norm."""
    n = np.linalg.norm(v)
    return v if n == 0 else v / n

# ----------------------- Axis parameterization -----------------------


def spherical_to_cartesian(theta: float, rho: float) -> np.ndarray:
    """Convert spherical coordinates to a unit Cartesian vector.
    Physics convention for spherical coordinates are used.
    Radius = 1 (unit vector)
    Parameters
    ----------
    theta : float
        Polar angle measured from positive z-axis (0 ≤ theta ≤ π).
    rho : float
        Azimuthal angle around Z measured from +X (−π < rho ≤ π).
    
    Returns
    -------
    np.ndarray
        3-element unit vector ``[x, y, z]`` on the unit sphere.

    """
    x = np.sin(theta) * np.cos(rho)
    y = np.sin(theta) * np.sin(rho)
    z = np.cos(theta)
    return np.array([x, y, z])


def dcart_dtheta(theta: float, rho: float) -> np.ndarray:
    """Partial derivative of spherical-to-Cartesian mapping w.r.t. polar angle θ."""
    x = np.cos(theta) * np.cos(rho)
    y = np.cos(theta) * np.sin(rho)
    z = -np.sin(theta)
    return np.array([x, y, z])


def dcart_drho(theta: float, rho: float) -> np.ndarray:
    """Partial derivative of spherical-to-Cartesian mapping w.r.t. azimuthal angle ρ."""
    x = -np.sin(theta) * np.sin(rho)
    y = np.sin(theta) * np.cos(rho)
    z = 0.0
    return np.array([x, y, z])


def avoid_spherical_singularity(theta):
    """
    Avoid spherical singularity (θ near 0 or π) by temporarily reparameterizing the axis
    with a 90° frame rotation.
    sin(2')≈0.0349, so this should not affect results much.
    """
    eps = np.deg2rad(2.0)
    if theta < eps:
        theta = eps
    if theta > np.pi - eps:
        theta = np.pi - eps
    return theta

# ----------------------- Estimator class -----------------------


class AlignmentFreeElbowEstimator:
    """
    Real-time, alignment-free estimator of FE (alpha) and PS (beta).
    Follows Müller et al. 2016:
      - ω_r^A = -ω_A^A + R_BA ω_B^B
      - Find a_A (in A) and b_B (in B) minimizing off-plane motion cost
      - Angles from generalized decomposition (here solved numerically)
    """

    def __init__(self, sample_rate_hz: float = 100.0):
        self.dt = 1.0 / sample_rate_hz

        # Paper defaults
        self.window_size = 100  # window size
        self.step_ini = 0.02  # initial step (rad)
        self.step_fin = 0.004  # final step (rad)
        self.cost_thresh = 0.01  # J_LP threshold
        self.min_axis_speed = 0.1  # rad/s (|alpha_dot|, |beta_dot|)
        self.min_omega_r = 0.01  # ignore near-zero relative speed

        # Initial axes (spherical) φ0 = [45°,45°, 90°,45°]
        self.theta_a = np.deg2rad(45.0)
        self.rho_a = np.deg2rad(45.0)
        self.theta_b = np.deg2rad(90.0)
        self.rho_b = np.deg2rad(45.0)

        # State
        self.err_window: list[float] = []
        self.cost_lp = 0.0
        self.converged = False

        # Zero offsets
        self.alpha0 = 0.0
        self.beta0 = 0.0
        self.has_zero = False
        self.alpha_prev = None
        self.beta_prev = None

    def unwrap(self, angle, prev_angle):
        if prev_angle is None:
            return angle
        delta = angle - prev_angle
        # Wrap delta to (-π, π]
        delta = (delta + np.pi) % (2 * np.pi) - np.pi
        return prev_angle + delta


    def current_axes(self) -> tuple[np.ndarray, np.ndarray]:
        a_A = normalize(spherical_to_cartesian(self.theta_a, self.rho_a))
        b_B = normalize(spherical_to_cartesian(self.theta_b, self.rho_b))
        return a_A, b_B

    def relative(
        self, R_A: np.ndarray, R_B: np.ndarray, gyro_A: np.ndarray, gyro_B: np.ndarray
    ):
        """Compute the relative pose and angular velocity used by the estimator.
        Gyros are already measured in their IMU-local frames (A and B)

        Parameters
        ----------
        R_A : np.ndarray
            3x3 rotation matrix of the upper-arm (A) IMU expressed in the world frame.
        R_B : np.ndarray
            3x3 rotation matrix of the forearm (B) IMU expressed in the world frame.
        gyro_A : np.ndarray
            Angular velocity measured by the upper-arm (A) IMU in its local coordinates (rad/s).
        gyro_B : np.ndarray
            Angular velocity measured by the forearm (B) IMU in its local coordinates (rad/s).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            ``R_BA`` (rotation of the forearm expressed in the upper-arm frame) and
            ``omega_r_A`` (relative angular velocity of the forearm expressed in the
            upper-arm frame), where
            ``omega_r_A = -omega_A^A + R_BA * omega_B^B``.
        """
        R_BA = R_A.T @ R_B
        omega_r_A = -gyro_A + R_BA @ gyro_B
        return R_BA, omega_r_A


    def solve_alpha_beta(
        self,
        R_BA: np.ndarray,
        omega_r_A: np.ndarray,
        a_A: np.ndarray,
        b_B: np.ndarray
    ) -> tuple[float, float]:
        """Solve Eq for α and β along the current axes.

        Parameters
        ----------
        R_BA : np.ndarray
            Rotation mapping vectors from the forearm frame ``B`` into the upper-arm frame ``A``.
        omega_r_A : np.ndarray
            Relative angular velocity of the forearm expressed in frame ``A`` (rad/s).
        a_A : np.ndarray
            Flexion/extension axis expressed in frame ``A``.
        b_B : np.ndarray
            Pronation/supination axis expressed in frame ``B``.

        Returns
        -------
        tuple[float, float]
            Least-squares scalars ``alpha`` and ``beta``.
        """
        b_A = R_BA @ b_B
        M = np.column_stack([a_A, b_A])

        MTM = M.T @ M
        if np.linalg.cond(MTM) > 1e8:  # near singular: axes colinear
            MTM = MTM + 1e-6 * np.eye(2)
        x = np.linalg.solve(MTM, M.T @ omega_r_A)  # [α, β]
        alpha, beta = float(x[0]), float(x[1])
        return alpha, beta


    def normalized_velocity_error(
        self,
        R_BA: np.ndarray,
        omega_r_A: np.ndarray,
        a_A: np.ndarray,
        b_B: np.ndarray,
        alpha: float,
        beta: float,
    ) -> np.ndarray:
        """Compute error normalized by ``||omega_r_A||``.

        Returns zero when ``omega_r_A`` is below ``self.min_omega_r`` to avoid
        division by small numbers.
        """
        if np.dot(omega_r_A, omega_r_A) < self.min_omega_r:
            return np.zeros(3)
        e = alpha * a_A + beta * R_BA @ b_B - omega_r_A
        return e / max(np.linalg.norm(omega_r_A), 1e-9)


    def update_cost(self, e_n: np.ndarray) -> float:
        """Update the normalized-error window and return the current cost ``J``."""
        en2 = float(e_n @ e_n)
        self.err_window.append(en2)
        if len(self.err_window) > self.window_size:
            self.err_window.pop(0)
        return float(np.mean(self.err_window)) if self.err_window else 0.0


    def update_step_size(self, J: float) -> float:
        """Low-pass filter the cost and return the current gradient step size.

        The filtered cost ``cost_lp`` is compared against ``cost_thresh`` to decide
        when the estimator has converged. Before convergence we use ``step_ini`` to
        drive faster axis updates, and afterwards we switch to the slower (more
        stable) ``step_fin``.
        """
        self.cost_lp = 0.9 * self.cost_lp + 0.1 * J
        if not self.converged and self.cost_lp < self.cost_thresh:
            self.converged = True
        return self.step_fin if self.converged else self.step_ini


    def axis_projection_terms(
        self, R_BA: np.ndarray, e_n: np.ndarray, alpha: float, beta: float
    ) -> tuple[float, float, float, float]:
        """Compute instantaneous projection terms used in the gradient update.

        Evaluates the dot-product contributions of ``e_n`` with the partial derivatives
        of the spherical axis parameterization (Eq. 12 of Müller et al. 2016).
        """
        da_dtheta = dcart_dtheta(self.theta_a, self.rho_a)
        da_drho = dcart_drho(self.theta_a, self.rho_a)
        db_dtheta = dcart_dtheta(self.theta_b, self.rho_b)
        db_drho = dcart_drho(self.theta_b, self.rho_b)

        term_a_theta = alpha * (e_n @ da_dtheta)
        term_a_rho = alpha * (e_n @ da_drho)
        term_b_theta = beta * (e_n @ (R_BA @ db_dtheta))
        term_b_rho = beta * (e_n @ (R_BA @ db_drho))
        return term_a_theta, term_a_rho, term_b_theta, term_b_rho


    def gradient_direction(
        self,
        R_BA: np.ndarray,
        e_n: np.ndarray,
        alpha: float,
        beta: float,
        up_a: bool,
        up_b: bool,
    ) -> np.ndarray:
        """Return the normalized gradient vector over (θ_a, ρ_a, θ_b, ρ_b).

        Axes that lack sufficient motion have their components zeroed (``up_*`` flags)
        to avoid noisy drift.
        """
        (
            term_a_theta,
            term_a_rho,
            term_b_theta,
            term_b_rho,
        ) = self.axis_projection_terms(R_BA, e_n, alpha, beta)

        g = np.array(
            [
                -2.0 * term_a_theta if up_a else 0.0,
                -2.0 * term_a_rho if up_a else 0.0,
                -2.0 * term_b_theta if up_b else 0.0,
                -2.0 * term_b_rho if up_b else 0.0,
            ]
        )

        gn = np.linalg.norm(g)
        if gn > 0:
            g /= gn
        return g


    def apply_axis_update(self, step: float, direction: np.ndarray) -> None:
        """Apply the gradient step to spherical parameters and wrap azimuths."""
        self.theta_a = avoid_spherical_singularity(self.theta_a + step * direction[0])
        self.rho_a = self.rho_a + step * direction[1]
        self.theta_b = avoid_spherical_singularity(self.theta_b + step * direction[2])
        self.rho_b = self.rho_b + step * direction[3]

        # Wrap the azimuth angles into [-π, π] to keep spherical parameters numerically stable
        for name in ("rho_a", "rho_b"):
            val = getattr(self, name)
            val = (val + np.pi) % (2 * np.pi) - np.pi
            setattr(self, name, val)


    def gradient_step(self, R_BA: np.ndarray, omega_r_A: np.ndarray):
        """Run one gradient-descent iteration on the anatomical axes.

        The method solves for the instantaneous angular rates ``alpha`` and
        ``beta`` along the current axis estimates, builds the normalized velocity
        residual, updates the sliding cost window and adaptive step size, and
        finally applies the gradient step to the spherical parameters.

        Parameters
        ----------
        R_BA : np.ndarray
            3x3 rotation matrix mapping vectors from the forearm frame ``B`` into
            the upper-arm frame ``A``.
        omega_r_A : np.ndarray
            Relative angular velocity of the forearm expressed in frame ``A`` (rad/s).

        Returns
        -------
        tuple[float, float, float, float]
            ``(alpha, beta, J, cost_lp)`` where ``alpha`` and ``beta`` are the
            solved axis-aligned rates, ``J`` is the current normalized-error cost,
            and ``cost_lp`` is its low-pass filtered version used to adapt the
            step size and convergence flag.
        """
        a_A, b_B = self.current_axes()
        alpha, beta = self.solve_alpha_beta(R_BA, omega_r_A, a_A, b_B)
        e_n = self.normalized_velocity_error(R_BA, omega_r_A, a_A, b_B, alpha, beta)

        # Cost update and step size
        J = self.update_cost(e_n)
        step = self.update_step_size(J)

        # thresholds: if little motion around axis, freeze its update
        up_a = abs(alpha) > self.min_axis_speed
        up_b = abs(beta) > self.min_axis_speed

        g = self.gradient_direction(R_BA, e_n, alpha, beta, up_a, up_b)

        self.apply_axis_update(step, g)

        return alpha, beta, J, self.cost_lp

    # --------------- Angle extraction (generalized Euler via small solve) ---------------

    def initial_angle_guess(
        self, R_BA: np.ndarray, a_A: np.ndarray, b_A: np.ndarray
    ) -> tuple[float, float]:
        """Project the rotation log onto the current axes to seed Gauss-Newton.

        Parameters
        ----------
        R_BA : np.ndarray
            Orientation of the forearm frame expressed in the upper-arm frame.
        a_A : np.ndarray
            Flexion/extension axis expressed in frame ``A``.
        b_A : np.ndarray
            Pronation/supination axis expressed in frame ``A`` (``R_BA @ b_B``).

        Returns
        -------
        tuple[float, float]
            Least-squares solution ``(alpha, beta)`` that best approximates the
            rotation vector along the provided axes.
        """
        rvec = log_so3(R_BA)
        A = np.column_stack([a_A, b_A])  # 3x2
        x0, *_ = np.linalg.lstsq(A, rvec, rcond=None)
        return float(x0[0]), float(x0[1])

    def solve_angles_from_orientation(self, R_BA: np.ndarray) -> tuple[float, float]:
        """
        Estimate flexion/extension (α) and pronation/supination (β) angles
        from the relative orientation matrix R_BA.

        Parameters
        ----------
        R_BA : np.ndarray, shape (3, 3)
            Relative rotation matrix expressing frame B (forearm IMU)
            with respect to frame A (upper arm IMU).

        Returns
        -------
        alpha : float
            Flexion/extension angle (radians), rotation about a_A.
        beta : float
            Pronation/supination angle (radians), rotation about b_B.

        Model
        -----
        The relative orientation is modeled as a sequential rotation:

            R_BA ≈ exp(α [a_A]^ ) · exp(β [b_A]^ )

        where:
            a_A : FE axis expressed in frame A
            b_A : PS axis expressed in frame A
                (computed from b_B via b_A = R_BA · b_B)

        Because this equation is nonlinear in α and β, the angles
        are solved using a small Gauss–Newton refinement (2–3 iterations)
        minimizing the orientation error in SO(3).

        Notes
        -----
        - Axes a_A and b_B must be pre-estimated by the calibration routine.
        - The method works even if axes are not orthogonal.
        - Returned angles are raw (zero-offset correction applied elsewhere).

        """
        a_A, b_B = self.current_axes()
        b_A = normalize(R_BA @ b_B)

        alpha, beta = self.initial_angle_guess(R_BA, a_A, b_A)

        # Gauss–Newton refinement
        for _ in range(3): 
            # Current estimated rotation: R_est = R_a(α) R_b(β)
            R_est = exp_so3(alpha * a_A) @ exp_so3(beta * b_A)
            # orientation error as a 3D rotation vector
            r_err = log_so3(R_est.T @ R_BA)  # should be ~ 0

            if np.linalg.norm(r_err) < 1e-4:
                break

            # Sensitivity of R_est w.r.t α (rotation about a_A)
            J_alpha = -(skew(a_A) @ R_est)
            # Sensitivity of R_est w.r.t β (rotation about b_A)
            J_beta = -(exp_so3(alpha * a_A) @ skew(b_A) @ exp_so3(beta * b_A))

            # Convert 3x3 skew-like matrices to 3D vectors
            v_alpha = vee(J_alpha)
            v_beta = vee(J_beta)
            J = np.column_stack([v_alpha, v_beta])  # 3x2 Jacobian matrix

            # Gauss–Newton update. Solve least-squares problem:
            JTJ = J.T @ J + 1e-6 * np.eye(2)
            d = np.linalg.solve(JTJ, J.T @ r_err)

            # Update angles
            alpha += d[0]
            beta += d[1]

        return alpha, beta

    def update_angles(
        self,
        R_A: np.ndarray,
        gyro_A: np.ndarray,
        R_B: np.ndarray,
        gyro_B: np.ndarray
    ):
        """Advance the estimator by one synchronized pair of IMU samples.

        Parameters
        ----------
        R_A : np.ndarray
            3x3 rotation matrix of the upper-arm (A) IMU expressed in the world frame.
        gyro_A : np.ndarray
            Angular velocity from the upper-arm (A) IMU in rad/s, expressed in its local frame.
        R_B : np.ndarray
            3x3 rotation matrix of the forearm (B) IMU expressed in the world frame.
        gyro_B : np.ndarray
            Angular velocity from the forearm (B) IMU in rad/s, expressed in its local frame.

        Returns
        -------
        tuple[float, float]
            Flexion/extension and pronation/supination angles in degrees after the
            current zero-pose offset is applied.
        """
        # Relative quantities
        R_BA, omega_r_A = self.relative(R_A, R_B, gyro_A, gyro_B)

        # Single-sample gradient step on axes
        self.gradient_step(R_BA, omega_r_A)

        # Angles from orientation with current axes
        alpha, beta = self.solve_angles_from_orientation(R_BA)

        # Zero-pose offset
        if self.has_zero:
            alpha -= self.alpha0
            beta -= self.beta0

        # Unwrap angles to avoid jumps
        alpha = self.unwrap(alpha, self.alpha_prev)
        beta = self.unwrap(beta, self.beta_prev)
        self.alpha_prev = alpha
        self.beta_prev = beta

        return np.rad2deg(alpha), np.rad2deg(beta)

    def set_zero_pose(self, R_A: np.ndarray, R_B: np.ndarray):
        """Call once when user is in your 'zero pose' to store offsets."""
        R_BA = R_A.T @ R_B
        alpha, beta = self.solve_angles_from_orientation(R_BA)
        self.alpha0 = alpha
        self.beta0 = beta
        self.has_zero = True
