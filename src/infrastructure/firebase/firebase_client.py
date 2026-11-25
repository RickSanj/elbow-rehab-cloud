from typing import Annotated

import firebase_admin  # pyright: ignore[reportMissingImports]
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials

from src.config import get_settings
from src.utils.logger import get_logger

logger = get_logger()
security = HTTPBearer()
_pyrebase_app = None


def get_firebase_app():
    """Return the Firebase Admin app, initializing it on first use.

    On Cloud Run no key file is needed: the service account of the revision is
    used through Application Default Credentials. For local development set
    GOOGLE_APPLICATION_CREDENTIALS (or FIREBASE_CRED) to a key file path.
    """
    if firebase_admin._apps:
        return firebase_admin.get_app()

    settings = get_settings()
    logger.info("Initializing Firebase admin")
    if settings.firebase_cred:
        return firebase_admin.initialize_app(credentials.Certificate(settings.firebase_cred))
    options = {"projectId": settings.project_id} if settings.project_id else None
    return firebase_admin.initialize_app(options=options)


def get_pyrebase_auth():
    global _pyrebase_app
    if _pyrebase_app is None:
        import pyrebase

        from config.firebase_config import firebaseConfig

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
        get_firebase_app()
        decoded_token = auth.verify_id_token(res.credentials)
        return decoded_token
    except Exception as exc:
        logger.info("Rejected Firebase token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_user_id(user: Annotated[dict, Depends(get_firebase_user_from_token)]) -> str:
    """
    Returns the user 'uid' from the decoded token.
    """
    return user["uid"]
