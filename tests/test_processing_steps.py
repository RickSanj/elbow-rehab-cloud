"""Pipeline steps 1-7 as pure functions (task section 5.4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.spatial.transform import Rotation

from src.processing.axes import apply_board_mounting_transform, to_filter_frame
from src.processing.bias import estimate_bias
from src.processing.clock import fit_clock
from src.processing.fusion import run_fusion
from src.processing.load import dedup_packets, split_by_role
from src.processing.quaternions import to_rotation
from src.processing.resample import build_grid, resample_sensor
from src.processing.segments import assign_segments
from src.processing.timebase import map_to_session_time
from tests.synthetic import (
    ANCHOR_UPTIME_S,
    SensorSpec,
    constant,
    simulate_sensor,
    simulate_session,
    static_upper_arm,
)


def prepared(packets: pd.DataFrame, role: str):
    seg, report = assign_segments(split_by_role(packets)[role])
    timed, fits = map_to_session_time(seg, ANCHOR_UPTIME_S)
    return to_filter_frame(timed), report, fits


# ------------------------------------------------------------- load/dedup


def test_dedup_keeps_reboot_packets_with_same_seq():
    rows = pd.DataFrame(
        {
            "role": ["A", "A", "A"],
            "seq": [5, 5, 5],
            "device_ts_us": [1_000, 1_000, 900_000],  # 3rd: after reboot
            "ingested_at": pd.to_datetime(["2026-01-01T00:00:02Z", "2026-01-01T00:00:01Z", "2026-01-01T00:00:03Z"]),
        }
    )
    out = dedup_packets(rows)
    assert len(out) == 2
    first = out[out["device_ts_us"] == 1_000].iloc[0]
    assert first["ingested_at"] == pd.Timestamp("2026-01-01T00:00:01Z")


def test_board_mounting_transform_flips_x_and_y_only():
    df = pd.DataFrame({c: [1.0] for c in ["ax", "ay", "az", "gx", "gy", "gz"]})
    out = apply_board_mounting_transform(df)
    assert out.iloc[0].to_dict() == {"ax": -1.0, "ay": -1.0, "az": 1.0, "gx": -1.0, "gy": -1.0, "gz": 1.0}
    assert df["ax"].iloc[0] == 1.0  # input untouched


# ------------------------------------------------------- segments and gaps


def test_reboot_starts_a_new_segment_and_is_not_loss():
    session = simulate_session(
        40.0,
        constant(30),
        constant(0),
        spec_a=SensorSpec("A", first_seq=177_900, reboot_after_s=20.0),
    )
    seg, report = assign_segments(split_by_role(session.packets)["A"])

    assert report.n_segments == 2
    assert report.resets == 1
    assert report.lost_total == 0
    assert report.gaps == []
    second = seg[seg["segment"] == 1]
    assert second["seq"].iloc[0] == 0
    assert seg["break_before"].sum() == 2  # the two segment starts


def test_lost_block_is_counted_as_gap():
    session = simulate_session(30.0, constant(30), constant(0), spec_a=SensorSpec("A", drop_seq=[(1000, 1049)]))
    seg, report = assign_segments(split_by_role(session.packets)["A"])

    assert report.lost_total == 50
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert (gap.after_seq, gap.before_seq, gap.lost) == (999, 1050, 50)
    assert seg.loc[seg["seq"] == 1050, "break_before"].item()
    assert seg.loc[seg["seq"] == 1050, "reinit_before"].item()  # 510 ms > 50 ms


# --------------------------------------------------------------- clock fit


@pytest.mark.parametrize("drift_ppm", [40.0, -60.0])
def test_clock_fit_recovers_offset_and_drift(drift_ppm):
    rng = np.random.default_rng(3)
    duration = 600.0
    spec = SensorSpec("A", device_start_s=1780.0, drift_ppm=drift_ppm)
    sim = simulate_sensor(spec, lambda tau: Rotation.identity(len(tau)), duration, rng)
    packets = sim.packets
    device_s = packets["device_ts_us"].to_numpy() / 1e6

    fit = fit_clock(device_s, packets["phone_rx_s"].to_numpy())

    truth = sim.device_to_phone[0]
    probe = np.linspace(device_s.min(), device_s.max(), 50)
    err_ms = np.abs(fit.to_phone(probe) - truth(probe)) * 1e3
    assert err_ms.max() < 1.0
    expected_ppm = (1.0 / (1.0 + drift_ppm * 1e-6) - 1.0) * 1e6
    assert fit.drift_ppm == pytest.approx(expected_ppm, abs=5.0)
    assert not fit.offset_only
    assert fit.residual_ms < 5.0

    # Raw BLE stamps are much worse than the fit.
    raw_err_ms = (packets["phone_rx_s"].to_numpy() - truth(device_s)) * 1e3
    assert np.percentile(raw_err_ms, 99) > 10.0


def test_short_segment_falls_back_to_offset_only():
    rng = np.random.default_rng(4)
    sim = simulate_sensor(SensorSpec("A"), lambda tau: Rotation.identity(len(tau)), 10.0, rng)
    device_s = sim.packets["device_ts_us"].to_numpy() / 1e6
    fit = fit_clock(device_s, sim.packets["phone_rx_s"].to_numpy())
    assert fit.offset_only
    assert fit.drift == 0.0
    err = np.abs(fit.to_phone(device_s) - sim.device_to_phone[0](device_s))
    assert err.max() < 0.003


def test_session_time_is_phone_time_minus_anchor():
    session = simulate_session(30.0, constant(30), constant(0))
    samples, _, _ = prepared(session.packets, "B")
    truth = session.sensors["B"].device_to_phone[0](samples["device_s"].to_numpy()) - ANCHOR_UPTIME_S
    assert np.abs(samples["t_s"].to_numpy() - truth).max() < 0.002
    assert samples["t_s"].iloc[0] == pytest.approx(0.3, abs=0.01)


# --------------------------------------------------------------------- bias


def moving_then_rest(t):
    # Moving for the first 10 s, then still (zero pose at 12 s), then moving.
    t = np.asarray(t)
    motion = 40 * np.sin(2 * np.pi * 0.4 * t)
    return np.where((t > 10) & (t < 15), 0.0, motion) + 30


def test_bias_from_rest_window_around_zero_pose():
    session = simulate_session(30.0, moving_then_rest, constant(0), upper_arm=static_upper_arm)
    samples, _, _ = prepared(session.packets, "B")

    bias = estimate_bias(samples, zero_pose_t_s=12.0)

    assert bias.found and bias.from_zero_pose
    assert 9.0 <= bias.window_start_s and bias.window_end_s <= 15.0
    np.testing.assert_allclose(bias.gyro_bias, (-0.012, 0.008, 0.02), atol=0.004)
    assert bias.acc_rest_ok


def test_bias_without_zero_pose_is_flagged():
    session = simulate_session(30.0, moving_then_rest, constant(0), upper_arm=static_upper_arm)
    samples, _, _ = prepared(session.packets, "A")

    bias = estimate_bias(samples, zero_pose_t_s=None)

    assert bias.found
    assert not bias.from_zero_pose
    np.testing.assert_allclose(bias.gyro_bias, (0.01, -0.02, 0.015), atol=0.004)


# ------------------------------------------------------------------- fusion


def level_rotation_samples(dt: np.ndarray, rate: float) -> pd.DataFrame:
    n = len(dt)
    return pd.DataFrame(
        {
            "ax": np.zeros(n),
            "ay": np.zeros(n),
            "az": np.full(n, -9.81),  # level in the EKF's NED convention
            "gx": np.zeros(n),
            "gy": np.zeros(n),
            "gz": np.full(n, rate),
            "dt_s": np.concatenate([[np.nan], dt[1:]]),
            "segment": np.zeros(n, dtype=int),
            "reinit_before": np.zeros(n, dtype=bool),
        }
    )


def test_fusion_integrates_with_real_dt():
    rng = np.random.default_rng(5)
    dt = rng.uniform(0.008, 0.016, 500)  # mean 12 ms, nominal 10 ms
    rate = 0.5  # rad/s about the vertical
    samples = level_rotation_samples(dt, rate)

    quaternions, reinit = run_fusion(samples)

    yaw = to_rotation(quaternions[-1]).as_euler("ZYX")[0][0]
    expected = rate * dt[1:].sum()
    assert abs(np.angle(np.exp(1j * (abs(yaw) - expected)))) < np.deg2rad(1.0)
    assert reinit.sum() == 1  # only the first sample


def test_fusion_does_not_integrate_across_a_gap():
    dt = np.full(300, 0.01)
    samples = level_rotation_samples(dt, 0.5)
    samples.loc[150, "dt_s"] = 0.4
    samples.loc[150, "reinit_before"] = True

    quaternions, reinit = run_fusion(samples)

    assert reinit[150]
    yaw_before = to_rotation(quaternions[149]).as_euler("ZYX")[0][0]
    yaw_after = to_rotation(quaternions[150]).as_euler("ZYX")[0][0]
    assert yaw_after == pytest.approx(yaw_before, abs=1e-6)  # heading kept, 0.4 s not integrated
    total = abs(to_rotation(quaternions[-1]).as_euler("ZYX")[0][0])
    assert total == pytest.approx(0.5 * 0.01 * 298, abs=np.deg2rad(1.0))


# ----------------------------------------------------------------- resample


def test_grid_points_inside_a_gap_are_invalid():
    session = simulate_session(30.0, constant(30), constant(0), spec_a=SensorSpec("A", drop_seq=[(1000, 1049)]))
    a, _, _ = prepared(session.packets, "A")
    b, _, _ = prepared(session.packets, "B")
    qa, _ = run_fusion(a)
    qb, _ = run_fusion(b)
    grid = build_grid(a["t_s"].to_numpy(), b["t_s"].to_numpy())

    on_a = resample_sensor(a["t_s"].to_numpy(), qa, a[["gx", "gy", "gz"]].to_numpy(), a["break_before"].to_numpy(), grid)
    on_b = resample_sensor(b["t_s"].to_numpy(), qb, b[["gx", "gy", "gz"]].to_numpy(), b["break_before"].to_numpy(), grid)

    gap_start = a.loc[a["seq"] == 999, "t_s"].item()
    gap_end = a.loc[a["seq"] == 1050, "t_s"].item()
    in_gap = (grid > gap_start) & (grid < gap_end)
    assert in_gap.sum() >= 45
    assert not on_a.valid[in_gap].any()
    assert np.isnan(on_a.quaternions[in_gap]).all()
    assert on_a.valid[~in_gap].all()
    assert on_b.valid.all()
    np.testing.assert_allclose(np.diff(grid), 0.01, atol=1e-9)


def test_moving_sensor_gets_no_bias_instead_of_a_wrong_one():
    always_moving = simulate_session(
        30.0, lambda t: 65 + 35 * np.sin(2 * np.pi * 0.25 * np.asarray(t)), constant(0)
    )
    samples, _, _ = prepared(always_moving.packets, "B")

    bias = estimate_bias(samples, zero_pose_t_s=None)

    assert not bias.found
    assert bias.reason == "no_rest_window"
    assert bias.gyro_bias == (0.0, 0.0, 0.0)
    assert bias.gyro_std > 0.05
