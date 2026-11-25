from __future__ import annotations
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation as R


from src.utils.logger import get_logger

logger = get_logger()


class SimpleElbowEstimator:
    def __init__(self, sample_rate_hz: float = 100.0):
        pass

    def set_debug_log_path(
        self,
        log_path: str | Path | None,
        *,
        sample_indices: set[int] | list[int] | tuple[int, ...] | None = None,
    ) -> None:
        """Simple estimator does not emit orientation-solver debug logs."""
        return None

    def rpy_to_matrix(self, roll, pitch, yaw):
        """Convert roll, pitch, yaw to a 3×3 rotation matrix."""
        return R.from_euler("xyz", [roll, pitch, yaw], degrees=True).as_matrix()

    def normalize_fe(self, angle_deg: float) -> float:
        angle_deg = angle_deg % 360.0
        if angle_deg > 180.0:
            angle_deg = 360.0 - angle_deg
        return max(0.0, min(150.0, angle_deg))

    def normalize_ps(self, angle_deg: float) -> float:
        return (angle_deg + 90.0) % 180.0 - 90.0

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


def skew(v: np.ndarray) -> np.ndarray:
    """Return the skew-symmetric matrix associated with a 3D vector.

    For a vector ``v = [x, y, z]``, this function constructs the matrix
    ``[v]_x`` such that ``[v]_x @ w == np.cross(v, w)`` for any other 3D vector
    ``w``.

    Parameters
    ----------
    v : np.ndarray
        Three-element vector to convert into its cross-product matrix.

    Returns
    -------
    np.ndarray
        3x3 skew-symmetric matrix representing the linear map
        ``w -> v x w``.
    """
    x, y, z = v
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])


def vee(M: np.ndarray) -> np.ndarray:
    """Map a skew-symmetric matrix back to its underlying 3D vector.

    This is the inverse of :func:`skew` on the space of 3x3 skew-symmetric
    matrices. If ``M = skew(v)``, then ``vee(M) == v``.

    Parameters
    ----------
    M : np.ndarray
        3x3 matrix whose skew-symmetric component should be converted to a
        vector.

    Returns
    -------
    np.ndarray
        Three-element vector corresponding to ``M``'s skew part.
    """
    return 0.5 * np.array(
        [M[2, 1] - M[1, 2], M[0, 2] - M[2, 0], M[1, 0] - M[0, 1]]
    )


