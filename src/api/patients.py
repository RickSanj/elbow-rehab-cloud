import secrets
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException

from src.config import get_settings
from src.infrastructure.cloud_sql.cloud_sql_client import create_patient, save_token
from src.infrastructure.firebase.firebase_client import get_user_id
from src.utils.logger import get_logger

logger = get_logger()
router = APIRouter()


def generate_invite_token():
    return secrets.token_urlsafe(32)


@router.get("/patients/{patient_id}/invite-doctor")
def generate_invite_link(patient_id: str, user_id: str = Depends(get_user_id)):
    # Only the patient themself may invite a doctor to their data.
    if user_id != patient_id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not allowed for this patient")

    create_patient(patient_id)
    token = generate_invite_token()
    save_token(token, patient_id)

    return {"invite_url": f"{get_settings().service_url}/signup?token={token}"}
