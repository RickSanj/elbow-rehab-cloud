import os
import uvicorn
from http import HTTPStatus
from fastapi import FastAPI, HTTPException, Depends
from typing import Annotated

import firebase_admin  # pyright: ignore[reportMissingImports]
from firebase_admin import auth, credentials  # pyright: ignore[reportMissingImports]

from src.analytics.session_report import compute_session_report
from src.service.big_query import get_imu_reading_df, load_calculated_angles
from src.models.imu_reading import ImuReading, Pain, ZeroPose
from src.service.configure_infrastructure import (
    initialize_bigquery_client,
    initialize_firebase_admin,
    ensure_infrastructure_exists,
    require_env,
    get_table_id,
)
from src.service.auth import get_user_id
from src.service.configure_database import (
    load_report,
    sync_firebase_users_to_db,
    update_pain_level,
    record_zero_pose_event,
    ensure_patient_exists,
)
from src.utils.logger import get_logger
from src.angle_calculation.calculations import ElbowTracker, get_sample_rate
from contextlib import asynccontextmanager

logger = get_logger()
logger.info("Service started successfully")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=== REGISTERED ROUTES ===")
    for r in app.routes:
        methods = ",".join(r.methods or [])
        print(f"{methods:10s} {r.path}")

    yield

app = FastAPI(lifespan=lifespan)

PROJECT_ID = require_env("PROJECT_ID")
OUTPUT_DATASET = require_env("OUTPUT_DATASET")
IMU_READINGS_TABLE = require_env("IMU_READINGS_TABLE")

bq_client = initialize_bigquery_client(PROJECT_ID)
firebase_admin = initialize_firebase_admin()



@app.get("/health", status_code=HTTPStatus.OK)
def health():
    return {"message": "OK"}


@app.get("/", status_code=HTTPStatus.OK)
def home():
    return {"message": "welcome"}


def get_session_report(pain_data: Pain):
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

@app.post("/imu/pain", status_code=HTTPStatus.CREATED)
def ingest_pain_data(
    pain_data: Pain,
    user_id: str = Depends(get_user_id)
):
    if not pain_data or not pain_data.timestamp or pain_data.pain_level is None :
        raise HTTPException(status_code=400, detail="No pain data provided")

    pain_data.session_id = f"{user_id}_{pain_data.session_time_iso}"
    pain_data.user_id = user_id

    report_data = get_session_report(pain_data)
    return  {"message": f"Successfully added pain logs."}


@app.post("/imu/zero-pose", status_code=HTTPStatus.CREATED)
def record_zero_pose_timestamp(
    zero_pose: ZeroPose,
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

    ensure_patient_exists(user_id)
    record_zero_pose_event(zero_pose)

    return {
        "message": "Zero pose timestamp recorded.",
        "session_id": zero_pose.session_id,
        "zero_pose_timestamp_iso": zero_pose.zero_pose_timestamp_iso,
    }


@app.post("/imu/readings", status_code=HTTPStatus.CREATED)
async def ingest_imu_readings(
    raw_readings: list[ImuReading],
    user_id: str = Depends(get_user_id),
):
    if not raw_readings:
        raise HTTPException(status_code=400, detail="No readings provided")

    rows_to_insert = []
    for reading in raw_readings:
        reading.user_id = user_id
        reading.session_id = f"{user_id}_{reading.session_time_iso}"
        # Swap z axis
        reading.az_A *= -1
        reading.gz_A *= -1
        reading.az_B *= -1
        reading.gz_B *= -1
        rows_to_insert.append(reading.model_dump(mode="json"))

    logger.info(f"Inserting {len(rows_to_insert)} readings for user {user_id}")
    errors = bq_client.insert_rows_json(get_table_id(), rows_to_insert)

    if errors:
        raise HTTPException(
            status_code=500,
            detail=f"BigQuery insertion errors: {errors}",
        )

    return {"message": f"Successfully inserted {len(rows_to_insert)} readings."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
