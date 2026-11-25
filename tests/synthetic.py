"""Synthetic two-sensor sessions with known truth.

Model
-----
* True time ``tau`` is the phone's monotonic clock (seconds).
* Each board samples at exactly ``rate_hz`` on its own clock, which runs
  ``drift_ppm`` fast relative to the phone and starts at ``device_start_s``.
* BLE delivers queued packets at connection events (~30 ms apart with jitter
  and occasional ~90 ms gaps); the phone stamps them after an exponential OS
  delay per connection event. Stamps are monotonic in arrival order.
* Kinematics: upper arm orientation R_UA(tau); sensor A = R_UA * M_A;
  sensor B = R_UA * Rz(fe) * Ry(ps) * M_B. Gyro = body angular rate + bias,
  accelerometer = specific force (gravity only) + noise.
* Values are emitted in the *raw board frame*, i.e. the inverse of
  ``src.processing.axes.to_filter_frame`` is applied, exactly as the boards
  would send them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from src.processing.axes import BOARD_MOUNTING_FLIP_COLUMNS, invert_acc_calibration

G = 9.81
ANCHOR_UPTIME_S = 5230.991


@dataclass
class SensorSpec:
    role: str
    device_start_s: float = 1780.0
    drift_ppm: float = 0.0
    gyro_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)  # filter frame, rad/s
    first_seq: int = 0
    start_delay_s: float = 0.3  # first sample after SessionStart
    drop_seq: list[tuple[int, int]] = field(default_factory=list)  # inclusive ranges
    reboot_after_s: float | None = None  # session time of the reboot
    reboot_downtime_s: float = 1.0
    reboot_device_start_s: float = 0.8


@dataclass
class BleSpec:
    interval_s: float = 0.030
    interval_jitter: float = 0.10
    long_gap_prob: float = 0.02
    long_gap_s: float = 0.090
    os_delay_mean_s: float = 0.001


def mount(euler_deg) -> Rotation:
    return Rotation.from_euler("xyz", euler_deg, degrees=True)


M_A = mount([10.0, -15.0, 30.0])
M_B = mount([-20.0, 10.0, 70.0])


def static_upper_arm(tau: np.ndarray) -> Rotation:
    return Rotation.from_euler("zyx", np.tile([0.2, 0.15, 0.1], (len(np.atleast_1d(tau)), 1)))


def default_upper_arm(tau: np.ndarray) -> Rotation:
    # Upper arm hanging with a slow, small sway.
    t = np.asarray(tau, dtype=float)
    return Rotation.from_euler(
        "zyx",
        np.column_stack([0.3 * np.sin(0.05 * t), 0.15 + 0.05 * np.sin(0.11 * t), 0.1 * np.cos(0.07 * t)]),
    )


def elbow_rotations(
    tau: np.ndarray,
    fe_deg: Callable[[np.ndarray], np.ndarray],
    ps_deg: Callable[[np.ndarray], np.ndarray],
    upper_arm: Callable[[np.ndarray], Rotation] = default_upper_arm,
) -> tuple[Rotation, Rotation]:
    r_ua = upper_arm(tau)
    # Intrinsic "ZY": joint = Rz(fe) * Ry(ps). FE about z fixed in the upper
    # arm, then PS about the forearm's own y axis (fixed in the forearm).
    # (Lower-case "zy" would be extrinsic, Ry(ps) * Rz(fe): the wrong joint.)
    joint = Rotation.from_euler(
        "ZY", np.column_stack([fe_deg(tau), ps_deg(tau)]), degrees=True
    )
    return r_ua * M_A, r_ua * joint * M_B


def body_rates(rot_fn: Callable[[np.ndarray], Rotation], tau: np.ndarray, h: float = 1e-4) -> np.ndarray:
    r0, r1 = rot_fn(tau - h / 2), rot_fn(tau + h / 2)
    return (r0.inv() * r1).as_rotvec() / h


def ble_receive_times(tau: np.ndarray, rng: np.random.Generator, ble: BleSpec) -> np.ndarray:
    span = tau[-1] - tau[0] + 1.0
    n_events = int(span / (ble.interval_s * 0.8)) + 10
    intervals = ble.interval_s * (1 + rng.uniform(-ble.interval_jitter, ble.interval_jitter, n_events))
    long = rng.random(n_events) < ble.long_gap_prob
    intervals[long] = ble.long_gap_s
    events = tau[0] - rng.uniform(0, ble.interval_s) + np.cumsum(intervals)
    idx = np.searchsorted(events, tau, side="left")
    # iOS hands over the notifications of one connection event back-to-back:
    # one OS delay per event, plus a few microseconds per packet.
    event_delay = rng.exponential(ble.os_delay_mean_s, n_events)
    position = np.arange(len(tau)) - np.searchsorted(idx, idx, side="left")
    rx = events[idx] + event_delay[idx] + 20e-6 * position
    return np.maximum.accumulate(rx)


def to_raw_frame(acc: np.ndarray, gyro: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    acc_raw = invert_acc_calibration(acc)
    gyro_raw = np.array(gyro, dtype=float)
    flip = {"ax": (acc_raw, 0), "ay": (acc_raw, 1), "gx": (gyro_raw, 0), "gy": (gyro_raw, 1)}
    for column in BOARD_MOUNTING_FLIP_COLUMNS:
        array, axis = flip[column]
        array[:, axis] = -array[:, axis]
    return acc_raw, gyro_raw


@dataclass
class SimulatedSensor:
    packets: pd.DataFrame
    # device seconds -> true phone time, per segment
    device_to_phone: list[Callable[[np.ndarray], np.ndarray]]


def simulate_sensor(
    spec: SensorSpec,
    rot_fn: Callable[[np.ndarray], Rotation],
    duration_s: float,
    rng: np.random.Generator,
    *,
    rate_hz: float = 100.0,
    ble: BleSpec | None = None,
    anchor_uptime_s: float = ANCHOR_UPTIME_S,
    gyro_noise: float = 0.002,
    acc_noise: float = 0.02,
) -> SimulatedSensor:
    ble = ble or BleSpec()
    k = 1.0 + spec.drift_ppm * 1e-6
    session_start = anchor_uptime_s + spec.start_delay_s
    session_end = anchor_uptime_s + duration_s

    segments = []  # (tau_start, tau_end, device_start, first_seq)
    if spec.reboot_after_s is None:
        segments.append((session_start, session_end, spec.device_start_s, spec.first_seq))
    else:
        reboot_tau = anchor_uptime_s + spec.reboot_after_s
        segments.append((session_start, reboot_tau, spec.device_start_s, spec.first_seq))
        segments.append((reboot_tau + spec.reboot_downtime_s, session_end, spec.reboot_device_start_s, 0))

    frames, mappings = [], []
    for tau_start, tau_end, device_start, first_seq in segments:
        n = int((tau_end - tau_start) * k * rate_hz)
        device_s = device_start + np.arange(n) / rate_hz
        tau = tau_start + (device_s - device_start) / k
        mappings.append(lambda d, ts=tau_start, ds=device_start: ts + (np.asarray(d) - ds) / k)

        rot = rot_fn(tau)
        gyro = body_rates(rot_fn, tau) + np.asarray(spec.gyro_bias) + rng.normal(0, gyro_noise, (n, 3))
        acc = rot.inv().apply(np.array([0.0, 0.0, G])) + rng.normal(0, acc_noise, (n, 3))
        acc_raw, gyro_raw = to_raw_frame(acc, gyro)

        seq = first_seq + np.arange(n)
        frame = pd.DataFrame(
            {
                "role": spec.role,
                "seq": seq.astype(np.int64),
                "device_ts_us": np.round(device_s * 1e6).astype(np.int64),
                "phone_rx_s": ble_receive_times(tau, rng, ble),
                "ax": acc_raw[:, 0],
                "ay": acc_raw[:, 1],
                "az": acc_raw[:, 2],
                "gx": gyro_raw[:, 0],
                "gy": gyro_raw[:, 1],
                "gz": gyro_raw[:, 2],
            }
        )
        if first_seq == spec.first_seq:  # drops apply to the first segment's seq numbers
            for lo, hi in spec.drop_seq:
                frame = frame[(frame["seq"] < lo) | (frame["seq"] > hi)]
        frames.append(frame)
    return SimulatedSensor(pd.concat(frames, ignore_index=True), mappings)


def constant(value: float) -> Callable[[np.ndarray], np.ndarray]:
    return lambda tau: np.full(np.shape(tau), float(value))


@dataclass
class SimulatedSession:
    packets: pd.DataFrame
    sensors: dict[str, SimulatedSensor]
    anchor_uptime_s: float
    fe_deg: Callable[[np.ndarray], np.ndarray]
    ps_deg: Callable[[np.ndarray], np.ndarray]


def simulate_session(
    duration_s: float,
    fe_deg: Callable[[np.ndarray], np.ndarray],
    ps_deg: Callable[[np.ndarray], np.ndarray],
    *,
    spec_a: SensorSpec | None = None,
    spec_b: SensorSpec | None = None,
    seed: int = 7,
    ble: BleSpec | None = None,
    anchor_uptime_s: float = ANCHOR_UPTIME_S,
    upper_arm: Callable[[np.ndarray], Rotation] = default_upper_arm,
) -> SimulatedSession:
    rng = np.random.default_rng(seed)
    spec_a = spec_a or SensorSpec("A", device_start_s=1780.0, drift_ppm=40.0, gyro_bias=(0.01, -0.02, 0.015))
    spec_b = spec_b or SensorSpec("B", device_start_s=2410.5, drift_ppm=-25.0, gyro_bias=(-0.012, 0.008, 0.02))

    def rot_a(tau):
        return elbow_rotations(tau - anchor_uptime_s, fe_deg, ps_deg, upper_arm)[0]

    def rot_b(tau):
        return elbow_rotations(tau - anchor_uptime_s, fe_deg, ps_deg, upper_arm)[1]

    sensor_a = simulate_sensor(spec_a, rot_a, duration_s, rng, ble=ble, anchor_uptime_s=anchor_uptime_s)
    sensor_b = simulate_sensor(spec_b, rot_b, duration_s, rng, ble=ble, anchor_uptime_s=anchor_uptime_s)
    packets = pd.concat([sensor_a.packets, sensor_b.packets], ignore_index=True)
    return SimulatedSession(
        packets=packets,
        sensors={"A": sensor_a, "B": sensor_b},
        anchor_uptime_s=anchor_uptime_s,
        fe_deg=fe_deg,
        ps_deg=ps_deg,
    )
