"""v2 ingestion API: sessions, raw packets, events, pain (task section 3).

Requests only validate and store. Nothing here transforms sensor values or
computes angles; processing runs asynchronously after Stop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from src.api.v2.dependencies import get_metadata_repo, get_packet_store, get_task_queue
from src.infrastructure.firebase.firebase_client import get_user_id
from src.models.contract_v2 import (
    Ack,
    Metrics,
    PacketBatch,
    PainReport,
    SessionEvent,
    SessionStart,
    SessionView,
)
from src.repositories.interfaces import MetadataRepository, PacketStore, SessionRecord, TaskQueue
from src.utils.logger import get_logger

logger = get_logger()
router = APIRouter(prefix="/imu/v2", tags=["v2"])


def load_owned_session(
    repo: MetadataRepository,
    session_id: UUID,
    user_id: str,
    *,
    missing_status: int = HTTPStatus.NOT_FOUND,
) -> SessionRecord:
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=missing_status, detail="Session not found")
    if session.patient_id != user_id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not your session")
    return session


def _check_path_matches_body(path_id: UUID, body_id: UUID) -> None:
    if path_id != body_id:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail="session_id in the body does not match the URL",
        )


@router.post("/sessions", status_code=HTTPStatus.CREATED, response_model=Ack)
def start_session(
    start: SessionStart,
    response: Response,
    user_id: str = Depends(get_user_id),
    repo: MetadataRepository = Depends(get_metadata_repo),
):
    outcome = repo.start_session(user_id, start)
    if outcome == "conflict":
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="Session id already used")
    if outcome == "exists":
        response.status_code = HTTPStatus.OK
    return Ack(session_id=start.session_id, status=outcome)


@router.post("/packets", status_code=HTTPStatus.CREATED)
def ingest_packets(
    batch: PacketBatch,
    user_id: str = Depends(get_user_id),
    repo: MetadataRepository = Depends(get_metadata_repo),
    store: PacketStore = Depends(get_packet_store),
):
    # 409 (not 404) when the session is unknown: the app retries the batch
    # once its SessionStart request went through.
    load_owned_session(repo, batch.session_id, user_id, missing_status=HTTPStatus.CONFLICT)
    try:
        store.insert_packets(user_id, batch, datetime.now(timezone.utc))
    except Exception as exc:
        logger.exception("Packet insert failed for batch %s", batch.batch_id)
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="Could not store packets, retry later"
        ) from exc
    return {"session_id": str(batch.session_id), "batch_id": str(batch.batch_id), "accepted": len(batch.packets)}


@router.post("/sessions/{session_id}/events", status_code=HTTPStatus.CREATED, response_model=Ack)
def post_event(
    session_id: UUID,
    event: SessionEvent,
    response: Response,
    user_id: str = Depends(get_user_id),
    repo: MetadataRepository = Depends(get_metadata_repo),
    queue: TaskQueue = Depends(get_task_queue),
):
    _check_path_matches_body(session_id, event.session_id)
    load_owned_session(repo, session_id, user_id)

    if event.type == "zero_pose":
        outcome = repo.add_zero_pose(session_id, event.uptime_s, event.wall_iso)
        if outcome == "not_active":
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="Session is not active")
        if outcome == "exists":
            response.status_code = HTTPStatus.OK
        return Ack(session_id=session_id, status=outcome)

    stats = {role: s.model_dump() for role, s in event.stats.items()} if event.stats else None
    outcome = repo.stop_session(session_id, event.uptime_s, event.wall_iso, stats)
    if outcome.needs_enqueue:
        try:
            queue.enqueue_processing(session_id)
            repo.mark_enqueued(session_id)
        except Exception as exc:
            logger.exception("Could not enqueue processing for session %s", session_id)
            # The app retries stop; the retry sees "stopped, not enqueued" and
            # enqueues again.
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="Could not schedule processing, retry"
            ) from exc
    if not outcome.first_stop:
        response.status_code = HTTPStatus.OK
    return Ack(session_id=session_id, status="stopped" if outcome.first_stop else "already_stopped")


@router.post("/sessions/{session_id}/pain", status_code=HTTPStatus.CREATED, response_model=Ack)
def post_pain(
    session_id: UUID,
    pain: PainReport,
    user_id: str = Depends(get_user_id),
    repo: MetadataRepository = Depends(get_metadata_repo),
):
    _check_path_matches_body(session_id, pain.session_id)
    load_owned_session(repo, session_id, user_id)
    repo.set_pain(session_id, pain.pain_level)  # never triggers processing
    return Ack(session_id=session_id, status="pain_recorded")


@router.get("/sessions/{session_id}", response_model=SessionView)
def get_session(
    session_id: UUID,
    user_id: str = Depends(get_user_id),
    repo: MetadataRepository = Depends(get_metadata_repo),
):
    session = load_owned_session(repo, session_id, user_id)
    report = repo.get_report(session_id)

    metrics = None
    if report is not None and report.computed_at is not None:
        metrics = Metrics(
            duration_s=report.duration_s,
            max_flexion=report.max_flexion,
            max_extension=report.max_extension,
            max_pronation=report.max_pronation,
            max_supination=report.max_supination,
            rep_count=report.rep_count,
            smoothness=report.smoothness,
        )
    return SessionView(
        session_id=session_id,
        status=session.status,
        pain_level=report.pain_level if report else None,
        metrics=metrics,
        quality=report.quality if report else None,
        quality_ok=report.quality_ok if report else None,
        algorithm_version=session.algorithm_version,
        processing_error=session.processing_error,
    )
