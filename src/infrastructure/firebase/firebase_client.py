import os
import pyrebase
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
from typing import Annotated
import firebase_admin  # pyright: ignore[reportMissingImports]
from firebase_admin import credentials
from config.firebase_config import firebaseConfig
from fastapi import Depends
from src.utils.logger import get_logger
from src.utils.helpers import require_env

logger = get_logger()
security = HTTPBearer()
_firebase_app = None
_pyrebase_app = None


def get_firebase_app():
    global _firebase_app
    if not firebase_admin._apps:
        cred_path = require_env("FIREBASE_CRED")
        logger.info("Initializing Firebase admin")
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)
    else:
        _firebase_app = firebase_admin.get_app()
    return _firebase_app

def get_pyrebase_auth():
    global _pyrebase_app
    if _pyrebase_app is None:
        logger.info("Initializing Firebase REST API")
        _pyrebase_app = pyrebase.initialize_app(firebaseConfig)
    return _pyrebase_app.auth()


async def get_firebase_user_from_token(
    res: HTTPAuthorizationCredentials = Security(security),
):
    """
    Decodes the Firebase ID Token and returns the decoded token
    """
    try:
        decoded_token = auth.verify_id_token(res.credentials)
        return decoded_token
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_user_id(user: Annotated[dict, Depends(get_firebase_user_from_token)]):
    """
    Returns the user 'uid' from the decoded token.
    """
    return user["uid"]


def sync_firebase_users_to_db():
    pass