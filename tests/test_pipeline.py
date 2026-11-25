"""Pipeline steps 8-12: zero pose, estimator integration, metrics, quality."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.processing.metrics import compute_metrics, sparc
from src.processing.pipeline import run_pipeline
from tests.synthetic import ANCHOR_UPTIME_S, SensorSpec, simulate_session, static_upper_arm

HOLD = (20.0, 30.0)


def fe_profile(t):
    t = np.asarray(t, dtype=float)
    return np.where((t >= HOLD[0]) & (t < HOLD[1]), 60.0, 65 + 35 * np.sin(2 * np.pi * 0.25 * t))


def ps_profile(t):
    t = np.asarray(t, dtype=float)
    return np.where((t >= HOLD[0]) & (t < HOLD[1]), 20.0, 20 + 30 * np.sin(2 * np.pi * 0.17 * t + 1.0))


@pytest.fixture(scope="module")
def session():
    # The upper arm is held still, so the rest window around the zero pose is
    # real rest. (With a swaying upper arm the rest-window bias absorbs that
    # slow motion and the zeroed angles creep by ~0.5 deg/s.)
    return simulate_session(45.0, fe_profile, ps_profile, upper_arm=static_upper_arm)


def run(packets, zero_pose_s=None, stop_s=45.0, app_stats=None):
    return run_pipeline(
        packets,
        uptime_anchor_s=ANCHOR_UPTIME_S,
        stopped_uptime_s=ANCHOR_UPTIME_S + stop_s,
        zero_pose_uptimes=[ANCHOR_UPTIME_S + z for z in (zero_pose_s or [])],
        app_stats=app_stats,
    )


def window(angles, lo, hi):
    return angles[(angles["t_s"] > lo) & (angles["t_s"] < hi) & angles["valid"]]


@pytest.fixture(scope="module")
def zeroed(session):
    return run(session.packets, zero_pose_s=[24.0])


def test_angles_are_near_zero_after_the_zero_pose(zeroed):
    angles = zeroed.angles
    after = window(angles, 24.05, HOLD[1] - 0.1)
    before = window(angles, HOLD[0] + 0.5, 23.95)

    assert len(after) > 500
    assert after["fe_deg"].abs().max() < 3.0
    assert after["ps_deg"].abs().max() < 3.0
    # Not trivially zero: the same static pose reads differently before zeroing.
    assert max(before["fe_deg"].abs().mean(), before["ps_deg"].abs().mean()) > 5.0

    zero_pose = zeroed.quality["zero_pose"]
    assert zero_pose["applied"]
    assert zero_pose["applied_at_t_s"] == pytest.approx(24.0, abs=0.011)
    assert zero_pose["bias_from_zero_pose"] == {"A": True, "B": True}


def test_metrics_use_grid_time_and_post_zero_points(zeroed):
    m = zeroed.metrics
    # Both sensors start 0.3 s after SessionStart; the grid spans the overlap.
    assert m.duration_s == pytest.approx(45.0 - 0.3, abs=0.05)
    assert m.max_flexion is not None and 0.0 <= m.max_extension <= m.max_flexion <= 150.0
    assert -90.0 <= m.max_supination <= m.max_pronation < 90.0
    assert m.rep_count is not None


def test_quality_of_a_clean_session(zeroed):
    q = zeroed.quality
    assert zeroed.quality_ok, q["reasons"]
    assert q["valid_pct"] == pytest.approx(100.0)
    assert q["overlap_ratio"] > 0.95
    for role in ("A", "B"):
        s = q["sensors"][role]
        assert s["lost_total"] == 0
        assert s["clock_residual_ms"] < 5.0
        assert s["effective_rate_hz"] == pytest.approx(100.0, rel=0.001)
    assert q["sensors"]["A"]["drift_ppm"] == pytest.approx(-40.0, abs=5)
    assert q["sensors"]["B"]["drift_ppm"] == pytest.approx(25.0, abs=5)


def test_last_zero_pose_event_is_used(session):
    result = run(session.packets, zero_pose_s=[22.0, 26.0])
    assert result.quality["zero_pose"]["applied_at_t_s"] == pytest.approx(26.0, abs=0.011)
    assert result.quality["zero_pose"]["events"] == 2


def test_without_zero_pose_bias_is_flagged_and_angles_still_computed(session):
    result = run(session.packets)
    assert not result.quality["zero_pose"]["applied"]
    assert result.quality["zero_pose"]["bias_from_zero_pose"] == {"A": False, "B": False}
    assert result.angles["fe_deg"].notna().any()


def test_reprocessing_is_deterministic_and_ignores_duplicates(session, zeroed):
    duplicated = pd.concat([session.packets, session.packets.iloc[::3]], ignore_index=True)
    again = run(duplicated, zero_pose_s=[24.0])
    pd.testing.assert_frame_equal(again.angles, zeroed.angles)
    assert again.metrics == zeroed.metrics
    assert again.quality == zeroed.quality


def test_loss_above_threshold_fails_quality_and_splits_ble_vs_upload():
    sim = simulate_session(
        40.0,
        fe_profile,
        ps_profile,
        spec_b=SensorSpec("B", device_start_s=2410.5, drift_ppm=-25.0, drop_seq=[(1000, 1099), (2000, 2049)]),
    )
    stats = {
        "A": {"received": 3970, "lost_ble": 0, "dropped_overflow": 0},
        "B": {"received": 3820, "lost_ble": 100, "dropped_overflow": 0},
    }
    result = run(sim.packets, zero_pose_s=[24.0], stop_s=40.0, app_stats=stats)

    b = result.quality["sensors"]["B"]
    assert b["lost_total"] == 150
    assert b["lost_ble"] == 100
    assert b["lost_upload"] == 50
    assert b["loss_pct"] > 2.0
    assert not result.quality_ok
    assert "loss_B" in result.quality["reasons"]
    invalid = result.angles[~result.angles["valid"]]
    assert 140 <= len(invalid) <= 160  # ~1.5 s of grid inside the two gaps
    assert invalid["fe_deg"].isna().all()


def test_board_reboot_is_two_segments_not_loss():
    sim = simulate_session(
        40.0, fe_profile, ps_profile, spec_a=SensorSpec("A", first_seq=177_900, reboot_after_s=10.0)
    )
    result = run(sim.packets, zero_pose_s=[24.0], stop_s=40.0)
    a = result.quality["sensors"]["A"]
    assert a["resets"] == 1
    assert a["segments"] == 2
    assert a["lost_total"] == 0
    assert len(a["clock_fits"]) == 2
    downtime = window(result.angles.assign(valid=True), 10.1, 10.9)
    assert not result.angles.loc[downtime.index, "valid"].any()


def test_missing_sensor_gives_no_angles_and_bad_quality(session):
    only_a = session.packets[session.packets["role"] == "A"]
    result = run(only_a, zero_pose_s=[24.0])
    assert result.angles.empty
    assert not result.quality_ok
    assert "no_data_B" in result.quality["reasons"]
    assert result.metrics.rep_count is None


# ------------------------------------------------------------ metrics only


def angles_frame(t, fe, valid=None):
    return pd.DataFrame(
        {"t_s": t, "fe_deg": fe, "ps_deg": np.zeros_like(fe), "valid": np.ones_like(fe, bool) if valid is None else valid}
    )


def test_rep_count_on_known_movement():
    t = np.arange(0, 24, 0.01)
    fe = 10 + 50 * (1 - np.cos(2 * np.pi * t / 4))  # 6 reps of 10 -> 110 -> 10 degrees
    m = compute_metrics(angles_frame(t, fe))
    assert m.rep_count == 6
    assert m.max_flexion == pytest.approx(110.0, abs=0.1)
    assert m.max_extension == pytest.approx(10.0, abs=0.1)
    assert m.duration_s == pytest.approx(23.99)


def test_metrics_skip_invalid_and_pre_zero_points():
    t = np.arange(0, 10, 0.01)
    fe = np.full_like(t, 30.0)
    fe[t < 2] = 140.0  # before the zero pose
    valid = np.ones_like(t, bool)
    fe[500:510] = 149.0
    valid[500:510] = False
    m = compute_metrics(angles_frame(t, fe, valid), from_t_s=2.0)
    assert m.max_flexion == pytest.approx(30.0)


def test_sparc_prefers_smooth_movement():
    t = np.arange(0, 2, 0.01)
    smooth = np.sin(np.pi * t / 2) ** 2  # bell-shaped speed
    jerky = smooth * (1 + 0.5 * np.sin(2 * np.pi * 6 * t))
    assert sparc(smooth, 100.0) > sparc(jerky, 100.0)
    assert sparc(smooth, 100.0) < 0
