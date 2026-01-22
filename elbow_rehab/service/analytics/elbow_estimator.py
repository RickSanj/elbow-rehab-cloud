# calculate_angles.py
# Alignment-free, self-calibrating elbow FE/PS angles (Müller et al., 2016)
# - Real-time axis estimation via gradient descent on the windowed cost
# - Two-stage step size, low-pass filtered cost, motion thresholds
# - Angle extraction via small Gauss-Newton solve on orientation (no orthogonality assumption)
#
# Inputs per sample (from main): R_A, gyro_A, R_B, gyro_B
# Outputs: flexion_deg, pronation_deg


# ----------------------- Rotation utilities -----------------------
from __future__ import annotations
import numpy as np

def skew(v: np.ndarray) -> np.ndarray:
    x, y, z = v
    return np.array([[0, -z, y],
                     [z,  0, -x],
                     [-y, x,  0]])


def exp_so3(v: np.ndarray) -> np.ndarray:
    """Exponential map SO(3): rotation matrix from rotation vector v."""
    theta = np.linalg.norm(v)
    if theta < 1e-12:
        return np.eye(3) + skew(v)
    k = v / theta
    K = skew(k)
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def log_so3(R: np.ndarray) -> np.ndarray:
    """Log map SO(3): rotation vector from rotation matrix R."""
    cos_theta = (np.trace(R) - 1.0) * 0.5
    cos_theta = np.clip(cos_theta, -1.0, 1.0)
    theta = np.arccos(cos_theta)
    if theta < 1e-12:
        return np.array([0.0, 0.0, 0.0])
    w = (1/(2*np.sin(theta))) * \
        np.array([R[2, 1]-R[1, 2], R[0, 2]-R[2, 0], R[1, 0]-R[0, 1]])
    return theta * w


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else v / n

# ----------------------- Axis parameterization -----------------------


def sph_to_cart(theta: float, rho: float) -> np.ndarray:
    # (θ, ρ) → unit vector (x,y,z)
    return np.array([
        np.sin(theta) * np.cos(rho),
        np.sin(theta) * np.sin(rho),
        np.cos(theta)
    ])


def dcart_dtheta(theta: float, rho: float) -> np.ndarray:
    return np.array([
        np.cos(theta) * np.cos(rho),
        np.cos(theta) * np.sin(rho),
        -np.sin(theta)
    ])


