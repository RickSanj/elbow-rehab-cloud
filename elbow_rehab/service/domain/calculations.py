import pandas as pd
import numpy as np
from datetime import datetime
from elbow_rehab.service.filters.madgwick import MadgwickFilter
from elbow_rehab.service.analytics.elbow_estimator import AlignmentFreeElbowEstimator

def process_session_angles(session_df: pd.DataFrame, sample_rate=100.0):
    # 1. Initialize filters for both sensors and the estimator
    filter_a = MadgwickFilter(frequency=sample_rate)
    filter_b = MadgwickFilter(frequency=sample_rate)
    estimator = AlignmentFreeElbowEstimator(sample_rate_hz=sample_rate)

    flexions = []
    pronations = []

    # 2. Iterate through rows (must be sorted by timestamp)
    # Assuming session_df is sorted by esp32_ms_A or a similar index
    for _, row in session_df.iterrows():
        # Prepare inputs
        acc_a = np.array([row['ax_A'], row['ay_A'], row['az_A']])
        gyro_a = np.array([row['gx_A'], row['gy_A'], row['gz_A']])
        acc_b = np.array([row['ax_B'], row['ay_B'], row['az_B']])
        gyro_b = np.array([row['gx_B'], row['gy_B'], row['gz_B']])

        # Update Filters
        filter_a.update(acc_a, gyro_a)
        filter_b.update(acc_b, gyro_b)

        # Get Rotation Matrices
        R_A = filter_a.rotation_matrix()
        R_B = filter_b.rotation_matrix()

        # Compute Angles
        flex, pron = estimator.update(R_A, gyro_a, R_B, gyro_b)
        
        flexions.append(flex)
        pronations.append(pron)

    # 3. Add columns to the existing dataframe
    session_df['flexion_deg'] = flexions
    session_df['pronation_deg'] = pronations
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_df.to_csv(f"data/session_angles_{timestamp}.csv", index=False)

    return session_df
