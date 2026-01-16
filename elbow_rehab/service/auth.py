from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
from typing import Annotated
from fastapi import Depends
from elbow_rehab.service.logger import get_logger

logger = get_logger()

security = HTTPBearer()


async def get_firebase_user_from_token(
    res: HTTPAuthorizationCredentials = Security(security),
):
    """
    Decodes the Firebase ID Token and returns the decoded token
    """
    try:
        decoded_token = auth.verify_id_token(res.credentials)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_user_id(user: Annotated[dict, Depends(get_firebase_user_from_token)]):
    """
    Returns the user 'uid' from the decoded token.
    """
    return user["uid"]
