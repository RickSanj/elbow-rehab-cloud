"""_summary_

Raises:
    RuntimeError: _description_

Returns:
    _type_: _description_
"""

import os
import pathlib
import firebase_admin
import pandas as pd


from google.cloud import bigquery
from google.api_core.exceptions import NotFound  # pyright: ignore[reportMissingImports]
from elbow_rehab.service.logger import get_logger

logger = get_logger()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.error(f"Missing required env var: {name}")
        raise RuntimeError(f"Missing required env var: {name}")
    return value


PROJECT_ID = require_env("PROJECT_ID")
OUTPUT_DATASET = require_env("OUTPUT_DATASET")
OUTPUT_TABLE = require_env("OUTPUT_TABLE")


def get_table_id() -> str:
    return f"{PROJECT_ID}.{OUTPUT_DATASET}.{OUTPUT_TABLE}"


def initialize_bigquery_client(project_id: str):
    logger.info(f"Initializing BigQuery client for project: {project_id}")
    return bigquery.Client(project=project_id)


def initialize_firebase_admin():
    if not firebase_admin._apps:
        logger.info("Initializing Firebase admin")
        firebase_admin.initialize_app()
    return firebase_admin


def ensure_infrastructure_exists(
    bq_client: bigquery.Client, project_id: str, output_dataset: str, output_table: str
):
    """Checks if Dataset and Table exist, creates them if not."""
    # Create Dataset if missing
    dataset_id = f"{project_id}.{output_dataset}"
    try:
        bq_client.get_dataset(dataset_id)
    except NotFound:
        logger.info(f"Dataset {dataset_id} not found")
        # dataset = bigquery.Dataset(dataset_id)
        # dataset.location = os.environ.get("LOCATION")
        # bq_client.create_dataset(dataset, timeout=30)
        # print(f"Created dataset {dataset_id}")

    # Create Table if missing
    table_id = f"{project_id}.{output_dataset}.{output_table}"
    try:
        bq_client.get_table(table_id)
    except NotFound:
        logger.info(f"Table {table_id} not found")
        # current_directory = pathlib.Path(__file__).parent
        # schema_path = str(current_directory / "schema/imu_readings.json")
        # schema = bq_client.schema_from_json(schema_path)

        # table = bigquery.Table(table_id, schema=schema)
        # bq_client.create_table(table)
        # logger.info(f"Created table {table_id}")


# def get_session_data_frame(bq_client: bigquery.Client, project_id: str, output_dataset: str, output_table: str, user_id: str, session_time_iso: str):
#     """Gets the session data frame from BigQuery."""
#     table_id = f"{project_id}.{output_dataset}.{output_table}"
#     query = f"SELECT * FROM `{table_id}` WHERE user_id = '{user_id}' AND session_time_iso = '{session_time_iso}'"
#     query_job = bq_client.query(query)
#     return query_job.to_dataframe()
