import os
from google.cloud import bigquery
from google.api_core.exceptions import NotFound  # pyright: ignore[reportMissingImports]
from src.utils.logger import get_logger
from src.utils.helpers import require_env

PROJECT_ID = require_env("PROJECT_ID")
OUTPUT_DATASET = require_env("OUTPUT_DATASET")
IMU_READINGS_TABLE = require_env("IMU_READINGS_TABLE")


logger = get_logger()
_bq_client = None

def get_bq_client():
    global _bq_client
    if _bq_client is None:
        project_id = get_table_id()
        logger.info(f"Initializing BigQuery client for project: {project_id}")
        _bq_client = bigquery.Client(project=project_id)
    return _bq_client


def get_table_id() -> str:
    return f"{PROJECT_ID}.{OUTPUT_DATASET}.{IMU_READINGS_TABLE}"


def ensure_infrastructure_exists(
    bq_client: bigquery.Client, project_id: str, output_dataset: str, output_table: str
):
    """Checks if Dataset and Table exist, creates them if not."""
    dataset_id = f"{project_id}.{output_dataset}"
    bq_client = get_bq_client()
    try:
        bq_client.get_dataset(dataset_id)
    except NotFound:
        logger.info(f"Dataset {dataset_id} not found")

    table_id = f"{project_id}.{output_dataset}.{output_table}"
    try:
        bq_client.get_table(table_id)
    except NotFound:
        logger.info(f"Table {table_id} not found")
