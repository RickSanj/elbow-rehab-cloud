from http import HTTPStatus
from fastapi import APIRouter, Header, Query
from fastapi.exceptions import HTTPException

from src.utils.logger import get_logger
from src.models.auth_models import SignupSchema, LoginSchema, SignupResponse
from src.infrastructure.firebase.firebase_client import get_pyrebase_auth
from src.infrastructure.cloud_sql.cloud_sql_client import create_doctor, get_patient_id_from_token, patient_exists, create_doctor_patient_link


logger = get_logger()
router = APIRouter()


@router.post("/signup", status_code=HTTPStatus.CREATED)
async def create_account(
    user_data: SignupSchema,
    token: str | None = Query(default=None)
) -> SignupResponse:
    """Create doctor account, optionally link to existing patient."""
    email = user_data.email
    password = user_data.password

    auth = get_pyrebase_auth()

    try:
        user = auth.create_user_with_email_and_password(email=email, password=password)
        doctor_id = user['localId']
    except Exception as exc:
        logger.exception(f"Signup failed: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Could not create account. Email may already exist."
        ) from exc

    # Create doctor record
    try:
        create_doctor(doctor_id)
    except Exception as exc:
        logger.exception(f"Failed to create doctor: {exc}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to create doctor with id={doctor_id}"
        ) from exc

    logger.info(f"Doctor {doctor_id} created")

    # Link to patient if token provided
    if not token:
        return SignupResponse(
            message=f"Doctor {doctor_id} created successfully",
            doctor_id=doctor_id
        )

    warning = _link_doctor_to_patient(doctor_id, token)
    return SignupResponse(
        message=f"Doctor {doctor_id} created" + (" and linked to patient" if not warning else ""),
        doctor_id=doctor_id,
        warning=warning
    )


def _link_doctor_to_patient(doctor_id: str, token: str) -> str | None:
    """Link doctor to patient if valid token provided. Returns warning message if any."""
    patient_id = get_patient_id_from_token(token)

    if not patient_id:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Invalid or expired token")

    if not patient_exists(patient_id):
        logger.warning(f"Patient {patient_id} does not exist")
        return f"Patient {patient_id} does not exist, link was not created"

    try:
        create_doctor_patient_link(doctor_id, patient_id)
        return None
    except ValueError as e:
        logger.warning(str(e))
        return str(e)
    except Exception:
        logger.exception("Unexpected error while linking doctor to patient")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to link doctor to patient"
        )


@router.post("/login", status_code=HTTPStatus.OK)
async def create_access_token(user_data: LoginSchema):
    """
    Exchanges email/password for a Firebase ID Token via REST API.
    """
    email = user_data.email
    password = user_data.password

    auth = get_pyrebase_auth()
    try:
        user = auth.sign_in_with_email_and_password(
            email=email,
            password=password
        )

        return {
            "token": user['idToken'],
            "refreshToken": user['refreshToken'],
            "uid": user['localId']
        }
    except Exception as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Invalid email or password"
        ) from exc


# TODO validate that ping works
@router.post("/ping", status_code=HTTPStatus.OK)
async def validate_token(authorization: str = Header(...)):
    """
    Validates if the provided Firebase ID token is still active and valid.
    Expects header: Authorization: Bearer <token>
    """
    auth = get_pyrebase_auth()

    try:
        token = authorization.split(" ")[1]
    except IndexError as err:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, 
            detail="Invalid token format. Use 'Bearer <token>'"
        ) from err

    try:
        user_info = auth.get_account_info(token)

        return {
            "status": "active",
            "uid": user_info['users'][0]['localId'],
            "email": user_info['users'][0]['email']
        }
    except Exception as exc:
        logger.error(f"Token validation failed: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Token is invalid or expired"
        ) from exc
