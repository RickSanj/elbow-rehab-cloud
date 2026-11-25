"""Internal endpoint called by Cloud Tasks after a session is stopped.

Only requests with a Google-signed OIDC ID token for the configured audience,
issued to the configured Cloud Tasks service account, are accepted. Everything
else gets 403.

Response codes drive Cloud Tasks retries: 2xx ends the task, anything else is
retried with backoff (503 while packets are still being uploaded, 500 on a
processing error).
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from src.api.v2.dependencies import get_metadata_repo, get_packet_store
from src.config import get_settings
from src.jobs.process_session import process_session
from src.processing.quality import clean_json
from src.repositories.interfaces import MetadataRepository, PacketStore
from src.utils.logger import get_logger

logger = get_logger()
router = APIRouter(prefix="/internal/v2", include_in_schema=False)

_transport = None


def _google_transport():
    global _transport
    if _transport is None:
        _transport = google_requests.Request()
    return _transport


def verify_cloud_tasks_request(authorization: str | None = Header(default=None)) -> dict:
    settings = get_settings()
    forbidden = HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Forbidden")
    if not settings.tasks_service_account:
        logger.error("TASKS_SERVICE_ACCOUNT is not configured; rejecting internal request")
        raise forbidden
    if not authorization or not authorization.startswith("Bearer "):
        raise forbidden
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = id_token.verify_oauth2_token(
            token, _google_transport(), audience=settings.effective_tasks_audience
        )
    except Exception as exc:  # wrong audience, expired, bad signature, ...
        logger.warning("Rejected internal request: %s", exc)
        raise forbidden from exc
    if claims.get("email") != settings.tasks_service_account or not claims.get("email_verified"):
        logger.warning("Rejected internal request from %s", claims.get("email"))
        raise forbidden
    return claims


@router.post("/process/{session_id}")
def process(
    session_id: UUID,
    _claims: dict = Depends(verify_cloud_tasks_request),
    repo: MetadataRepository = Depends(get_metadata_repo),
    store: PacketStore = Depends(get_packet_store),
):
    outcome = process_session(session_id, repo, store)
    body = {"session_id": str(session_id), "status": outcome.status, **clean_json(outcome.detail)}
    if outcome.status == "not_ready":
        return JSONResponse(status_code=HTTPStatus.SERVICE_UNAVAILABLE, content=body)
    if outcome.status == "failed":
        return JSONResponse(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, content=body)
    # done, busy (another attempt holds the lease), not_found, active: no retry
    if outcome.status != "done":
        logger.warning("Processing task for %s ended with status %s", session_id, outcome.status)
    return JSONResponse(status_code=HTTPStatus.OK, content=body)
