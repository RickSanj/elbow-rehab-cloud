from pandas import DataFrame, to_datetime
from src.angle_calculation.calculations import sort_session_samples
from src.config import get_settings
from src.utils.logger import get_logger


logger = get_logger()


def _tables():
    settings = get_settings()
    settings.require("imu_readings_table", "calculated_angles_table")
    return (
        settings.project_id,
        settings.bq_table(settings.imu_readings_table),
        settings.bq_table(settings.calculated_angles_table),
    )


def get_angles_df(session_id: str):
    import pandas_gbq

    PROJECT_ID, _, CALCULATED_ANGLES_TABLE = _tables()
    query = f"""
    SELECT * 
    FROM `{CALCULATED_ANGLES_TABLE}`
    WHERE session_id = '{session_id}'
    """

    df = pandas_gbq.read_gbq(query, project_id=PROJECT_ID)
    return df


def get_imu_reading_df(session_id: str):
    import pandas_gbq

    PROJECT_ID, IMU_READINGS_TABLE, _ = _tables()
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

    import pandas_gbq

    PROJECT_ID, _, CALCULATED_ANGLES_TABLE = _tables()
    angles_df = df[['session_id', 'flexion_deg', 'pronation_deg', 'esp32_ms_A']]

    pandas_gbq.to_gbq(
        angles_df,
        CALCULATED_ANGLES_TABLE,
        project_id=PROJECT_ID,
        if_exists="replace"
    )
    logger.info("Loading calculated angles")
    return angles_df
