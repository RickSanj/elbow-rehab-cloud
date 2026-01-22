import bigframes.pandas as bpd
from elbow_rehab.service.logger import get_logger
from elbow_rehab.service.configure_infrastructure import require_env

logger = get_logger()


PROJECT_ID = require_env("PROJECT_ID")
OUTPUT_DATASET = require_env("OUTPUT_DATASET")
OUTPUT_TABLE = require_env("OUTPUT_TABLE")

IMU_READINGS_TABLE = f"{PROJECT_ID}.{OUTPUT_DATASET}.{OUTPUT_TABLE}"

bpd.options.bigquery.project = PROJECT_ID
bpd.options.bigquery.ordering_mode = "partial"


def get_imu_reading_df(session_id: str):
    query = f"SELECT * FROM `{IMU_READINGS_TABLE}` WHERE session_id = '{session_id}'"

    df = bpd.read_gbq(query)
    pandas_df = df.to_pandas()
    pandas_df = pandas_df.sort_values(by="esp32_ms_A")

    return pandas_df
