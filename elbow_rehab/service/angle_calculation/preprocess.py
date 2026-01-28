"""Minimal preprocessing placeholder for IMU samples.

The goal is to keep the public API stable while the rest of the pipeline is
being simplified. The :class:`IMUPreprocessor` merely validates the incoming
vectors and hands them straight back to the caller.
"""

import numpy as np


def preprocess(acc_m_s2, gyr_rad_s):
    acc = np.asarray(acc_m_s2, dtype=np.float64).reshape(3)
    gyr = np.asarray(gyr_rad_s, dtype=np.float64).reshape(3)
    return acc, gyr


def low_pass_filer(acc_m_s2, gyr_rad_s):
    LPF_ACC_ALPHA = 0.10
    LPF_GYRO_ALPHA = 0.01

    g_x_new = LPF_GYRO_ALPHA * gyr_rad_s[0] + (1 - LPF_GYRO_ALPHA) * gyr_rad_s[0]
    g_y_new = LPF_GYRO_ALPHA * gyr_rad_s[1] + (1 - LPF_GYRO_ALPHA) * gyr_rad_s[1]
    g_z_new = LPF_GYRO_ALPHA * gyr_rad_s[2] + (1 - LPF_GYRO_ALPHA) * gyr_rad_s[2]

    a_x_new = LPF_ACC_ALPHA * acc_m_s2[0] + (1 - LPF_ACC_ALPHA) * acc_m_s2[0]
    a_y_new = LPF_ACC_ALPHA * acc_m_s2[1] + (1 - LPF_ACC_ALPHA) * acc_m_s2[1]
    a_z_new = LPF_ACC_ALPHA * acc_m_s2[2] + (1 - LPF_ACC_ALPHA) * acc_m_s2[2]
    return
