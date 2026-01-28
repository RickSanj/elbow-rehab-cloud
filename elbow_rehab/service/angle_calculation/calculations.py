import pandas as pd
import numpy as np
from datetime import datetime
from elbow_rehab.service.angle_calculation.filters.madgwick import MadgwickFilter
from elbow_rehab.service.angle_calculation.estimator import (
    AlignmentFreeElbowEstimator,
    SimpleElbowEstimator,
)
from elbow_rehab.service.angle_calculation.settings import DEFAULT_SAMPLE_RATE_HZ, DEFAULT_ESTIMATOR
from elbow_rehab.service.angle_calculation.calibration import calibrate_gyro
from elbow_rehab.service.analytics.raw_data_plots import get_file_path, plot_angles


def get_filter(sample_rate) -> MadgwickFilter:
    filter = MadgwickFilter(frequency=sample_rate)
    return filter


def get_estimator(estimator_type, sample_rate) -> SimpleElbowEstimator | AlignmentFreeElbowEstimator:
    estimator = estimator_type
    if estimator_type == "simple":
        estimator = SimpleElbowEstimator(sample_rate)
    else:
        estimator = AlignmentFreeElbowEstimator(sample_rate)
    return estimator


def normalize_fe(angle_deg: float) -> float:
    return (angle_deg + 180) % 360 - 180


def normalize_ps(angle_deg: float) -> float:
    return (angle_deg + 180) % 360 - 180


def process_session_angles(
    session_df: pd.DataFrame,
    estimator_type=DEFAULT_ESTIMATOR,
    sample_rate=DEFAULT_SAMPLE_RATE_HZ,
):
    filter_a = get_filter(sample_rate)
    filter_b = get_filter(sample_rate)
    estimator = get_estimator(estimator_type, sample_rate)

    flexions = []
    pronations = []

    # Calibrate Gyroscope
    calibrated_session_df = calibrate_gyro(session_df)

    # Iterate through rows (must be sorted by timestamp)
    # Assuming session_df is sorted by esp32_ms_A or a similar index
    for _, row in calibrated_session_df.iterrows():
        acc_a = np.array([row["ax_A"], row["ay_A"], row["az_A"]])
        gyro_a = np.array([row["gx_A"], row["gy_A"], row["gz_A"]])
        acc_b = np.array([row["ax_B"], row["ay_B"], row["az_B"]])
        gyro_b = np.array([row["gx_B"], row["gy_B"], row["gz_B"]])

        filter_a.update(acc_a, gyro_a)
        filter_b.update(acc_b, gyro_b)

        R_A = filter_a.rotation_matrix()
        R_B = filter_b.rotation_matrix()

        flex, pron = estimator.update_angles(R_A, gyro_a, R_B, gyro_b)

        flexions.append(normalize_fe(flex))
        pronations.append(normalize_ps(pron))

    calibrated_session_df["flexion_deg"] = flexions
    calibrated_session_df["pronation_deg"] = pronations
    path = f"{get_file_path(calibrated_session_df)}/angles_by_session.csv"
    calibrated_session_df.to_csv(path, index=False)
    
    plot_angles(calibrated_session_df)

    return calibrated_session_df
