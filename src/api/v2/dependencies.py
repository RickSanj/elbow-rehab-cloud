"""FastAPI dependency providers for the v2 API.

Tests replace these with in-memory fakes through ``app.dependency_overrides``.
"""

from __future__ import annotations

from src.config import get_settings
from src.repositories.interfaces import MetadataRepository, PacketStore, TaskQueue


def get_metadata_repo() -> MetadataRepository:
    from src.infrastructure.cloud_sql.cloud_sql_client import get_engine
    from src.repositories.cloud_sql_v2 import CloudSqlMetadataRepository

    return CloudSqlMetadataRepository(get_engine())


def get_packet_store() -> PacketStore:
    from src.repositories.bigquery_v2 import BigQueryPacketStore

    return BigQueryPacketStore(settings=get_settings())


def get_task_queue() -> TaskQueue:
    from src.repositories.tasks import CloudTasksQueue

    return CloudTasksQueue(get_settings())
