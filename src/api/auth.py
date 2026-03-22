from http import HTTPStatus
import requests
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from fastapi.requests import Request

from src.utils.logger import get_logger
from src.models.auth_models import SignupSchema, LoginSchema
from src.infrastructure.firebase.firebase_client import get_firebase_app, get_pyrebase_auth
from src.infrastructure.cloud_sql.cloud_sql_client import ensure_patient_exists #


logger = get_logger()
router = APIRouter()

firebase = get_firebase_app()

@router.post("/signup", status_code=HTTPStatus.CREATED)
async def create_account(user_data: SignupSchema):
    email = user_data.email
    password = user_data.password
    patient_id = user_data.patient_id
    
    auth = get_pyrebase_auth()

    try:
        user = auth.create_user_with_email_and_password(
            email=email,
            password=password,
        )
        ensure_patient_exists(user['localId'])

        return JSONResponse(content={
            "message": f"User account created successfully for user {user['localId']}"
            },
            status_code=HTTPStatus.CREATED
        )

    except Exception as exc:
        logger.error(f"Signup failed: {str(exc)}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Could not create account. Email may already exist."
        ) from exc

    # TODO create link to patient




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
