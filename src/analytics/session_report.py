from src.models.data_models import ReportSchema
from pandas import DataFrame
import numpy as np
from scipy.signal import medfilt

from src.angle_calculation.calculations import prepare_final_angle_columns
from src.infrastructure.bigquery.bigquery_operations import get_imu_reading_df
from src.utils.logger import get_logger

logger = get_logger()


def get_sesion_duration(session_id):
    """Return session duration (seconds) by fetching IMU readings for a session."""
    df = get_imu_reading_df(session_id)
    duration = df["ingestion_timestamp_iso"].max() - df["session_time_iso"].min()
    return duration.total_seconds()


def compute_session_report(df: DataFrame, pain_level: float | None) -> ReportSchema:
    df = prepare_final_angle_columns(df, preserve_raw=False)
    session_id = df.iloc[0]["session_id"]
    duration = get_sesion_duration(session_id)
    max_flexion = df["flexion_deg"].max()
    max_extention = df["flexion_deg"].min()
    max_pronation = df["pronation_deg"].max()
    max_supination = df["pronation_deg"].min()
    reps_count = get_reps_count(df)

    return ReportSchema(
        session_id=session_id,
        duration=duration,
        max_flexion=max_flexion,
        max_extension=max_extention,
        max_pronation=max_pronation,
        max_supination=max_supination,
        rep_count=reps_count,
        pain_level=pain_level
    )


def moving_average(x: np.ndarray, window: int = 5):
    return np.convolve(x, np.ones(window) / window, mode="same")


def compute_velocity(theta: np.ndarray, t: np.ndarray):
    v = np.zeros_like(theta)
    dt = np.diff(t)
    dtheta = np.diff(theta)
    v[1:] = dtheta / np.maximum(dt, 1e-6)
    return v


def debounce_condition(cond_array, min_samples):
    """
    Returns boolean array where condition must hold
    for min_samples consecutive samples.
    """
    result = np.zeros_like(cond_array, dtype=bool)
    count = 0
    for i, val in enumerate(cond_array):
        if val:
            count += 1
        else:
            count = 0
        if count >= min_samples:
            result[i] = True
    return result


def get_reps_count(df: DataFrame,
                   theta_low=20,
                   theta_high=100,
                   ROM_min=30,
                   v_min=15,
                   v_stop=5,
                   t_min_rep=0.8,
                   debounce_samples=3):

    df = df.sort_values("esp32_ms_A").copy()
    t = df["esp32_ms_A"].values.astype(float) / 1000.0  # convert ms to seconds
    theta = df["flexion_deg"].values.astype(float)

    # -------------------------
    # 1️⃣ Preprocess angle
    # -------------------------
    theta = np.clip(theta, 0, 160)                 # clamp unrealistic
    theta = medfilt(theta, kernel_size=5)          # remove spikes
    theta_s = moving_average(theta, window=7)      # smooth

    # -------------------------
    # 2️⃣ Compute velocity
    # -------------------------
    v = compute_velocity(theta_s, t)
    v = moving_average(v, window=5)

    # Debounced velocity conditions
    v_up = debounce_condition(v > v_min, debounce_samples)
    v_down = debounce_condition(v < -v_min, debounce_samples)
    v_still = np.abs(v) < v_stop

    # -------------------------
    # FSM STATES
    # -------------------------
    EXTENDED = 0
    FLEXING = 1
    FLEXED = 2
    EXTENDING = 3

    state = EXTENDED
    reps = 0
    rep_data = []

    rep_start_time = None
    theta_start = None
    theta_peak = None
    up_start_time = None
    down_start_time = None

    for i in range(len(theta_s)):
        angle = theta_s[i]
        time = t[i]

        # ---------------- STATE: EXTENDED ----------------
        if state == EXTENDED:
            if angle <= theta_low and not v_up[i]:
                continue

            if v_up[i] and angle > theta_low:
                state = FLEXING
                rep_start_time = time
                theta_start = angle
                theta_peak = angle
                up_start_time = time

        # ---------------- STATE: FLEXING ----------------
        elif state == FLEXING:
            theta_peak = max(theta_peak, angle)

            if angle >= theta_high and v_still[i]:
                state = FLEXED

            elif v_down[i]:  # reversed before reaching top
                state = EXTENDING
                down_start_time = time

        # ---------------- STATE: FLEXED ----------------
        elif state == FLEXED:
            if v_down[i]:
                state = EXTENDING
                down_start_time = time

        # ---------------- STATE: EXTENDING ----------------
        elif state == EXTENDING:
            if angle <= theta_low:
                duration = time - rep_start_time
                ROM = theta_peak - theta_start

                if ROM >= ROM_min and duration >= t_min_rep:
                    reps += 1
                    rep_data.append({
                        "start_time": rep_start_time,
                        "end_time": time,
                        "duration": duration,
                        "peak_flexion": theta_peak,
                        "min_extension": theta_start,
                        "ROM": ROM,
                        "up_time": (down_start_time - up_start_time) if down_start_time else None,
                        "down_time": (time - down_start_time) if down_start_time else None,
                    })

                state = EXTENDED
                rep_start_time = None
                theta_start = None
                theta_peak = None
                up_start_time = None
                down_start_time = None

    # return {
    #     "rep_count": reps,
    #     "rep_details": rep_data
    # }
    return reps
