from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

security = HTTPBearer()

async def get_user_id(res: HTTPAuthorizationCredentials = Security(security)):
    """
    Decodes the Firebase ID Token and returns the user 'uid'.
    """
    try:
        decoded_token = auth.verify_id_token(res.credentials)
        return decoded_token['uid']
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid authentication: {str(e)}")
