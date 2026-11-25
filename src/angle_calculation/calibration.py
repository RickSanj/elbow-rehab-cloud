"""Zero-pose calibration helpers."""

from __future__ import annotations

import numpy as np

from .settings import DEFAULT_CALIBRATION_DURATION_FRAMES

# Accelerometer calibration (bias in m/s^2 and per-axis scale), applied as
# a_cal = (a_raw - ACC_CAL_BIAS) @ ACC_CAL_SCALE.T to both sensors.
ACC_CAL_BIAS = np.array([0.43000557, 0.71119793, -0.38784999])
ACC_CAL_SCALE = np.array(
    [
        [1.00430962, 0.0, 0.0],
        [0.0, 0.99287692, 0.0],
        [0.0, 0.0, 0.99845489],
    ]
)


def get_acc_bias(df, cols, stationary_window, g_ms2=9.81):
    """
    Estimate accelerometer bias (m/s^2) from a stationary window.

    Assumes:
    - accelerometer outputs are in m/s^2
    - sensor is stationary during the window
    - scale is already calibrated
    """

    if not isinstance(stationary_window, int):
        print("Incorrect stationary_window provided, using default")
        stationary_window = DEFAULT_CALIBRATION_DURATION_FRAMES

    calib = df.iloc[:stationary_window][cols]
    a_mean = calib.mean(axis=0)
    norm = np.linalg.norm(a_mean)

    # Stationarity / sanity check
    if not (0.8 * g_ms2 <= norm <= 1.2 * g_ms2):
        raise ValueError("Not stationary or accelerometer scale is incorrect")

    g_vec = (a_mean / norm) * g_ms2
    bias = a_mean - g_vec
    return bias


def get_gyro_bias(df, cols, stationary_window):
    if not isinstance(stationary_window, int):
        print("Incorrect stationary_window provided using default")
        stationary_window = DEFAULT_CALIBRATION_DURATION_FRAMES
    calib_data = df.iloc[:stationary_window][cols]

    bias = calib_data.mean()
    return bias


def calibrate_gyro_acc(
    df,
    window=DEFAULT_CALIBRATION_DURATION_FRAMES,
    *,
    visualize: bool = True,
):
    gyro_cols_A = ["gx_A", "gy_A", "gz_A"]
    gyro_cols_B = ["gx_B", "gy_B", "gz_B"]
    accel_cols_A = ["ax_A", "ay_A", "az_A"]
    accel_cols_B = ["ax_B", "ay_B", "az_B"]

    b = ACC_CAL_BIAS
    S = ACC_CAL_SCALE

    calibrated_df = df.copy()

    # Calibrate sensor A
    # Gyroscope
    bias_df = get_gyro_bias(df, gyro_cols_A, window)
    for col in gyro_cols_A:
        calibrated_df[col] = df[col] - bias_df[col]

    # Accelerometer
    a_raw = df[accel_cols_A].values
    a_cal = (a_raw - b) @ S.T
    calibrated_df[accel_cols_A] = a_cal
    # print("Calibrate sensor A Accelerometer")
    # bias_df = get_acc_bias(df, accel_cols_A, window)
    # print(bias_df)
    # for col in accel_cols_A:
    #     calibrated_df[col] = df[col] - bias_df[col]

    # Calibrate sensor B
    # Gyroscope
    bias_df = get_gyro_bias(df, gyro_cols_B, window)
    for col in gyro_cols_B:
        calibrated_df[col] = df[col] - bias_df[col]

    # Accelerometer
    b_raw = df[accel_cols_B].values
    b_cal = (b_raw - b) @ S.T
    calibrated_df[accel_cols_B] = b_cal

    # print("Calibrate sensor B Accelerometer")
    # bias_df = get_acc_bias(df, accel_cols_B, window)
    # print(bias_df)
    # for col in accel_cols_B:
    #     calibrated_df[col] = df[col] - bias_df[col]

    if visualize:
        from src.analytics.raw_data_plots import (
            plot_acc_calibration,
            plot_gyro_calibration,
            plot_imu_readings,
        )

        plot_imu_readings(calibrated_df)
        plot_gyro_calibration(df, calibrated_df)
        plot_acc_calibration(df, calibrated_df)
    return calibrated_df
