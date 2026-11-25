from http import HTTPStatus
import secrets
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
    save_token,
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

URL = "https://elbow-rehab-service-1086744305186.europe-central2.run.app"

logger = get_logger()
router = APIRouter()



def generate_invite_token():
    return secrets.token_urlsafe(32)


@router.get("/patients/{patient_id}/invite-doctor")
def generate_invite_link(patient_id: str):
    token = generate_invite_token()

    save_token(token, patient_id)

    return {
        "invite_url": f"{URL}/signup?token={token}"
    }
