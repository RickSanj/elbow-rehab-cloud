import pandas as pd
import numpy as np
from src.angle_calculation.filters.EKF import ExtendedKalmanFilter
from src.angle_calculation.filters.Mahony import MahonyFilter
from src.angle_calculation.filters.madgwick import MadgwickFilter
from src.angle_calculation.estimator import (
    AlignmentFreeElbowEstimator,
    SimpleElbowEstimator,
)
from src.angle_calculation.settings import (
    DEFAULT_SAMPLE_RATE_HZ,
    DEFAULT_ESTIMATOR,
    DEFAULT_FILTER,
)

from src.angle_calculation.calibration import calibrate_gyro_acc


def normalize_fe(angle_deg: float) -> float:
    """Fold a signed angle onto the elbow hinge range [0, 150] degrees."""
    angle_deg = angle_deg % 360.0
    if angle_deg > 180.0:
        angle_deg = 360.0 - angle_deg
    return max(0.0, min(150.0, angle_deg))
    # return angle_deg


def normalize_ps(angle_deg: float) -> float:
    """Wrap pronation/supination to the centered clinical range [-90, 90)."""
    return (angle_deg + 90.0) % 180.0 - 90.0
    # return angle_deg


def sort_session_samples(session_data: pd.DataFrame) -> pd.DataFrame:
    """Return session samples ordered by device time, then ingestion time."""
    ordered = session_data.copy()
    sort_cols: list[str] = []

    for col in ("esp32_ms_A", "esp32_ms_B"):
        if col in ordered.columns:
            ordered[col] = pd.to_numeric(ordered[col], errors="coerce")
            if ordered[col].notna().any():
                sort_cols.append(col)

    for col in ("ingestion_timestamp_iso", "session_time_iso"):
        if col in ordered.columns:
            ordered[col] = pd.to_datetime(ordered[col], utc=True, errors="coerce")
            if ordered[col].notna().any():
                sort_cols.append(col)

    if not sort_cols:
        return ordered.reset_index(drop=True)

    return ordered.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


def prepare_final_angle_columns(
    df: pd.DataFrame,
    *,
    preserve_raw: bool = True,
) -> pd.DataFrame:
    """Normalize saved angle columns for analytics while optionally keeping raw values."""
    prepared = df.copy()

    if "flexion_deg" in prepared.columns:
        if preserve_raw and "flexion_deg_raw" not in prepared.columns:
            prepared["flexion_deg_raw"] = prepared["flexion_deg"]
        prepared["flexion_deg"] = prepared["flexion_deg"].astype(float).map(normalize_fe)

    if "pronation_deg" in prepared.columns:
        if preserve_raw and "pronation_deg_raw" not in prepared.columns:
            prepared["pronation_deg_raw"] = prepared["pronation_deg"]
        prepared["pronation_deg"] = prepared["pronation_deg"].astype(float).map(normalize_ps)

    return prepared


def get_filter(filter_type: str, sample_rate: float) -> MadgwickFilter | ExtendedKalmanFilter | MahonyFilter:
    """Return an AHRS filter implementation configured for ``sample_rate`` Hz.

    Parameters
    ----------
    filter_type : str
        String key identifying the desired algorithm. Accepted values are
        ``\"madgwick\"``, ``\"ekf\"``, and ``\"mahony\"``.
    sample_rate : float
        Sensor sampling frequency in Hertz that is forwarded to the filter's
        update equations.

    Returns
    -------
    MadgwickFilter | ExtendedKalmanFilter | MahonyFilter
        Instantiated filter ready to receive accelerometer and gyroscope
        samples.
    """
    if filter_type == "madgwick":
        return MadgwickFilter(frequency=sample_rate)
    if filter_type == "ekf":
        return ExtendedKalmanFilter(frequency=sample_rate)
    if filter_type == "mahony":
        return MahonyFilter(frequency=sample_rate)
    raise ValueError(f"Unknown filter type: {filter_type!r}")


def get_estimator(
    estimator_type: str, sample_rate: float
) -> SimpleElbowEstimator | AlignmentFreeElbowEstimator:
    """Create the elbow-angle estimator that post-processes the filter outputs.

    Parameters
    ----------
    estimator_type : str
        Selector for the estimator variant. ``\"simple\"`` maintains
        the original kinematic assumptions, while any other value defaults to
        the alignment-free approach for scenarios without careful sensor
        placement.
    sample_rate : float
        Sampling frequency in Hertz that determines smoothing constants within
        the estimator implementations.

    Returns
    -------
    SimpleElbowEstimator | AlignmentFreeElbowEstimator
        Concrete estimator that exposes ``set_zero_pose`` and ``update_angles``.
    """
    estimator = estimator_type
    if estimator_type == "simple":
        estimator = SimpleElbowEstimator(sample_rate)
    else:
        estimator = AlignmentFreeElbowEstimator(sample_rate)
    return estimator

def get_sample_rate(session_data: pd.DataFrame) -> float:
    """Calculate the sampling frequency of the IMU readings in Hertz."""
    session_data = sort_session_samples(session_data)

    if "esp32_ms_A" in session_data.columns:
        time_diffs = pd.to_numeric(
            session_data["esp32_ms_A"], errors="coerce"
        ).diff()
        time_diffs = time_diffs[time_diffs > 0].dropna()
        if not time_diffs.empty:
            median_diff_ms = time_diffs.median()
            if median_diff_ms > 0:
                return 1000.0 / median_diff_ms

    for time_col in ("ingestion_timestamp_iso", "session_time_iso"):
        if time_col not in session_data.columns:
            continue
        timestamps = pd.to_datetime(session_data[time_col], utc=True, errors="coerce")
        time_diffs = timestamps.diff().dt.total_seconds()
        time_diffs = time_diffs[time_diffs > 0].dropna()
        if not time_diffs.empty:
            median_diff = time_diffs.median()
            if median_diff > 0:
                return 1.0 / median_diff

    return DEFAULT_SAMPLE_RATE_HZ

