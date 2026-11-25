"""BigQueryPacketStore against a recording fake client (no network)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest
from google.cloud import bigquery

from src.models.contract_v2 import PacketBatch
from src.repositories.bigquery_v2 import BigQueryPacketStore, PacketInsertError


class FakeBigQuery:
    def __init__(self, rows=None, insert_errors=None):
        self.calls = []
        self.rows = rows or []
        self.insert_errors = insert_errors or []

    def insert_rows_json(self, table, rows, row_ids=None):
        self.calls.append(("insert", table, rows, row_ids))
        return self.insert_errors

    def query(self, sql, job_config=None):
        self.calls.append(("query", sql, job_config))
        job = MagicMock()
        job.result.return_value = self.rows
        return job

    def load_table_from_json(self, rows, table, job_config=None):
        self.calls.append(("load", table, rows, job_config))
        return MagicMock()


def params(job_config):
    return {p.name: p.value for p in job_config.query_parameters}


def make_batch(session_id):
    packet = {"role": "B", "seq": 4294967295, "device_ts_us": 1780475045, "phone_rx_s": 5231.02,
              "ax": 0.1, "ay": -0.2, "az": -9.8, "gx": 0.01, "gy": 0.02, "gz": -0.03}
    return PacketBatch.model_validate(
        {"schema_version": 2, "session_id": str(session_id), "batch_id": str(uuid.uuid4()), "packets": [packet]}
    )


@pytest.fixture
def store_and_fake(isolated_settings):
    fake = FakeBigQuery()
    return BigQueryPacketStore(client_factory=lambda: fake, settings=isolated_settings), fake


def test_insert_packets_raw_with_row_ids(store_and_fake):
    store, fake = store_and_fake
    sid = uuid.UUID("E621E1F8-C36C-495A-93FC-0C247A3E6E5F")  # iOS sends upper case
    ingested = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)

    store.insert_packets("patient-1", make_batch(sid), ingested)

    [(_, table, rows, row_ids)] = fake.calls
    assert table == "test-project.test_dataset.raw_imu_packets"
    row = rows[0]
    assert row["session_id"] == "e621e1f8-c36c-495a-93fc-0c247a3e6e5f"
    assert row["user_id"] == "patient-1"
    assert (row["ay"], row["gx"]) == (-0.2, 0.01)  # unchanged
    assert row["seq"] == 4294967295
    assert row["schema_version"] == 2
    assert row["ingested_at"] == ingested.isoformat()
    assert row_ids == ["e621e1f8-c36c-495a-93fc-0c247a3e6e5f:B:4294967295:1780475045"]


def test_insert_errors_raise(isolated_settings):
    fake = FakeBigQuery(insert_errors=[{"index": 0, "errors": ["bad"]}])
    store = BigQueryPacketStore(client_factory=lambda: fake, settings=isolated_settings)
    with pytest.raises(PacketInsertError):
        store.insert_packets("u", make_batch(uuid.uuid4()), datetime.now(timezone.utc))


def test_load_packets_dedups_in_sql_and_is_parameterized(store_and_fake):
    store, fake = store_and_fake
    sid = uuid.uuid4()
    since = datetime(2026, 10, 15, tzinfo=timezone.utc)

    df = store.load_packets(sid, since)

    assert df.empty and "device_ts_us" in df.columns
    [(_, sql, job_config)] = fake.calls
    assert "QUALIFY ROW_NUMBER() OVER" in sql
    assert "PARTITION BY session_id, role, seq, device_ts_us ORDER BY ingested_at" in sql
    assert str(sid) not in sql
    assert params(job_config) == {"session_id": str(sid), "since": since}


def test_count_packets_uses_same_dedup_key(store_and_fake):
    store, fake = store_and_fake
    fake.rows = [{"role": "A", "n": 10}, {"role": "B", "n": 9}]
    assert store.count_packets(uuid.uuid4()) == {"A": 10, "B": 9}
    sql = fake.calls[0][1]
    assert "SELECT DISTINCT role, seq, device_ts_us" in sql


def test_replace_angles_appends_then_deletes_only_older_rows_of_this_session(store_and_fake):
    store, fake = store_and_fake
    sid = uuid.uuid4()
    computed_at = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)
    angles = pd.DataFrame({"t_s": [0.0, 0.01], "fe_deg": [1.0, float("nan")], "ps_deg": [2.0, None], "valid": [True, False]})

    store.replace_angles(sid, angles, "v-test", computed_at)

    load, delete = fake.calls
    assert load[0] == "load" and load[1] == "test-project.test_dataset.angles_v2"
    rows, config = load[2], load[3]
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert rows[0] == {
        "session_id": str(sid), "t_s": 0.0, "fe_deg": 1.0, "ps_deg": 2.0, "valid": True,
        "algorithm_version": "v-test", "computed_at": computed_at.isoformat(),
    }
    assert rows[1]["fe_deg"] is None and rows[1]["valid"] is False

    assert delete[0] == "query"
    assert delete[1].startswith("DELETE FROM `test-project.test_dataset.angles_v2`")
    assert "session_id = @session_id AND computed_at < @computed_at" in delete[1]
    assert params(delete[2]) == {"session_id": str(sid), "computed_at": computed_at}
