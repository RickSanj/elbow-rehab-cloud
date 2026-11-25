"""Cloud Tasks implementation of :class:`TaskQueue`.

The task calls ``POST /internal/v2/process/{session_id}`` on this service with
an OIDC token signed for ``TASKS_SERVICE_ACCOUNT``. The task name is derived
from the session id, so enqueueing twice for the same reason is a no-op.
"""

from __future__ import annotations

from uuid import UUID

from src.config import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger()
_client = None


def _tasks_client():
    global _client
    if _client is None:
        from google.cloud import tasks_v2

        _client = tasks_v2.CloudTasksClient()
    return _client


def processing_url(settings: Settings, session_id: UUID) -> str:
    return f"{settings.service_url.rstrip('/')}/internal/v2/process/{session_id}"


class CloudTasksQueue:
    def __init__(self, settings: Settings | None = None, client_factory=_tasks_client):
        self._settings = settings or get_settings()
        self._client_factory = client_factory

    def enqueue_processing(self, session_id: UUID, reason: str = "stop") -> None:
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import tasks_v2
        from google.protobuf import duration_pb2

        s = self._settings
        s.require("project_id", "tasks_queue", "tasks_service_account", "service_url")
        client = self._client_factory()
        parent = client.queue_path(s.project_id, s.effective_tasks_location, s.tasks_queue)
        task = tasks_v2.Task(
            name=f"{parent}/tasks/process-{session_id}-{reason}",
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=processing_url(s, session_id),
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=s.tasks_service_account,
                    audience=s.effective_tasks_audience,
                ),
            ),
            dispatch_deadline=duration_pb2.Duration(seconds=s.tasks_dispatch_deadline_s),
        )
        try:
            client.create_task(parent=parent, task=task)
            logger.info("Enqueued processing for session %s", session_id)
        except AlreadyExists:
            logger.info("Processing task for session %s already exists", session_id)
