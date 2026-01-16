"""_summary_

Raises:
    RuntimeError: _description_

Returns:
    _type_: _description_
"""

import os
import pathlib
import firebase_admin

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


def get_project_id_and_dataset_and_table() -> tuple[str, str, str]:
    PROJECT_ID = require_env("PROJECT_ID")
    OUTPUT_DATASET = require_env("OUTPUT_DATASET")
    OUTPUT_TABLE = require_env("OUTPUT_TABLE")
    return PROJECT_ID, OUTPUT_DATASET, OUTPUT_TABLE


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
        logger.info(f"Dataset {dataset_id} not found, creating it")
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = os.environ.get("LOCATION")
        bq_client.create_dataset(dataset, timeout=30)
        print(f"Created dataset {dataset_id}")

    # Create Table if missing
    table_id = f"{project_id}.{output_dataset}.{output_table}"
    try:
        bq_client.get_table(table_id)
    except NotFound:
        logger.info(f"Table {table_id} not found, creating it")
        current_directory = pathlib.Path(__file__).parent
        schema_path = str(current_directory / "schema/imu_readings.json")
        schema = bq_client.schema_from_json(schema_path)

        table = bigquery.Table(table_id, schema=schema)
        bq_client.create_table(table)
        logger.info(f"Created table {table_id}")
