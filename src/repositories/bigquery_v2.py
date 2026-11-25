"""BigQuery implementation of :class:`PacketStore`.

* Raw packets are appended unchanged with streaming inserts. ``row_ids`` give
  best-effort dedup of retried batches; processing always deduplicates again.
* Every query uses query parameters; table names come from configuration.
* Angles are written per session with a load job (not streaming, so the rows
  can be deleted right away): append the new run, then delete this session's
  rows from older runs. Other sessions' rows are never touched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from uuid import UUID

import pandas as pd
from google.cloud import bigquery

from src.config import Settings, get_settings
from src.infrastructure.bigquery.bigquery_client import get_bq_client
from src.infrastructure.bigquery.bigquery_operations import dataframe_to_json_rows, rows_to_dataframe
from src.models.contract_v2 import PacketBatch
from src.utils.logger import get_logger

logger = get_logger()

PACKET_COLUMNS = ["role", "seq", "device_ts_us", "phone_rx_s", "ax", "ay", "az", "gx", "gy", "gz", "ingested_at"]

ANGLES_V2_SCHEMA = [
    bigquery.SchemaField("session_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("t_s", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("fe_deg", "FLOAT64"),
    bigquery.SchemaField("ps_deg", "FLOAT64"),
    bigquery.SchemaField("valid", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("algorithm_version", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("computed_at", "TIMESTAMP", mode="REQUIRED"),
]


class PacketInsertError(RuntimeError):
    pass


def packet_row_id(session_id: UUID | str, role: str, seq: int, device_ts_us: int) -> str:
    return f"{session_id}:{role}:{seq}:{device_ts_us}"


def batch_to_rows(user_id: str, batch: PacketBatch, ingested_at: datetime) -> tuple[list[dict], list[str]]:
    session_id = str(batch.session_id)
    batch_id = str(batch.batch_id)
    ingested = ingested_at.isoformat()
    rows, row_ids = [], []
    for p in batch.packets:
        rows.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "role": p.role,
                "seq": p.seq,
                "device_ts_us": p.device_ts_us,
                "phone_rx_s": p.phone_rx_s,
                "ax": p.ax,
                "ay": p.ay,
                "az": p.az,
                "gx": p.gx,
                "gy": p.gy,
                "gz": p.gz,
                "batch_id": batch_id,
                "schema_version": batch.schema_version,
                "ingested_at": ingested,
            }
        )
        row_ids.append(packet_row_id(session_id, p.role, p.seq, p.device_ts_us))
    return rows, row_ids


class BigQueryPacketStore:
    def __init__(
        self,
        client_factory: Callable[[], bigquery.Client] = get_bq_client,
        settings: Settings | None = None,
    ):
        self._client_factory = client_factory
        self._settings = settings or get_settings()

    @property
    def raw_table(self) -> str:
        return self._settings.bq_table(self._settings.raw_packets_table)

    @property
    def angles_table(self) -> str:
        return self._settings.bq_table(self._settings.angles_v2_table)

    @staticmethod
    def _session_filter(session_id: UUID, since: datetime | None):
        params = [bigquery.ScalarQueryParameter("session_id", "STRING", str(session_id))]
        clause = "session_id = @session_id"
        if since is not None:
            # Partition pruning: no packet of a session is ingested before it started.
            params.append(bigquery.ScalarQueryParameter("since", "TIMESTAMP", since))
            clause += " AND ingested_at >= @since"
        return clause, params

    def insert_packets(self, user_id: str, batch: PacketBatch, ingested_at: datetime) -> None:
        rows, row_ids = batch_to_rows(user_id, batch, ingested_at)
        errors = self._client_factory().insert_rows_json(self.raw_table, rows, row_ids=row_ids)
        if errors:
            logger.error("BigQuery insert errors for batch %s: %s", batch.batch_id, errors[:3])
            raise PacketInsertError(f"{len(errors)} rows failed")

    def count_packets(self, session_id: UUID, since: datetime | None = None) -> dict[str, int]:
        clause, params = self._session_filter(session_id, since)
        query = f"""
            SELECT role, COUNT(*) AS n
            FROM (
              SELECT DISTINCT role, seq, device_ts_us
              FROM `{self.raw_table}`
              WHERE {clause}
            )
            GROUP BY role
        """
        job = self._client_factory().query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
        return {row["role"]: int(row["n"]) for row in job.result()}

    def load_packets(self, session_id: UUID, since: datetime | None = None) -> pd.DataFrame:
        clause, params = self._session_filter(session_id, since)
        # Dedup key includes device_ts_us: after a board reboot seq restarts at
        # 0, and those packets must be kept.
        query = f"""
            SELECT {", ".join(PACKET_COLUMNS)}
            FROM `{self.raw_table}`
            WHERE {clause}
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY session_id, role, seq, device_ts_us ORDER BY ingested_at
            ) = 1
        """
        job = self._client_factory().query(query, job_config=bigquery.QueryJobConfig(query_parameters=params))
        df = rows_to_dataframe(job.result())
        if df.empty:
            return pd.DataFrame(columns=PACKET_COLUMNS)
        return df

    def replace_angles(
        self, session_id: UUID, angles: pd.DataFrame, algorithm_version: str, computed_at: datetime
    ) -> None:
        client = self._client_factory()
        out = angles[["t_s", "fe_deg", "ps_deg", "valid"]].copy()
        out.insert(0, "session_id", str(session_id))
        out["algorithm_version"] = algorithm_version
        out["computed_at"] = computed_at.isoformat()

        job_config = bigquery.LoadJobConfig(
            schema=ANGLES_V2_SCHEMA,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        client.load_table_from_json(dataframe_to_json_rows(out), self.angles_table, job_config=job_config).result()

        client.query(
            f"DELETE FROM `{self.angles_table}` WHERE session_id = @session_id AND computed_at < @computed_at",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("session_id", "STRING", str(session_id)),
                    bigquery.ScalarQueryParameter("computed_at", "TIMESTAMP", computed_at),
                ]
            ),
        ).result()
        logger.info("Wrote %d angle rows for session %s", len(out), session_id)
