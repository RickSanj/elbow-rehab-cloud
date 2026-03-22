import pandas_gbq
from pandas import DataFrame, to_datetime
from src.angle_calculation.calculations import sort_session_samples
from src.utils.logger import get_logger
from src.service.configure_infrastructure import require_env

from logging import getLogger


logger = get_logger()
getLogger("pandas_gbq").parent = logger
getLogger("pandas_gbq").propagate = True


PROJECT_ID = require_env("PROJECT_ID")
OUTPUT_DATASET = require_env("OUTPUT_DATASET")
IMU_READINGS_TABLE = require_env("IMU_READINGS_TABLE")
CALCULATED_ANGLES_TABLE = require_env("CALCULATED_ANGLES_TABLE")

IMU_READINGS_TABLE = f"{PROJECT_ID}.{OUTPUT_DATASET}.{IMU_READINGS_TABLE}"
CALCULATED_ANGLES_TABLE = f"{PROJECT_ID}.{OUTPUT_DATASET}.{CALCULATED_ANGLES_TABLE}"


def get_angles_df(session_id: str):
    query = f"""
    SELECT * 
    FROM `{CALCULATED_ANGLES_TABLE}`
    WHERE session_id = '{session_id}'
    """

    df = pandas_gbq.read_gbq(query, project_id=PROJECT_ID)
    return df


def get_imu_reading_df(session_id: str):
    query = f"""
    SELECT * 
    FROM `{IMU_READINGS_TABLE}`
    WHERE session_id = '{session_id}'
    """

    df = pandas_gbq.read_gbq(query, project_id=PROJECT_ID)

    df["session_time_iso"] = to_datetime(df["session_time_iso"], utc=True)
    if "ingestion_timestamp_iso" in df.columns:
        df["ingestion_timestamp_iso"] = to_datetime(
            df["ingestion_timestamp_iso"], utc=True, errors="coerce"
        )
    df = sort_session_samples(df)

    return df


def load_calculated_angles(df: DataFrame):
    """Loads specific rehab metrics back to BigQuery and returns the df back"""

    angles_df = df[['session_id', 'flexion_deg', 'pronation_deg', 'esp32_ms_A']]

    pandas_gbq.to_gbq(
        angles_df,
        CALCULATED_ANGLES_TABLE,
        project_id=PROJECT_ID,
        if_exists="replace"
    )
    logger.info("Loading calculated angles")
    return angles_df
