from http import HTTPStatus
from fastapi import APIRouter, HTTPException, Depends
from src.models.data_models import ImuReadingSchema, PainSchema, ZeroPoseSchema
from src.analytics.session_report import compute_session_report
from src.utils.logger import get_logger

from src.angle_calculation.calculations import ElbowTracker, get_sample_rate

from src.infrastructure.cloud_sql.cloud_sql_client import (
    load_report,
    record_zero_pose_event,
    create_patient,
    patient_exists,
)
from src.infrastructure.bigquery.bigquery_operations import (
    get_imu_reading_df,
    load_calculated_angles,
)
from src.infrastructure.bigquery.bigquery_client import (
    get_bq_client,
    get_table_id,
)
from src.infrastructure.firebase.firebase_client import get_user_id

logger = get_logger()
router = APIRouter()


@router.get("/", status_code=HTTPStatus.OK)
def home():
    return {"message": "welcome"}

def get_session_report(pain_data: PainSchema):
    # TODO handle case when session was already generated
    logger.info(f"Generating report for session_ID: {pain_data.session_id}")

    session_data = calculate_angles(pain_data.session_id)
    if session_data.empty:
        raise HTTPException(status_code=404, detail="Session not found")

    report_data = compute_session_report(session_data, pain_data.pain_level)
    print(report_data)
    logger.info(f"Report generated for session_ID: {pain_data.session_id}, report: {report_data}")
    load_report(report_data)
    return report_data

def calculate_angles(session_id: str):
    logger.info(f"Calculating angles for session_ID: {session_id}")

    # Fetch from BigQuery
    session_data = get_imu_reading_df(session_id)

    if session_data.empty:
        raise HTTPException(status_code=404, detail="Session not found")

    elbow_tracker = ElbowTracker(sample_rate=get_sample_rate(session_data))
    processed_df = elbow_tracker.process_session_angles(session_data)
    angles_df = load_calculated_angles(processed_df)

    return angles_df

@router.post("/imu/pain", status_code=HTTPStatus.CREATED)
def ingest_pain_data(
    pain_data: PainSchema,
    user_id: str = Depends(get_user_id)
):
    if not pain_data or not pain_data.timestamp or pain_data.pain_level is None :
        raise HTTPException(status_code=400, detail="No pain data provided")

    pain_data.session_id = f"{user_id}_{pain_data.session_time_iso}"
    pain_data.user_id = user_id

    report_data = get_session_report(pain_data)
    return  {"message": f"Successfully added pain logs."}


@router.post("/imu/zero-pose", status_code=HTTPStatus.CREATED)
def record_zero_pose_timestamp(
    zero_pose: ZeroPoseSchema,
    user_id: str = Depends(get_user_id),
):
    if not zero_pose or not zero_pose.zero_pose_timestamp_iso or not zero_pose.session_time_iso:
        raise HTTPException(status_code=400, detail="No zero pose data provided")

    if zero_pose.zero_pose_timestamp_iso < zero_pose.session_time_iso:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="zero_pose_timestamp_iso cannot be earlier than session_time_iso",
        )
    zero_pose.user_id = user_id
    zero_pose.session_id = f"{user_id}_{zero_pose.session_time_iso}"

    if not patient_exists(user_id):
        create_patient(user_id)
    record_zero_pose_event(zero_pose)

    return {
        "message": "Zero pose timestamp recorded.",
        "session_id": zero_pose.session_id,
        "zero_pose_timestamp_iso": zero_pose.zero_pose_timestamp_iso,
    }


@router.post("/imu/readings", status_code=HTTPStatus.CREATED)
async def ingest_imu_readings(
    raw_readings: list[ImuReadingSchema],
    user_id: str = Depends(get_user_id),
):
    bq_client = get_bq_client()
    if not raw_readings:
        raise HTTPException(status_code=400, detail="No readings provided")

    rows_to_insert = []
    for reading in raw_readings:
        reading.user_id = user_id
        reading.session_id = f"{user_id}_{reading.session_time_iso}"
        # Swap values, because z axis is swapped
        reading.ax_A *= -1
        reading.gx_A *= -1
        reading.ax_B *= -1
        reading.gx_B *= -1

        reading.ay_A *= -1
        reading.gy_A *= -1
        reading.ay_B *= -1
        reading.gy_B *= -1
        rows_to_insert.append(reading.model_dump(mode="json"))

    logger.info(f"Inserting {len(rows_to_insert)} readings for user {user_id}")
    errors = bq_client.insert_rows_json(get_table_id(), rows_to_insert)

    if errors:
        raise HTTPException(
            status_code=500,
            detail=f"BigQuery insertion errors: {errors}",
        )

    return {"message": f"Successfully inserted {len(rows_to_insert)} readings."}
