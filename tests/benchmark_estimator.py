"""Accuracy benchmark for the elbow-angle estimator (not collected by pytest).

    python -m tests.benchmark_estimator [--duration 300] [--seed 7]

Runs AlignmentFreeElbowEstimator on one synthetic session with known truth,
feeding it three kinds of input on the same 100 Hz grid:

  a_truth     true sensor orientations and true (noise/bias-free) gyro
  a_heading   like a_truth, but sensor B's world frame is rotated 60 deg about
              the vertical (what two magnetometer-free filters produce)
  b_oracle    fused orientations (full pipeline up to the grid), with B's
              heading corrected using the truth
  c_pipeline  fused orientations as the pipeline uses them

Errors are measured on raw estimator output (degrees, no folding) against
the true angle change since the zero pose, after a warm-up period. Because
the estimated joint axes may point either way, each angle is also scored
with flipped sign and the better sign is reported.

Estimators: the original absolute angle solve vs the referenced solve
(default), each with learned axes and with the true axes injected.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation

from src.angle_calculation.estimator import AlignmentFreeElbowEstimator
from src.processing.axes import GYRO_COLUMNS, to_filter_frame
from src.processing.bias import estimate_bias, remove_gyro_bias
from src.processing.fusion import run_fusion
from src.processing.load import split_by_role
from src.processing.quaternions import from_rotation, to_matrices, to_rotation
from src.processing.resample import build_grid, resample_sensor
from src.processing.segments import assign_segments
from src.processing.timebase import map_to_session_time
from tests.synthetic import (
    ANCHOR_UPTIME_S,
    M_A,
    M_B,
    body_rates,
    default_upper_arm,
    elbow_rotations,
    simulate_session,
)

# True joint axes in the sensor frames (see tests/synthetic.elbow_rotations).
TRUE_A = M_A.inv().apply([0.0, 0.0, 1.0])  # FE axis in A
TRUE_B = M_B.inv().apply([0.0, 1.0, 0.0])  # PS axis in B


def make_estimator(referenced: bool, true_axes: bool) -> AlignmentFreeElbowEstimator:
    """referenced=False: the original absolute angle solve (for comparison)."""
    est = AlignmentFreeElbowEstimator(100.0)
    est.use_referenced_solve = referenced
    if true_axes:
        def spherical(v):
            return float(np.arccos(np.clip(v[2], -1, 1))), float(np.arctan2(v[1], v[0]))

        est.theta_a, est.rho_a = spherical(TRUE_A)
        est.theta_b, est.rho_b = spherical(TRUE_B)
        est.min_axis_speed = np.inf  # no axis learning
    return est


ZERO_POSE_T = 4.0
HOLD_END = 8.0


def fe_truth(t):
    t = np.asarray(t, dtype=float)
    move = 70 + 35 * np.sin(2 * np.pi * 0.21 * t) + 15 * np.sin(2 * np.pi * 0.53 * t + 0.4)
    return np.where(t < HOLD_END, 15.0, move)


def ps_truth(t):
    t = np.asarray(t, dtype=float)
    move = 30 * np.sin(2 * np.pi * 0.13 * t + 1.0) + 15 * np.sin(2 * np.pi * 0.37 * t)
    return np.where(t < HOLD_END, 0.0, move)


@dataclass
class Score:
    name: str
    fe_rmse: float
    fe_sign: int
    ps_rmse: float
    ps_sign: int
    fe_max: float
    ps_max: float


def wrap_deg(x):
    return (np.asarray(x) + 180.0) % 360.0 - 180.0


def axis_error_deg(u, v):
    return float(np.rad2deg(np.arccos(min(1.0, abs(float(np.dot(u, v)))))))


def run_estimator(grid, rot_a, gyro_a, rot_b, gyro_b, valid, est=None):
    est = est or AlignmentFreeElbowEstimator(100.0)
    alpha = np.full(len(grid), np.nan)
    beta = np.full(len(grid), np.nan)
    zeroed = False
    for i in np.flatnonzero(valid):
        if not zeroed and grid[i] >= ZERO_POSE_T:
            est.set_zero_pose(rot_a[i], rot_b[i])
            zeroed = True
        alpha[i], beta[i] = est.update_angles(rot_a[i], gyro_a[i], rot_b[i], gyro_b[i])
    return alpha, beta, est


def score(name, grid, alpha, beta, warmup_s):
    m = (grid >= warmup_s) & np.isfinite(alpha)
    fe_ref = fe_truth(grid[m]) - fe_truth(ZERO_POSE_T)
    ps_ref = ps_truth(grid[m]) - ps_truth(ZERO_POSE_T)

    def best(est, ref):
        options = []
        for sign in (1, -1):
            err = wrap_deg(sign * est - ref)
            options.append((float(np.sqrt(np.mean(err**2))), sign, float(np.max(np.abs(err)))))
        return min(options)

    fe_rmse, fe_sign, fe_max = best(alpha[m], fe_ref)
    ps_rmse, ps_sign, ps_max = best(beta[m], ps_ref)
    return Score(name, fe_rmse, fe_sign, ps_rmse, ps_sign, fe_max, ps_max)


def fused_on_grid(session):
    prepared = {}
    for role in ("A", "B"):
        seg, _ = assign_segments(split_by_role(session.packets)[role])
        timed, _ = map_to_session_time(seg, ANCHOR_UPTIME_S)
        samples = to_filter_frame(timed)
        samples = remove_gyro_bias(samples, estimate_bias(samples, ZERO_POSE_T))
        quats, _ = run_fusion(samples)
        prepared[role] = (samples, quats)
    (a, qa), (b, qb) = prepared["A"], prepared["B"]
    grid = build_grid(a["t_s"].to_numpy(), b["t_s"].to_numpy())
    on_a = resample_sensor(a["t_s"].to_numpy(), qa, a[GYRO_COLUMNS].to_numpy(), a["break_before"].to_numpy(), grid)
    on_b = resample_sensor(b["t_s"].to_numpy(), qb, b[GYRO_COLUMNS].to_numpy(), b["break_before"].to_numpy(), grid)
    return grid, on_a, on_b


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--warmup", type=float, default=60.0)
    parser.add_argument("--skip-inputs", default="", help="comma-separated input names to skip")
    args = parser.parse_args(argv)

    session = simulate_session(args.duration, fe_truth, ps_truth, seed=args.seed)
    grid, on_a, on_b = fused_on_grid(session)
    valid = on_a.valid & on_b.valid

    # (a) truth on the same grid
    def true_a(t):
        return elbow_rotations(t, fe_truth, ps_truth, default_upper_arm)[0]

    def true_b(t):
        return elbow_rotations(t, fe_truth, ps_truth, default_upper_arm)[1]

    ta, tb = true_a(grid), true_b(grid)
    ga, gb = body_rates(true_a, grid), body_rates(true_b, grid)
    ra, rb = ta.as_matrix(), tb.as_matrix()
    heading = Rotation.from_euler("z", 60, degrees=True)
    rb_heading = (heading * tb).as_matrix()

    # (b)/(c) fused
    fa = to_matrices(on_a.quaternions[valid])
    fb = to_matrices(on_b.quaternions[valid])
    full_fa = np.full((len(grid), 3, 3), np.nan)
    full_fb = np.full((len(grid), 3, 3), np.nan)
    full_fa[valid], full_fb[valid] = fa, fb
    world_a = to_rotation(on_a.quaternions[valid]) * ta[valid].inv()
    world_b = to_rotation(on_b.quaternions[valid]) * tb[valid].inv()
    fix = Rotation.from_rotvec(np.median((world_a * world_b.inv()).as_rotvec(), axis=0))
    full_fb_fixed = np.full((len(grid), 3, 3), np.nan)
    full_fb_fixed[valid] = to_matrices(from_rotation(fix * to_rotation(on_b.quaternions[valid])))
    mismatch = (world_a.inv() * world_b)
    print(
        f"fused world A vs B: {np.rad2deg(np.median(mismatch.magnitude())):.1f} deg "
        f"(yaw part {np.rad2deg(np.median(mismatch.as_euler('ZYX')[:, 0])):.1f} deg)"
    )

    inputs = {
        "a_truth": (ra, ga, rb, gb),
        "a_heading": (ra, ga, rb_heading, gb),
        "b_oracle": (full_fa, on_a.gyro, full_fb_fixed, on_b.gyro),
        "c_pipeline": (full_fa, on_a.gyro, full_fb, on_b.gyro),
    }
    estimators = {
        "old_absolute+learned": lambda: make_estimator(False, False),
        "old_absolute+true_axes": lambda: make_estimator(False, True),
        "referenced+true_axes": lambda: make_estimator(True, True),
        "referenced+learned": lambda: make_estimator(True, False),
    }
    print(f"duration {args.duration:.0f} s, warm-up {args.warmup:.0f} s, seed {args.seed}")
    header = f"{'input':<11} {'estimator':<23} {'FE rmse':>8} {'FE max':>7} {'sign':>4}   {'PS rmse':>8} {'PS max':>7} {'sign':>4}  axis err A/B"
    print(header)
    for input_name, (r_a, g_a, r_b, g_b) in inputs.items():
        for est_name, make in estimators.items():
            if input_name in args.skip_inputs.split(","):
                continue
            alpha, beta, est = run_estimator(grid, r_a, g_a, r_b, g_b, valid, make())
            s = score(input_name, grid, alpha, beta, args.warmup)
            a_axis, b_axis = est.current_axes()
            print(
                f"{input_name:<11} {est_name:<23} {s.fe_rmse:8.2f} {s.fe_max:7.1f} {s.fe_sign:4d}   "
                f"{s.ps_rmse:8.2f} {s.ps_max:7.1f} {s.ps_sign:4d}  {axis_error_deg(a_axis, TRUE_A):5.1f}/{axis_error_deg(b_axis, TRUE_B):5.1f}"
            )


if __name__ == "__main__":
    main()
