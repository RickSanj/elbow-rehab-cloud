from google.cloud import bigquery

from src.config import get_settings
from src.utils.logger import get_logger

logger = get_logger()
_bq_client = None


def get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        settings = get_settings()
        settings.require("project_id")
        logger.info("Initializing BigQuery client for project: %s", settings.project_id)
        _bq_client = bigquery.Client(project=settings.project_id)
    return _bq_client


def get_table_id() -> str:
    """Fully qualified id of the legacy v1 paired-readings table."""
    settings = get_settings()
    settings.require("imu_readings_table")
    return settings.bq_table(settings.imu_readings_table)