def exp_so3(v: np.ndarray) -> np.ndarray:
    """Map a rotation vector in ``so(3)`` to a rotation matrix in ``SO(3)``.

    The input ``v`` encodes an axis-angle rotation in vector form: its
    direction is the rotation axis and its norm is the rotation angle in
    radians. The function evaluates the matrix exponential via Rodrigues'
    formula. For very small angles it falls back to the first-order
    approximation ``I + skew(v)`` to avoid numerical issues near zero.

    Parameters
    ----------
    v : np.ndarray
        Three-element rotation vector in the Lie algebra ``so(3)``.

    Returns
    -------
    np.ndarray
        3x3 proper rotation matrix corresponding to the rotation encoded by
        ``v``.
    """
    rot = R.from_rotvec(v)
    rotation_matrix = rot.as_matrix()
    return rotation_matrix


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
    tr = np.trace(R)
    # Clamp for numerical stability to avoid NaNs in arccos
    cos_theta = np.clip((tr - 1) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_theta)

    if theta < 1e-12:
        c = 0.5 * (1 + theta**2 / 6)
    else:
        c = theta / (2 * np.sin(theta))

    w = c * np.array([
        R[2, 1] - R[1, 2],
        R[0, 2] - R[2, 0],
        R[1, 0] - R[0, 1]
    ])
    return w


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
    Firstly, wrap into the standard [0, 2*pi] circle
    Secondly, If it crossed the pole into the other hemisphere
    force it back into [0, pi])
    Lastly, clamp slightly away from the exact poles
    """
    eps = 1e-5
    theta = theta % (2 * np.pi)

    if theta > np.pi:
        theta = 2 * np.pi - theta

    return float(np.clip(theta, eps, np.pi - eps))

# ----------------------- Estimator class -----------------------


class AlignmentFreeElbowEstimator:
    """
    Real-time, alignment-free estimator of FE (alpha) and PS (beta).
    Follows Müller et al. 2016:
      - ω_r^A = -ω_A^A + R_AB ω_B^B
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
        self.debug_log_path: Path | None = None
        self.debug_sample_index = 0
        self.debug_sample_indices: set[int] | None = None
        self.last_orientation_solve_debug: dict[str, object] = {}
        self.use_gauss_newton_refinement = True

        # Angle extraction relative to a reference orientation (see
        # solve_angles_referenced). False keeps the original absolute solve
        # (R_AB ~ exp(alpha a) exp(beta b), no mounting rotation) for comparison.
        self.use_referenced_solve = True
        self.R_ref: np.ndarray | None = None
        self.ref_angles = np.zeros(2)  # warm start [d_alpha, d_beta]

    def unwrap(self, angle, prev_angle):
        if prev_angle is None:
            return angle
        delta = angle - prev_angle
        # Wrap delta to (-π, π]
        delta = (delta + np.pi) % (2 * np.pi) - np.pi
        return prev_angle + delta

    def set_debug_log_path(
        self,
        log_path: str | Path | None,
        *,
        sample_indices: set[int] | list[int] | tuple[int, ...] | None = None,
    ) -> None:
        """Configure the session-scoped text file used for angle debug logs."""
        if log_path is None:
            self.debug_log_path = None
            self.debug_sample_index = 0
            self.debug_sample_indices = None
            self.last_orientation_solve_debug = {}
            return

        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("AlignmentFreeElbowEstimator debug log\n\n", encoding="utf-8")
        self.debug_log_path = path
        self.debug_sample_index = 0
        self.debug_sample_indices = (
            {int(idx) for idx in sample_indices} if sample_indices is not None else None
        )
        self.last_orientation_solve_debug = {}

    def append_debug_log(self, *lines: str) -> None:
        """Append plain-text debug lines when file logging is enabled."""
        if self.debug_log_path is None:
            return

        with self.debug_log_path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(f"{line}\n")

    def should_log_debug_sample(self, sample_index: int) -> bool:
        """Return whether ``sample_index`` should be written to the debug log."""
        return (
            self.debug_sample_indices is None
            or sample_index in self.debug_sample_indices
        )

    @staticmethod
    def format_debug_value(value: object) -> str:
        """Format vectors and matrices compactly for the text debug log."""
        if isinstance(value, np.ndarray):
            return np.array2string(value, precision=6, separator=", ")
        if isinstance(value, (list, tuple)):
            return np.array2string(np.asarray(value, dtype=float), precision=6, separator=", ")
        return str(value)

    def log_orientation_solution(self, alpha: float, beta: float) -> None:
        """Record the raw orientation-solver output for one sample."""
        if self.debug_log_path is None:
            return

        self.debug_sample_index += 1
        if not self.should_log_debug_sample(self.debug_sample_index):
            return

        gauss_newton_steps = self.last_orientation_solve_debug.get(
            "gauss_newton_steps", []
        )
        final_iteration_residuals = self.last_orientation_solve_debug.get(
            "final_iteration_residuals", []
        )
        step_lines: list[str] = []
        for step_info in gauss_newton_steps:
            iteration = step_info["iteration"]
            trial_residuals = step_info.get("trial_residuals", {})
            trial_residuals_str = ", ".join(
                f"{name}={value:.6f}" for name, value in trial_residuals.items()
            )
            step_lines.extend(
                [
                    f"r_err_before (iter {iteration}): {self.format_debug_value(step_info['r_err_before'])}",
                    f"r_err_before_norm (iter {iteration}): {step_info['r_err_before_norm']}",
                    f"J (iter {iteration}): {self.format_debug_value(step_info['J'])}",
                    f"d_unclipped (iter {iteration}): {self.format_debug_value(step_info['d_unclipped'])}",
                    f"d_clipped (iter {iteration}): {self.format_debug_value(step_info['d_clipped'])}",
                    f"r_err_after (iter {iteration}): {self.format_debug_value(step_info['r_err_after'])}",
                    f"r_err_after_norm (iter {iteration}): {step_info['r_err_after_norm']}",
                    f"one-step trial residuals (iter {iteration}): {trial_residuals_str}",
                ]
            )
        final_residual_lines = [
            (
                f"final residual after {step_info['iteration']} iteration"
                f"{'' if step_info['iteration'] == 1 else 's'}: {step_info['r_err_norm_after']}"
            )
            for step_info in final_iteration_residuals
        ]
        self.append_debug_log(
            f"sample: {self.debug_sample_index}",
            "selected_for_detailed_logging: True",
            f"alpha raw (rad): {alpha}",
            f"beta raw  (rad): {beta}",
            f"alpha deg: {np.rad2deg(alpha)}",
            f"Gauss-Newton refinement enabled: {self.last_orientation_solve_debug.get('gauss_newton_refinement_enabled')}",
            f"R_AB: {self.format_debug_value(self.last_orientation_solve_debug.get('R_AB'))}",
            f"a_A: {self.format_debug_value(self.last_orientation_solve_debug.get('a_A'))}",
            f"b_B: {self.format_debug_value(self.last_orientation_solve_debug.get('b_B'))}",
            f"b_A: {self.format_debug_value(self.last_orientation_solve_debug.get('b_A'))}",
            f"||r_err||: {self.last_orientation_solve_debug.get('r_err_norm')}",
            f"alpha0 from initial_angle_guess (rad): {self.last_orientation_solve_debug.get('initial_alpha')}",
            f"beta0 from initial_angle_guess (rad): {self.last_orientation_solve_debug.get('initial_beta')}",
            f"residual norm at initial guess: {self.last_orientation_solve_debug.get('initial_residual_norm')}",
            f"residual at initial guess: {self.format_debug_value(self.last_orientation_solve_debug.get('initial_residual'))}",
            *step_lines,
            *final_residual_lines,
            "",
        )

    def orientation_residual(
        self,
        R_AB: np.ndarray,
        a_A: np.ndarray,
        b_A: np.ndarray,
        alpha: float,
        beta: float,
    ) -> tuple[np.ndarray, float]:
        """Return the SO(3) residual vector and its norm for ``(alpha, beta)``."""
        R_est = exp_so3(alpha * a_A) @ exp_so3(beta * b_A)
        r_err = log_so3(R_est.T @ R_AB)
        return r_err, float(np.linalg.norm(r_err))

    def trial_residuals_for_step(
        self,
        R_AB: np.ndarray,
        a_A: np.ndarray,
        b_A: np.ndarray,
        alpha: float,
        beta: float,
        d_unclipped: np.ndarray,
        d_clipped: np.ndarray,
    ) -> dict[str, float]:
        """Compare one-step residual norms for several update sign conventions."""
        conventions = {
            "plus_unclipped": d_unclipped,
            "minus_unclipped": -d_unclipped,
            "plus_clipped": d_clipped,
            "minus_clipped": -d_clipped,
        }
        trial_residuals: dict[str, float] = {}
        for name, step in conventions.items():
            _, residual_norm = self.orientation_residual(
                R_AB,
                a_A,
                b_A,
                alpha + float(step[0]),
                beta + float(step[1]),
            )
            trial_residuals[name] = residual_norm
        return trial_residuals


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
            ``R_AB`` (rotation of the forearm expressed in the upper-arm frame) and
            ``omega_r_A`` (relative angular velocity of the forearm expressed in the
            upper-arm frame), where
            ``omega_r_A = -omega_A^A + R_AB * omega_B^B``.
        """
        R_AB = R_A.T @ R_B
        omega_r_A = -gyro_A + R_AB @ gyro_B
        return R_AB, omega_r_A


    def solve_alpha_beta(
        self,
        R_AB: np.ndarray,
        omega_r_A: np.ndarray,
        a_A: np.ndarray,
        b_B: np.ndarray
    ) -> tuple[float, float]:
        """Solve Eq for α and β along the current axes.

        Parameters
        ----------
        R_AB : np.ndarray
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
        b_A = R_AB @ b_B
        M = np.column_stack([a_A, b_A])

        MTM = M.T @ M
        if np.linalg.cond(MTM) > 1e8:  # near singular: axes colinear
            MTM = MTM + 1e-6 * np.eye(2)
        x = np.linalg.solve(MTM, M.T @ omega_r_A)  # [α, β]
        alpha, beta = float(x[0]), float(x[1])
        return alpha, beta


    def normalized_velocity_error(
        self,
        R_AB: np.ndarray,
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
        omega_mag_sq = float(np.dot(omega_r_A, omega_r_A))
        if omega_mag_sq < (self.min_omega_r ** 2):
            return np.zeros(3)
        e = alpha * a_A + beta * (R_AB @ b_B) - omega_r_A
        return e / np.sqrt(omega_mag_sq)


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
        self, R_AB: np.ndarray, e_n: np.ndarray, alpha: float, beta: float
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
        term_b_theta = beta * (e_n @ (R_AB @ db_dtheta))
        term_b_rho = beta * (e_n @ (R_AB @ db_drho))
        return term_a_theta, term_a_rho, term_b_theta, term_b_rho


    def gradient_direction(
        self,
        R_AB: np.ndarray,
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
        ) = self.axis_projection_terms(R_AB, e_n, alpha, beta)

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


    def gradient_step(self, R_AB: np.ndarray, omega_r_A: np.ndarray):
        """Run one gradient-descent iteration on the anatomical axes.

        The method solves for the instantaneous angular rates ``alpha`` and
        ``beta`` along the current axis estimates, builds the normalized velocity
        residual, updates the sliding cost window and adaptive step size, and
        finally applies the gradient step to the spherical parameters.

        Parameters
        ----------
        R_AB : np.ndarray
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
        alpha, beta = self.solve_alpha_beta(R_AB, omega_r_A, a_A, b_B)
        e_n = self.normalized_velocity_error(R_AB, omega_r_A, a_A, b_B, alpha, beta)

        # Cost update and step size
        J = self.update_cost(e_n)
        step = self.update_step_size(J)

        # thresholds: if little motion around axis, freeze its update
        up_a = abs(alpha) >= self.min_axis_speed
        up_b = abs(beta) >= self.min_axis_speed

        g = self.gradient_direction(R_AB, e_n, alpha, beta, up_a, up_b)

        self.apply_axis_update(step, g)

        return alpha, beta, J, self.cost_lp

    # --------------- Angle extraction (generalized Euler via small solve) ---------------

    def initial_angle_guess(
        self, R_AB: np.ndarray, a_A: np.ndarray, b_A: np.ndarray
    ) -> tuple[float, float]:
        """Project the rotation log onto the current axes to seed Gauss-Newton.

        Parameters
        ----------
        R_AB : np.ndarray
            Orientation of the forearm frame expressed in the upper-arm frame.
        a_A : np.ndarray
            Flexion/extension axis expressed in frame ``A``.
        b_A : np.ndarray
            Pronation/supination axis expressed in frame ``A`` (``R_AB @ b_B``).

        Returns
        -------
        tuple[float, float]
            Least-squares solution ``(alpha, beta)`` that best approximates the
            rotation vector along the provided axes.
        """
        rvec = log_so3(R_AB)
        A = np.column_stack([a_A, b_A])  # 3x2
        x0, *_ = np.linalg.lstsq(A, rvec, rcond=None)
        return float(x0[0]), float(x0[1])

    def solve_angles_from_orientation(self, R_AB: np.ndarray) -> tuple[float, float]:
        """
        Estimate flexion/extension (α) and pronation/supination (β) angles
        from the relative orientation matrix R_AB.

        Parameters
        ----------
        R_AB : np.ndarray, shape (3, 3)
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

            R_AB ≈ exp(α [a_A]^ ) · exp(β [b_A]^ )

        where:
            a_A : FE axis expressed in frame A
            b_A : PS axis expressed in frame A
                (computed from b_B via b_A = R_AB · b_B)

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
        b_A = normalize(R_AB @ b_B)

        alpha, beta = self.initial_angle_guess(R_AB, a_A, b_A)
        initial_alpha = alpha
        initial_beta = beta
        alpha_work = alpha
        beta_work = beta
        prev_alpha = alpha_work
        prev_beta = beta_work
        r_err_initial, r_err_norm = self.orientation_residual(
            R_AB, a_A, b_A, alpha, beta
        )
        gauss_newton_steps: list[dict[str, object]] = []
        final_iteration_residuals: list[dict[str, object]] = []
        refinement_aborted_on_large_residual = False

        # Gauss–Newton refinement
        for iteration in range(3):
            r_err, r_err_norm = self.orientation_residual(
                R_AB, a_A, b_A, alpha_work, beta_work
            )

            if r_err_norm < 1e-4:
                break

            # Sensitivity of R_est w.r.t α (rotation about a_A)
            R_est = exp_so3(alpha_work * a_A) @ exp_so3(beta_work * b_A)
            J_alpha = -(skew(a_A) @ R_est)
            # Sensitivity of R_est w.r.t β (rotation about b_A)
            J_beta = -(exp_so3(alpha_work * a_A) @ skew(b_A) @ exp_so3(beta_work * b_A))

            # Convert 3x3 skew-like matrices to 3D vectors
            v_alpha = vee(J_alpha)
            v_beta = vee(J_beta)
            J = np.column_stack([v_alpha, v_beta])  # 3x2 Jacobian matrix

            # Gauss–Newton update. Solve least-squares problem:
            JTJ = J.T @ J + 1e-6 * np.eye(2)
            d_unclipped = np.linalg.solve(JTJ, J.T @ r_err)
            max_step = 0.2  # rad (~11°)
            d = np.clip(d_unclipped, -max_step, max_step)
            trial_residuals = self.trial_residuals_for_step(
                R_AB,
                a_A,
                b_A,
                alpha_work,
                beta_work,
                d_unclipped,
                d,
            )
            alpha_after = alpha_work - float(d[0])
            beta_after = beta_work - float(d[1])
            r_err_after, r_err_after_norm = self.orientation_residual(
                R_AB, a_A, b_A, alpha_after, beta_after
            )
            if r_err_after_norm < r_err_norm:
                # Accept step
                alpha_work = alpha_after
                beta_work  = beta_after
            else:
                # Reject step → stop refinement
                break

            gauss_newton_steps.append(
                {
                    "iteration": iteration + 1,
                    "r_err_before": r_err.copy(),
                    "r_err_before_norm": r_err_norm,
                    "J": J.copy(),
                    "d_unclipped": [float(d_unclipped[0]), float(d_unclipped[1])],
                    "d_clipped": [float(d[0]), float(d[1])],
                    "r_err_after": r_err_after.copy(),
                    "r_err_after_norm": r_err_after_norm,
                    "trial_residuals": trial_residuals,
                }
            )
            final_iteration_residuals.append(
                {
                    "iteration": iteration + 1,
                    "r_err_after": r_err_after.copy(),
                    "r_err_norm_after": r_err_after_norm,
                }
            )

            if r_err_norm > 1.0:
                refinement_aborted_on_large_residual = True
                break

            # Update angles
            alpha_work = alpha_after
            beta_work = beta_after
            prev_alpha = alpha_work
            prev_beta = beta_work

        # Wrap [-p; p]
        if self.use_gauss_newton_refinement:
            if refinement_aborted_on_large_residual:
                alpha = prev_alpha
                beta = prev_beta
            else:
                alpha = alpha_work
                beta = beta_work
            alpha = (alpha + np.pi) % (2 * np.pi) - np.pi
            beta = (beta + np.pi) % (2 * np.pi) - np.pi
        else:
            alpha = initial_alpha
            beta = initial_beta

        final_residual, final_residual_norm = self.orientation_residual(
            R_AB, a_A, b_A, alpha, beta
        )

        self.last_orientation_solve_debug = {
            "gauss_newton_refinement_enabled": self.use_gauss_newton_refinement,
            "R_AB": R_AB.copy(),
            "a_A": a_A.copy(),
            "b_B": b_B.copy(),
            "b_A": b_A.copy(),
            "r_err_norm": final_residual_norm,
            "initial_alpha": float(initial_alpha),
            "initial_beta": float(initial_beta),
            "initial_residual": r_err_initial.copy(),
            "initial_residual_norm": float(np.linalg.norm(r_err_initial)),
            "final_residual": final_residual.copy(),
            "gauss_newton_steps": gauss_newton_steps,
            "final_iteration_residuals": final_iteration_residuals,
        }
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
        R_AB, omega_r_A = self.relative(R_A, R_B, gyro_A, gyro_B)

        # Single-sample gradient step on axes
        self.gradient_step(R_AB, omega_r_A)

        if self.use_referenced_solve:
            if self.R_ref is None:
                # No zero pose yet: angles are relative to the first sample.
                self.R_ref = R_AB.copy()
            d_alpha, d_beta = self.solve_angles_referenced(R_AB)
            self.alpha_prev, self.beta_prev = d_alpha, d_beta
            return np.rad2deg(d_alpha), np.rad2deg(d_beta)

        # Angles from orientation with current axes
        alpha, beta = self.solve_angles_from_orientation(R_AB)
        self.log_orientation_solution(alpha, beta)

        # Zero-pose offset
        if self.has_zero:
            alpha -= self.alpha0
            beta -= self.beta0

        # Unwrap angles to avoid jumps
        # alpha = self.unwrap(alpha, self.alpha_prev)
        # beta = self.unwrap(beta, self.beta_prev)
        self.alpha_prev = alpha
        self.beta_prev = beta

        return np.rad2deg(alpha), np.rad2deg(beta)

    def solve_angles_referenced(
        self, R_AB: np.ndarray, max_iterations: int = 10, tol: float = 1e-9
    ) -> tuple[float, float]:
        """Angle changes since the reference orientation ``R_ref``.

        Joint model (FE axis ``a_A`` fixed in A, PS axis ``b_B`` fixed in B,
        unknown constant mounting rotation ``C``):

            R_AB = exp(alpha a_A) C exp(beta b_B)

        With ``R_ref = R_AB`` at the reference pose the unknown ``C`` cancels:

            R_AB R_ref^T = exp(d_alpha a_A) exp(d_beta c),   c = R_ref b_B

        Solved by Gauss-Newton, warm-started from the previous sample. With
        E = exp(d_alpha a) exp(d_beta c) and r = log(E^T R_AB R_ref^T), the
        first-order model is r(d + delta) = r - [E^T a, c] delta.
        """
        a_A, b_B = self.current_axes()
        c = self.R_ref @ b_B
        target = R_AB @ self.R_ref.T
        x = self.ref_angles.copy()
        for _ in range(max_iterations):
            E = exp_so3(x[0] * a_A) @ exp_so3(x[1] * c)
            r = log_so3(E.T @ target)
            J = np.column_stack([E.T @ a_A, c])
            delta, *_ = np.linalg.lstsq(J, r, rcond=None)
            x = x + delta
            if float(delta @ delta) < tol:
                break
        self.ref_angles = x
        return float(x[0]), float(x[1])

    def set_zero_pose(self, R_A: np.ndarray, R_B: np.ndarray):
        """Call once when user is in your 'zero pose' to store offsets."""
        R_AB = R_A.T @ R_B
        if self.use_referenced_solve:
            # Angles are measured as changes from this orientation.
            self.R_ref = R_AB.copy()
            self.ref_angles = np.zeros(2)
            self.has_zero = True
            logger.debug("Zero pose set (referenced solve)")
            return
        alpha, beta = self.solve_angles_from_orientation(R_AB)
        logger.debug("Zero pose set: alpha0=%.4f rad, beta0=%.4f rad", alpha, beta)
        self.alpha0 = alpha
        self.beta0 = beta
        self.has_zero = True
