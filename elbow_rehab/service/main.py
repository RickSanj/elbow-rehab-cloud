import os
import pathlib
from datetime import datetime
from typing import List

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Security
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
import firebase_admin
from firebase_admin import auth, credentials
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from elbow_rehab.service.domain.imu_reading import ImuReading

app = FastAPI()

# --- Config ---
PROJECT_ID = os.environ.get('PROJECT_ID', 'rehab-project-480112')
OUTPUT_DATASET = os.environ.get('OUTPUT_DATASET', 'imu_data')
OUTPUT_TABLE = os.environ.get('OUTPUT_TABLE', 'readings')

# Initialize Client
bq_client = bigquery.Client(project=PROJECT_ID)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

security = HTTPBearer()

async def get_user_id(res: HTTPAuthorizationCredentials = Security(security)):
    """
    Decodes the Firebase ID Token and returns the 'uid'.
    """
    try:
        # Verify the token sent from the Swift app
        decoded_token = auth.verify_id_token(res.credentials)
        return decoded_token['uid'] # This is the user's unique ID
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid authentication: {str(e)}")

def get_table_id():
    return f"{PROJECT_ID}.{OUTPUT_DATASET}.{OUTPUT_TABLE}"

def ensure_infrastructure_exists():
    """Checks if Dataset and Table exist, creates them if not."""
    
    # 1. Create Dataset if missing
    dataset_id = f"{PROJECT_ID}.{OUTPUT_DATASET}"
    try:
        bq_client.get_dataset(dataset_id)
    except NotFound:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = os.environ.get('LOCATION', 'europe-central2')
        bq_client.create_dataset(dataset, timeout=30)
        print(f"Created dataset {dataset_id}")

    # 2. Create Table if missing
    table_id = get_table_id()
    try:
        bq_client.get_table(table_id)
    except NotFound:
        current_directory = pathlib.Path(__file__).parent
        schema_path = str(current_directory / "schema/imu_readings.json")
        schema = bq_client.schema_from_json(schema_path)
        
        table = bigquery.Table(table_id, schema=schema)
        bq_client.create_table(table)
        print(f"Created table {table_id}")

@app.on_event("startup")
def startup_event():
    # Verify DB setup on app start
    ensure_infrastructure_exists()

# --- NEW ENDPOINT HERE ---
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

    # Prepare rows for insertion
    rows_to_insert = []
    current_time = datetime.now().isoformat()
    
    for reading in readings:
        row_dict = reading.model_dump() # Convert Pydantic model to dict
        row_dict['user_id'] = user_id 
        row_dict['ingestionDate'] = current_time
        # Ensure timestamp is string for JSON serialization if needed
        row_dict['pc_time_iso'] = row_dict['pc_time_iso'].isoformat()
        rows_to_insert.append(row_dict)

    # Insert rows (Streaming API)
    errors = bq_client.insert_rows_json(get_table_id(), rows_to_insert)

    if errors:
        print(f"Encountered errors while inserting rows: {errors}")
        raise HTTPException(status_code=500, detail=f"BigQuery Insertion Errors: {errors}")

    return {"message": f"Successfully inserted {len(rows_to_insert)} readings."}

if __name__ == "__main__":
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))