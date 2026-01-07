import os
import pathlib
from google.cloud import bigquery
from google.api_core.exceptions import NotFound  # pyright: ignore[reportMissingImports]
import firebase_admin

def get_project_id_and_dataset_and_table() -> tuple[str, str, str]:
    PROJECT_ID = os.environ.get('PROJECT_ID', 'rehab-project-480112')
    OUTPUT_DATASET = os.environ.get('OUTPUT_DATASET', 'imu_data')
    OUTPUT_TABLE = os.environ.get('OUTPUT_TABLE', 'readings')
    return  PROJECT_ID, OUTPUT_DATASET, OUTPUT_TABLE


def initialize_bigquery_client(project_id: str):
    return bigquery.Client(project=project_id)


def initialize_firebase_admin():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firebase_admin


def ensure_infrastructure_exists(bq_client: bigquery.Client, project_id: str, output_dataset: str, output_table: str):
    """Checks if Dataset and Table exist, creates them if not."""
    # Create Dataset if missing
    dataset_id = f"{project_id}.{output_dataset}"
    try:
        bq_client.get_dataset(dataset_id)
    except NotFound:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = os.environ.get('LOCATION', 'europe-central2')
        bq_client.create_dataset(dataset, timeout=30)
        print(f"Created dataset {dataset_id}")

    # Create Table if missing
    table_id = f"{project_id}.{output_dataset}.{output_table}"
    try:
        bq_client.get_table(table_id)
    except NotFound:
        current_directory = pathlib.Path(__file__).parent
        schema_path = str(current_directory / "schema/imu_readings.json")
        schema = bq_client.schema_from_json(schema_path)
        
        table = bigquery.Table(table_id, schema=schema)
        bq_client.create_table(table)
        print(f"Created table {table_id}")