def dcart_drho(theta: float, rho: float) -> np.ndarray:
    return np.array([
        -np.sin(theta) * np.sin(rho),
        np.sin(theta) * np.cos(rho),
        0.0
    ])

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
        self.M = 100                          # window size
        self.step_ini = 0.02                  # initial step (rad)
        self.step_fin = 0.004                 # final step (rad)
        self.cost_thresh = 0.01               # J_LP threshold
        self.min_axis_speed = 0.1             # rad/s (|alpha_dot|, |beta_dot|)
        self.min_omega_r = 0.01               # ignore near-zero relative speed

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

    # --------------- Helpers to compute quantities at one timestep ---------------

    def current_axes(self) -> tuple[np.ndarray, np.ndarray]:
        a_A = normalize(sph_to_cart(self.theta_a, self.rho_a))
        b_B = normalize(sph_to_cart(self.theta_b, self.rho_b))
        return a_A, b_B

    def relative(self, R_A: np.ndarray, R_B: np.ndarray, gyro_A: np.ndarray, gyro_B: np.ndarray):
        """
        Returns R_BA (B in A), ω_A^A (local), ω_B^B (local), and ω_r^A per paper (Eq. 1)
        """
        R_BA = R_A.T @ R_B
        # gyros are already measured in their IMU-local frames (A and B)
        omega_r_A = -gyro_A + R_BA @ gyro_B
        return R_BA, omega_r_A

    # --------------- Compute α_k, β_k, normalized error e_n,k and cost increment ---------------

    def alphas_betas_error(self, R_BA: np.ndarray, omega_r_A: np.ndarray, a_A: np.ndarray, b_B: np.ndarray):
        """
        Given axes a_A, b_B, compute least-squares α, β (Eq. 3) and normalized error e_n (Eq. 6).
        """
        b_A = R_BA @ b_B
        M = np.column_stack([a_A, b_A])         # 3x2
        # Moore-Penrose via normal equations (2x2)
        MTM = M.T @ M
        if np.linalg.cond(MTM) > 1e8:  # near singular: axes colinear
            MTM = MTM + 1e-6 * np.eye(2)
        x = np.linalg.solve(MTM, M.T @ omega_r_A)  # [α, β]
        alpha, beta = float(x[0]), float(x[1])
        # error
        if np.dot(omega_r_A, omega_r_A) < self.min_omega_r:
            e_n = np.zeros(3)
        else:
            recon = alpha * a_A + beta * b_A
            e = recon - omega_r_A
            e_n = e / max(np.linalg.norm(omega_r_A), 1e-9)
        return alpha, beta, e_n

    # --------------- Gradient step on spherical parameters (Eq. 12, 13-15) ---------------

    def gradient_step(self, R_BA: np.ndarray, omega_r_A: np.ndarray):
        a_A, b_B = self.current_axes()
        alpha, beta, e_n = self.alphas_betas_error(R_BA, omega_r_A, a_A, b_B)

        # Cost update (windowed mean squared norm of normalized error)
        en2 = float(e_n @ e_n)
        self.err_window.append(en2)
        if len(self.err_window) > self.M:
            self.err_window.pop(0)
        J = float(np.mean(self.err_window)) if self.err_window else 0.0
        # simple IIR as LP of J
        self.cost_lp = 0.9 * self.cost_lp + 0.1 * J

        # step size schedule
        if not self.converged and self.cost_lp < self.cost_thresh:
            self.converged = True
        step = self.step_fin if self.converged else self.step_ini

        # thresholds: if little motion around axis, freeze its update
        up_a = abs(alpha) > self.min_axis_speed
        up_b = abs(beta) > self.min_axis_speed

        # Grad of J wrt (θa, ρa, θb, ρb):  -2/N Σ [ α e^T ∂a + β e^T R_BA ∂b ]
        # Here we use instant gradient (stochastic step).
        da_dtheta = dcart_dtheta(self.theta_a, self.rho_a)
        da_drho = dcart_drho(self.theta_a, self.rho_a)
        db_dtheta = dcart_dtheta(self.theta_b, self.rho_b)
        db_drho = dcart_drho(self.theta_b, self.rho_b)

        # projection terms
        term_a_theta = alpha * (e_n @ da_dtheta)
        term_a_rho = alpha * (e_n @ da_drho)
        term_b_theta = beta * (e_n @ (R_BA @ db_dtheta))
        term_b_rho = beta * (e_n @ (R_BA @ db_drho))

        # negative gradient step; normalize to keep stable
        g_a_theta = -2.0 * term_a_theta
        g_a_rho = -2.0 * term_a_rho
        g_b_theta = -2.0 * term_b_theta
        g_b_rho = -2.0 * term_b_rho

        g = np.array([g_a_theta if up_a else 0.0,
                      g_a_rho if up_a else 0.0,
                      g_b_theta if up_b else 0.0,
                      g_b_rho if up_b else 0.0])

        gn = np.linalg.norm(g)
        if gn > 0:
            g /= gn

        # Avoid spherical singularity (θ near 0 or π): temporary 90° frame trick from paper
        def avoid_sing(theta):
            # If too close to 0 or pi, nudge away slightly
            eps = np.deg2rad(2.0)
            if theta < eps:
                theta = eps
            if theta > np.pi-eps:
                theta = np.pi - eps
            return theta

        self.theta_a = avoid_sing(self.theta_a + step * g[0])
        self.rho_a = self.rho_a + step * g[1]
        self.theta_b = avoid_sing(self.theta_b + step * g[2])
        self.rho_b = self.rho_b + step * g[3]

        # wrap rhos into [-pi, pi] for stability
        for name in ("rho_a", "rho_b"):
            val = getattr(self, name)
            val = (val + np.pi) % (2*np.pi) - np.pi
            setattr(self, name, val)

        # return α, β (useful for debug/thresholding) and current cost
        return alpha, beta, J, self.cost_lp

    # --------------- Angle extraction (generalized Euler via small solve) ---------------

    def solve_angles_from_orientation(self, R_BA: np.ndarray) -> tuple[float, float]:
        """
        Solve for angles α (FE about a_A) and β (PS about b_B) such that:
            R_BA ≈ exp( α [a_A]^ ) * exp( β [b_A]^ ),  where b_A = R_BA b_B
        We do a tiny Gauss-Newton (2–3 iterations) on orientation error.
        """
        a_A, b_B = self.current_axes()
        b_A = normalize(R_BA @ b_B)

        # initial guess from projecting rotation vector
        rvec = log_so3(R_BA)
        A = np.column_stack([a_A, b_A])  # 3x2
        x0, *_ = np.linalg.lstsq(A, rvec, rcond=None)
        alpha = float(x0[0])
        beta = float(x0[1])

        for _ in range(3):
            R_est = exp_so3(alpha * a_A) @ exp_so3(beta * b_A)
            r_err = log_so3(R_est.T @ R_BA)  # want this ~ 0

            if np.linalg.norm(r_err) < 1e-4:
                break

            # Jacobian wrt alpha, beta ≈ [-[a_A]^ R_est]^vee and [-R_a [b_A]^]^vee around small error
            # Linearize: R_est * exp([δ]^)^T ≈ R_est (I - [δ]^)
            J_alpha = - (skew(a_A) @ R_est)
            J_beta = - (exp_so3(alpha * a_A) @ skew(b_A) @ exp_so3(beta * b_A))
            # Map to so(3) vector space with vee operator: for small δR ~ I + [v]^, vee([v]^) = v
            # Approx: r_err ≈ J_alpha_vee * dα + J_beta_vee * dβ
            # Use columns as: v_alpha = vee(J_alpha), v_beta = vee(J_beta)
            v_alpha = np.array([J_alpha[2, 1]-J_alpha[1, 2],
                                J_alpha[0, 2]-J_alpha[2, 0],
                                J_alpha[1, 0]-J_alpha[0, 1]]) * 0.5
            v_beta = np.array([J_beta[2, 1]-J_beta[1, 2],
                               J_beta[0, 2]-J_beta[2, 0],
                               J_beta[1, 0]-J_beta[0, 1]]) * 0.5
            J = np.column_stack([v_alpha, v_beta])  # 3x2
            # damped least squares
            JTJ = J.T @ J + 1e-6 * np.eye(2)
            d = np.linalg.solve(JTJ, J.T @ r_err)
            alpha += d[0]
            beta += d[1]

        return alpha, beta

    # --------------- Public API ---------------

    def update(self, R_A: np.ndarray, gyro_A: np.ndarray, R_B: np.ndarray, gyro_B: np.ndarray):
        """
        One real-time step.
        gyro_* must be in rad/s (sensor local axes).
        Returns (flexion_deg, pronation_deg).
        """
        # 1) Relative quantities
        R_BA, omega_r_A = self.relative(R_A, R_B, gyro_A, gyro_B)

        # 2) Single-sample gradient step on axes
        self.gradient_step(R_BA, omega_r_A)

        # 3) Angles from orientation with current axes
        alpha, beta = self.solve_angles_from_orientation(R_BA)

        # 4) Zero-pose offset
        if self.has_zero:
            alpha -= self.alpha0
            beta -= self.beta0

        return np.rad2deg(alpha), np.rad2deg(beta)

    def set_zero_pose(self, R_A: np.ndarray, R_B: np.ndarray):
        """Call once when user is in your 'zero pose' to store offsets."""
        R_BA = R_A.T @ R_B
        alpha, beta = self.solve_angles_from_orientation(R_BA)
        self.alpha0 = alpha
        self.beta0 = beta
        self.has_zero = True
