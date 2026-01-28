import numpy as np
import datetime as dt
import matplotlib.pyplot as plt
from pathlib import Path

GYRO_COLS_A = ["gx_A", "gy_A", "gz_A"]
GYRO_COLS_B = ["gx_B", "gy_B", "gz_B"]
ACCEL_COLS_A = ["ax_A", "ay_A", "az_A"]
ACCEL_COLS_B = ["ax_B", "ay_B", "az_B"]

def get_file_path(df):
    session_time = df["session_time_iso"].iloc[0]
    output_dir = Path(f"data/{session_time.strftime('%Y%m%d_%H%M%S')}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def plot_imu_readings(df, title_prefix="IMU"):
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), sharex=True)
    axes = axes.ravel()

    # Accelerometer – Sensor A
    for col in ACCEL_COLS_A:
        axes[0].plot(df.index, df[col], label=col)
    axes[0].set_title(f"{title_prefix} A – Accelerometer")
    axes[0].set_ylabel("Acceleration (m/s²)")
    axes[0].legend(fontsize=8)

    # Accelerometer – Sensor B
    for col in ACCEL_COLS_B:
        axes[1].plot(df.index, df[col], label=col)
    axes[1].set_title(f"{title_prefix} B – Accelerometer")
    axes[1].set_ylabel("Acceleration (m/s²)")
    axes[1].legend(fontsize=8)

    # Gyroscope – Sensor A
    for col in GYRO_COLS_A:
        axes[2].plot(df.index, df[col], label=col)
    axes[2].set_title(f"{title_prefix} A – Gyroscope")
    axes[2].set_ylabel("Angular velocity (rad/s)")
    axes[2].legend(fontsize=8)

    # Gyroscope – Sensor B
    for col in GYRO_COLS_B:
        axes[3].plot(df.index, df[col], label=col)
    axes[3].set_title(f"{title_prefix} B – Gyroscope")
    axes[3].set_ylabel("Angular velocity (rad/s)")
    axes[3].legend(fontsize=8)

    axes[2].set_xlabel("Time")
    axes[3].set_xlabel("Time")

    plt.tight_layout()
    plt.suptitle("IMU reading over Time", fontsize=16)
    plt.savefig(f"{get_file_path(df)}/raw_imu_readings.png")
    plt.close(fig)



def plot_gyro_calibration(df_before, df_after):
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, constrained_layout=True)
    axes = axes.ravel()

    for i, col in enumerate(GYRO_COLS_A):
        ax = axes[i]
        ax.plot(df_before.index, df_before[col], label=f"{col} raw", alpha=0.6)
        ax.plot(df_after.index, df_after[col], label=f"{col} calibrated", alpha=0.8)
        ax.set_title(f"Sensor A - {col.replace('_A','').upper()} Axis")
        ax.legend(fontsize=8)
        ax.set_ylabel("Gyro (rad/s)")

    for i, col in enumerate(GYRO_COLS_B):
        ax = axes[i+3]
        ax.plot(df_before.index, df_before[col], label=f"{col} raw", alpha=0.6)
        ax.plot(df_after.index, df_after[col], label=f"{col} calibrated", alpha=0.8)
        ax.set_title(f"Sensor B - {col.replace('_B','').upper()} Axis")
        ax.legend(fontsize=8)
        ax.set_ylabel("Gyro (rad/s)")

    axes[-1].set_xlabel("Timestamp")
    plt.suptitle("Gyroscope Calibration Comparison (Raw vs Bias-Corrected)", fontsize=16)
    plt.savefig(f"{get_file_path(df_after)}/gyro_calibration.png")
    plt.close(fig)
    

def plot_angles(df):
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)

    axes[0].plot(df.index, df["flexion_deg"], label="Flexion / Extension")
    axes[0].set_title("Flexion / Extension")
    axes[0].set_ylabel("FE [deg]")
    axes[0].legend()

    axes[1].plot(df.index, df["pronation_deg"], label="Pronation / Supination")
    axes[1].set_title("Pronation / Supination")
    axes[1].set_ylabel("PS [deg]")
    axes[1].set_xlabel("Time")
    axes[1].legend()

    fig.suptitle("Elbow Angles Over Time", fontsize=16)
    plt.tight_layout()
    plt.savefig(f"{get_file_path(df)}/angles.png")
    plt.close(fig)

