import os
import uvicorn
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException, Depends

import firebase_admin                            # pyright: ignore[reportMissingImports]
from firebase_admin import auth, credentials     # pyright: ignore[reportMissingImports]

from elbow_rehab.service.domain.imu_reading import ImuReading
from elbow_rehab.service.configure_infrastructure import get_project_id_and_dataset_and_table, initialize_bigquery_client, initialize_firebase_admin, ensure_infrastructure_exists
from elbow_rehab.service.auth import get_user_id

app = FastAPI()

PROJECT_ID, OUTPUT_DATASET, OUTPUT_TABLE = get_project_id_and_dataset_and_table()

bq_client = initialize_bigquery_client(PROJECT_ID)
firebase_admin = initialize_firebase_admin()


def get_table_id():
    return f"{PROJECT_ID}.{OUTPUT_DATASET}.{OUTPUT_TABLE}"


@app.on_event("startup")
def startup_event():
    ensure_infrastructure_exists(bq_client, PROJECT_ID, OUTPUT_DATASET, OUTPUT_TABLE)

@app.get("/")
def home():
    return {"message": "welcome"}

@app.post('/imu/readings')
async def ingest_imu_readings(
    readings: List[ImuReading], 
    user_id: str = Depends(get_user_id)
):
    """
    Receives a list of IMU readings and loads them into BigQuery.
    """
    print(f"Receiving data from User: {user_id}")
    if not readings:
        return {"message": "No readings provided"}

    rows_to_insert = []
    current_time = datetime.now().isoformat()
    
    for reading in readings:
        row_dict = reading.model_dump() # Convert Pydantic model to dict
        row_dict['user_id'] = user_id 
        row_dict['ingestionDate'] = current_time
        row_dict['pc_time_iso'] = row_dict['pc_time_iso'].isoformat()
        rows_to_insert.append(row_dict)

    # Insert rows
    errors = bq_client.insert_rows_json(get_table_id(), rows_to_insert)

    if errors:
        print(f"Encountered errors while inserting rows: {errors}")
        raise HTTPException(status_code=500, detail=f"BigQuery Insertion Errors: {errors}")

    return {"message": f"Successfully inserted {len(rows_to_insert)} readings."}

if __name__ == "__main__":
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))