class ElbowTracker:
    def __init__(self, estimator_type=DEFAULT_ESTIMATOR, filter_type=DEFAULT_FILTER, sample_rate=DEFAULT_SAMPLE_RATE_HZ):
        self.sample_rate = sample_rate
        self.filter_type = filter_type
        self.estimator_type = estimator_type
        self.filter_a = get_filter(filter_type, self.sample_rate)
        self.filter_b = get_filter(filter_type, self.sample_rate)
        self.estimator = get_estimator(estimator_type, self.sample_rate)
        self.zero_pose_timestamp_iso = None
        self.zero_pose_set = False


    def process_session_angles(
        self,
        session_df: pd.DataFrame,
        *,
        calibrated_session_df: pd.DataFrame | None = None,
        persist: bool = True,
        visualize: bool = True,
        debug_sample_indices: set[int] | list[int] | tuple[int, ...] | None = None,
    ):
        """Compute elbow angles and orientation diagnostics for a single session.

        Parameters
        ----------
        session_df : pd.DataFrame
            Raw IMU readings to calibrate and run through the filters unless a
            pre-calibrated DataFrame is passed via ``calibrated_session_df``.
        calibrated_session_df : pd.DataFrame | None, default None
            Allows reusing pre-calibrated readings. When supplied, ``session_df``
            is left untouched and calibration plots are skipped.
        persist : bool, default True
            Save ``angles_by_session.csv`` and diagnostic text reports to the
            session-specific output directory if ``True``.
        visualize : bool, default True
            Generate calibration plots (when calibration runs) and the final
            flexion/pronation figure.
        debug_sample_indices : set[int] | list[int] | tuple[int, ...] | None, default None
            Optional 1-based sample indices whose detailed solver diagnostics
            should be written to ``angle_debug_log.txt``. ``None`` keeps the
            current behavior and logs every sample.
        """
        flexions = []
        pronations = []
        quaternions_a = []
        quaternions_b = []
        session_df = sort_session_samples(session_df)

        if calibrated_session_df is None:
            calibrated_session_df = calibrate_gyro_acc(
                session_df, visualize=visualize
            )
        else:
            calibrated_session_df = calibrated_session_df.copy()

        calibrated_session_df = sort_session_samples(calibrated_session_df)
        output_dir = None
        if persist or visualize:
            # Analytics helpers (matplotlib) are only needed for local runs.
            from src.analytics.quaternion_diagnostics import write_quaternion_diagnostics_report
            from src.analytics.raw_data_plots import get_file_path, plot_angles
            from src.analytics.settings_info import write_settings_info_report

            output_dir = get_file_path(calibrated_session_df)
        self.estimator.set_debug_log_path(
            output_dir / "angle_debug_log.txt" if output_dir is not None else None,
            sample_indices=debug_sample_indices,
        )

        for _, row in calibrated_session_df.iterrows():
            acc_a = np.array([row["ax_A"], row["ay_A"], row["az_A"]])
            gyro_a = np.array([row["gx_A"], row["gy_A"], row["gz_A"]])
            acc_b = np.array([row["ax_B"], row["ay_B"], row["az_B"]])
            gyro_b = np.array([row["gx_B"], row["gy_B"], row["gz_B"]])

            self.filter_a.update(acc_a, gyro_a)
            self.filter_b.update(acc_b, gyro_b)
            quaternions_a.append(self.filter_a.quaternion.copy())
            quaternions_b.append(self.filter_b.quaternion.copy())


            R_A = self.filter_a.rotation_matrix()
            R_B = self.filter_b.rotation_matrix()

            row_ts = pd.to_datetime(row["session_time_iso"], utc=True)
            zero_ts = pd.to_datetime(self.zero_pose_timestamp_iso, utc=True)
            if not self.zero_pose_set and pd.notna(zero_ts):
                if row_ts >= zero_ts:
                    self.estimator.set_zero_pose(R_A, R_B)
                    self.zero_pose_set = True

            flex, pron = self.estimator.update_angles(R_A, gyro_a, R_B, gyro_b)
            # flexions.append(normalize_fe(flex))
            # pronations.append(normalize_ps(pron))
            flexions.append(flex)
            pronations.append(pron)

        # smoothed_flex = ema_filter(flexions)
        # smoothed_pron = ema_filter(pronations)
        smoothed_flex = flexions
        smoothed_pron = pronations

        calibrated_session_df["flexion_deg"] = smoothed_flex
        calibrated_session_df["pronation_deg"] = smoothed_pron
        calibrated_session_df = prepare_final_angle_columns(calibrated_session_df)

        if persist or visualize:
            write_settings_info_report(
                output_dir / "settings_info.txt",
                filter_setting=self.filter_type,
                filter_class=type(self.filter_a).__name__,
                estimator_setting=self.estimator_type,
                estimator_class=type(self.estimator).__name__,
                sample_rate_hz=float(self.sample_rate),
            )

        if persist:
            path = output_dir / "angles_by_session.csv"
            calibrated_session_df.to_csv(path, index=False)
            write_quaternion_diagnostics_report(
                output_dir / "quaternion_diagnostics.txt",
                {
                    "Sensor A": np.asarray(quaternions_a, dtype=float),
                    "Sensor B": np.asarray(quaternions_b, dtype=float),
                },
            )

        if visualize:
            plot_angles(calibrated_session_df)
            # plot_orientation(calibrated_session_df)

        return calibrated_session_df
