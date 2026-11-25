"""Fusion accuracy check per sensor (not collected by pytest).

    python -m tests.benchmark_fusion [--duration 300]

For each sensor the fused orientation R_f(t) should equal W R_true(t) for a
constant world offset W (the filter's own world frame). The error is the
change of W(t) = R_f(t) R_true(t)^-1 relative to W at t = 2 s, split into
tilt (how far the vertical moved) and heading (rotation about the vertical).
The relative error between A and B is what the elbow angles see.

Checks:
  inputs      filter-frame acc/gyro produced by the pipeline vs the truth
  bias        estimated (rest window at the zero pose) vs true gyro bias
  arm         upper arm swaying vs held still during the zero-pose hold
  filter      EKF / Madgwick / Mahony
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from src.processing.axes import ACC_COLUMNS, GYRO_COLUMNS, to_filter_frame
from src.processing.bias import estimate_bias, remove_gyro_bias
from src.processing.fusion import run_fusion
from src.processing.load import split_by_role
from src.processing.quaternions import to_rotation
from src.processing.segments import assign_segments
from src.processing.timebase import map_to_session_time
from tests.benchmark_estimator import ZERO_POSE_T, fe_truth, ps_truth
from tests.synthetic import (
    ANCHOR_UPTIME_S,
    G,
    body_rates,
    default_upper_arm,
    elbow_rotations,
    simulate_session,
    static_upper_arm,
)

TRUE_BIAS = {"A": (0.01, -0.02, 0.015), "B": (-0.012, 0.008, 0.02)}  # tests/synthetic defaults
REF_T = 2.0


def truth_rotation(role, upper_arm):
    index = 0 if role == "A" else 1
    return lambda t: elbow_rotations(t, fe_truth, ps_truth, upper_arm)[index]


def prepare(session, role):
    seg, _ = assign_segments(split_by_role(session.packets)[role])
    timed, _ = map_to_session_time(seg, ANCHOR_UPTIME_S)
    return to_filter_frame(timed)


def world_drift(t, fused: Rotation, truth: Rotation):
    w = fused * truth.inv()
    i0 = int(np.searchsorted(t, REF_T))
    e = w * w[i0].inv()
    z = np.array([0.0, 0.0, 1.0])
    tilt = np.rad2deg(np.arccos(np.clip(np.abs(e.apply(z) @ z), -1, 1)))
    heading = np.rad2deg(np.abs(e.as_euler("ZYX")[:, 0]))
    return w, tilt, heading


def summary(x, t, after=60.0):
    m = t >= after
    return f"median {np.median(x[m]):6.1f}  max {np.max(x[m]):6.1f}"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    for arm_name, upper_arm in (("swaying arm", default_upper_arm), ("still arm", static_upper_arm)):
        session = simulate_session(args.duration, fe_truth, ps_truth, seed=args.seed, upper_arm=upper_arm)
        print(f"\n=== {arm_name} ({args.duration:.0f} s, errors after 60 s, degrees) ===")
        samples = {role: prepare(session, role) for role in ("A", "B")}

        # 1. inputs: filter-frame samples vs truth (bias + noise removed by comparison)
        for role, s in samples.items():
            t = s["t_s"].to_numpy()
            rot = truth_rotation(role, upper_arm)
            gyro_true = body_rates(rot, t) + np.asarray(TRUE_BIAS[role])
            acc_true = rot(t).inv().apply([0.0, 0.0, G])
            gyro_err = np.abs(s[GYRO_COLUMNS].to_numpy() - gyro_true).mean()
            acc_err = np.abs(s[ACC_COLUMNS].to_numpy() - acc_true).mean()
            print(f"inputs {role}: mean |gyro - truth| {gyro_err:.4f} rad/s, mean |acc - truth| {acc_err:.3f} m/s^2")

        # 2. bias estimate
        for role, s in samples.items():
            est = estimate_bias(s, ZERO_POSE_T)
            err = np.asarray(est.gyro_bias) - np.asarray(TRUE_BIAS[role])
            print(f"bias {role}: estimated - true = {np.round(err, 4)} rad/s (|.|={np.linalg.norm(err):.4f}), "
                  f"window {est.window_start_s:.1f}-{est.window_end_s:.1f} s, found={est.found}")

        # 3./4. fusion error per configuration
        print(f"{'filter':<9} {'bias':<10} {'A tilt':>22} {'A heading':>22} {'B tilt':>22} {'B heading':>22} {'A-B relative':>22}")
        for filter_type in ("ekf", "madgwick", "mahony"):
            for bias_mode in ("estimated", "true"):
                fused, worlds = {}, {}
                for role, s in samples.items():
                    if bias_mode == "true":
                        corrected = s.copy()
                        corrected[GYRO_COLUMNS] = s[GYRO_COLUMNS].to_numpy() - np.asarray(TRUE_BIAS[role])
                    else:
                        corrected = remove_gyro_bias(s, estimate_bias(s, ZERO_POSE_T))
                    q, _ = run_fusion(corrected, filter_type=filter_type)
                    t = s["t_s"].to_numpy()
                    w, tilt, heading = world_drift(t, to_rotation(q), truth_rotation(role, upper_arm)(t))
                    fused[role] = (t, tilt, heading)
                    worlds[role] = pd.Series(range(len(t)), index=t), w
                # relative world drift A vs B on A's timestamps
                ta = fused["A"][0]
                idx_b = np.clip(np.searchsorted(fused["B"][0], ta), 0, len(fused["B"][0]) - 1)
                rel = worlds["A"][1].inv() * worlds["B"][1][idx_b]
                i0 = int(np.searchsorted(ta, REF_T))
                rel_err = np.rad2deg((rel * rel[i0].inv()).magnitude())
                cols = [summary(fused["A"][1], ta), summary(fused["A"][2], ta),
                        summary(fused["B"][1], fused["B"][0]), summary(fused["B"][2], fused["B"][0]),
                        summary(rel_err, ta)]
                print(f"{filter_type:<9} {bias_mode:<10} " + " ".join(f"{c:>22}" for c in cols))


if __name__ == "__main__":
    main()
