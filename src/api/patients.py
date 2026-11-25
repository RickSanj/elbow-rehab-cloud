import secrets
from fastapi import APIRouter
from src.utils.logger import get_logger


from src.infrastructure.cloud_sql.cloud_sql_client import (
    save_token,
)

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
