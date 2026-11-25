"""Legacy (v1) BigQuery reads/writes.

All queries use query parameters; table names come from configuration only.
Angles are written per session (delete this session's rows, then append), so
processing one session never touches another session's rows.
"""

import math

import pandas as pd
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src.angle_calculation.calculations import sort_session_samples
from src.config import get_settings
from src.infrastructure.bigquery.bigquery_client import get_bq_client
from src.utils.logger import get_logger

logger = get_logger()

V1_ANGLES_SCHEMA = [
    bigquery.SchemaField("session_id", "STRING"),
    bigquery.SchemaField("flexion_deg", "FLOAT64"),
    bigquery.SchemaField("pronation_deg", "FLOAT64"),
    bigquery.SchemaField("esp32_ms_A", "INT64"),
]


def _readings_table() -> str:
    settings = get_settings()
    settings.require("imu_readings_table")
    return settings.bq_table(settings.imu_readings_table)


def _angles_table() -> str:
    settings = get_settings()
    settings.require("calculated_angles_table")
    return settings.bq_table(settings.calculated_angles_table)


def session_param(session_id: str) -> bigquery.QueryJobConfig:
    return bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("session_id", "STRING", session_id)]
    )


def rows_to_dataframe(rows) -> pd.DataFrame:
    """Convert a BigQuery row iterator to a DataFrame without pyarrow.

    Rows are collected as tuples (not one dict per row) to keep memory low
    for long sessions.
    """
    columns = None
    records = []
    for row in rows:
        if columns is None:
            columns = list(row.keys())
        records.append(tuple(row.values()))
    if columns is None:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records, columns=columns)


def get_angles_df(session_id: str) -> pd.DataFrame:
    query = f"SELECT * FROM `{_angles_table()}` WHERE session_id = @session_id"
    job = get_bq_client().query(query, job_config=session_param(session_id))
    return rows_to_dataframe(job.result())


def get_imu_reading_df(session_id: str) -> pd.DataFrame:
    query = f"SELECT * FROM `{_readings_table()}` WHERE session_id = @session_id"
    job = get_bq_client().query(query, job_config=session_param(session_id))
    df = rows_to_dataframe(job.result())
    if df.empty:
        return df

    df["session_time_iso"] = pd.to_datetime(df["session_time_iso"], utc=True)
    if "ingestion_timestamp_iso" in df.columns:
        df["ingestion_timestamp_iso"] = pd.to_datetime(
            df["ingestion_timestamp_iso"], utc=True, errors="coerce"
        )
    return sort_session_samples(df)


def _json_value(value):
    if value is None:
        return None
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def dataframe_to_json_rows(df: pd.DataFrame) -> list[dict]:
    return [
        {key: _json_value(value) for key, value in record.items()}
        for record in df.to_dict(orient="records")
    ]


def load_calculated_angles(df: pd.DataFrame) -> pd.DataFrame:
    """Replace the angles of the session(s) in ``df`` and return the written rows."""
    angles_df = df[["session_id", "flexion_deg", "pronation_deg", "esp32_ms_A"]]
    table = _angles_table()
    client = get_bq_client()

    for session_id in angles_df["session_id"].dropna().unique():
        try:
            client.query(
                f"DELETE FROM `{table}` WHERE session_id = @session_id",
                job_config=session_param(str(session_id)),
            ).result()
        except NotFound:
            logger.info("Angles table %s does not exist yet; it will be created", table)

    job_config = bigquery.LoadJobConfig(
        schema=V1_ANGLES_SCHEMA,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    client.load_table_from_json(
        dataframe_to_json_rows(angles_df), table, job_config=job_config
    ).result()
    logger.info("Loaded %d calculated angle rows", len(angles_df))
    return angles_df
