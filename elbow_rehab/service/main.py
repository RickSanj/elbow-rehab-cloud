import os
import uvicorn
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException, Depends

import firebase_admin  # pyright: ignore[reportMissingImports]
from firebase_admin import auth, credentials  # pyright: ignore[reportMissingImports]

from elbow_rehab.service.big_query import get_imu_reading_df
from elbow_rehab.service.domain.imu_reading import ImuReading
from elbow_rehab.service.configure_infrastructure import (
    initialize_bigquery_client,
    initialize_firebase_admin,
    ensure_infrastructure_exists,
    require_env,
    get_table_id,
)
from elbow_rehab.service.auth import get_user_id
from elbow_rehab.service.configure_database import sync_firebase_users_to_db
from elbow_rehab.service.logger import get_logger
from elbow_rehab.service.angle_calculation.calculations import process_session_angles
from contextlib import asynccontextmanager

logger = get_logger()
logger.info("Service started successfully")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    ensure_infrastructure_exists(bq_client, PROJECT_ID, OUTPUT_DATASET, OUTPUT_TABLE)
    sync_firebase_users_to_db()
    yield
    # Shutdown logic (if any) can go here


app = FastAPI(lifespan=lifespan)

PROJECT_ID = require_env("PROJECT_ID")
OUTPUT_DATASET = require_env("OUTPUT_DATASET")
OUTPUT_TABLE = require_env("OUTPUT_TABLE")

bq_client = initialize_bigquery_client(PROJECT_ID)
firebase_admin = initialize_firebase_admin()


# @app.on_event("startup")
# def startup_event():
#     ensure_infrastructure_exists(bq_client, PROJECT_ID, OUTPUT_DATASET, OUTPUT_TABLE)
#     sync_firebase_users_to_db()


@app.get("/health")
def health():
    return 200


@app.get("/")
def home():
    return {"message": "welcome"}


@app.get("/calculate_angles/")
def calculate_angles(session_id: str):
    logger.info(f"Calculating angles for session_ID: {session_id}")

    # Fetch from BigQuery
    session_data = get_imu_reading_df(session_id)  # Returns a pandas DF

    if session_data.empty:
        raise HTTPException(status_code=404, detail="Session not found")

    processed_df = process_session_angles(session_data)

    return {"message": processed_df.to_dict(orient="records")}


@app.post("/imu/readings")
async def ingest_imu_readings(
    raw_readings: list[dict],
    user_id: str = Depends(get_user_id),
):
    if not raw_readings:
        raise HTTPException(status_code=400, detail="No readings provided")

    rows_to_insert = []
    for item in raw_readings:
        item["user_id"] = user_id
        try:
            reading = ImuReading(**item)
            rows_to_insert.append(reading.model_dump(mode="json"))
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Validation error: {str(e)}")

    logger.info(f"Readings: {rows_to_insert[0]}")
    errors = bq_client.insert_rows_json(get_table_id(), rows_to_insert)

    if errors:
        raise HTTPException(
            status_code=500,
            detail=f"BigQuery insertion errors: {errors}",
        )

    return {"message": f"Successfully inserted {len(rows_to_insert)} readings."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
