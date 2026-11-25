"""Regression tests for the P0 bugs fixed before v2 (task section 2.1)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

# ---------------------------------------------------------------- #1 / #2 routing


def test_api_routes_are_not_shadowed_by_static_files(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "OK"}

    # Without a token the API answers (401/403), not StaticFiles (405).
    response = client.post("/imu/readings", json=[])
    assert response.status_code in (401, 403)


def test_static_pages_are_still_served(client):
    response = client.get("/auth/login.html")
    assert response.status_code == 200
    assert "<html" in response.text.lower()


# ---------------------------------------------------------------- #3 load_report


def test_load_report_commits_and_upserts(monkeypatch):
    import src.infrastructure.cloud_sql.cloud_sql_client as sql_client
    from src.models.data_models import ReportSchema

    connection = MagicMock()
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    monkeypatch.setattr(sql_client, "get_engine", lambda: engine)

    sql_client.load_report(
        ReportSchema(
            session_id="s1",
            duration=1.0,
            max_flexion=2.0,
            max_extension=3.0,
            max_pronation=4.0,
            max_supination=5.0,
            rep_count=6,
            pain_level=None,
        )
    )

    engine.begin.assert_called_once()
    engine.connect.assert_not_called()
    statement = connection.execute.call_args[0][0].text
    assert "ON CONFLICT (session_id) DO UPDATE" in statement


# ------------------------------------------------- #4 / #6 / #11 BigQuery fixes


class RecordingBigQuery:
    def __init__(self, rows=None):
        self.queries: list[tuple[str, object]] = []
        self.loads: list[tuple[list, str, object]] = []
        self._rows = rows or []

    def query(self, sql, job_config=None):
        self.queries.append((sql, job_config))
        job = MagicMock()
        job.result.return_value = self._rows
        return job

    def load_table_from_json(self, rows, table, job_config=None):
        self.loads.append((rows, table, job_config))
        return MagicMock()


def _params(job_config):
    return {p.name: p.value for p in job_config.query_parameters}


EVIL_SESSION_ID = "u1_2026-01-01T00:00:00Z' OR '1'='1"


def test_imu_reading_query_is_parameterized(monkeypatch):
    import src.infrastructure.bigquery.bigquery_operations as ops

    fake = RecordingBigQuery()
    monkeypatch.setattr(ops, "get_bq_client", lambda: fake)

    df = ops.get_imu_reading_df(EVIL_SESSION_ID)

    assert df.empty
    sql, job_config = fake.queries[0]
    assert EVIL_SESSION_ID not in sql
    assert "@session_id" in sql
    assert _params(job_config) == {"session_id": EVIL_SESSION_ID}


def test_load_calculated_angles_replaces_only_this_session(monkeypatch):
    import src.infrastructure.bigquery.bigquery_operations as ops
    from google.cloud import bigquery

    fake = RecordingBigQuery()
    monkeypatch.setattr(ops, "get_bq_client", lambda: fake)

    df = pd.DataFrame(
        {
            "session_id": ["s1", "s1"],
            "flexion_deg": [10.0, float("nan")],
            "pronation_deg": [1.0, 2.0],
            "esp32_ms_A": [1000, 1010],
            "extra": ["ignored", "ignored"],
        }
    )
    ops.load_calculated_angles(df)

    [(sql, job_config)] = fake.queries
    assert sql.startswith("DELETE FROM")
    assert "@session_id" in sql
    assert _params(job_config) == {"session_id": "s1"}

    [(rows, table, load_config)] = fake.loads
    assert table == "test-project.test_dataset.angles"
    assert load_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert rows[1]["flexion_deg"] is None  # NaN is not valid JSON
    assert set(rows[0]) == {"session_id", "flexion_deg", "pronation_deg", "esp32_ms_A"}


def test_bigquery_client_uses_project_id(monkeypatch):
    import src.infrastructure.bigquery.bigquery_client as bq_client

    created = {}

    class FakeClient:
        def __init__(self, project):
            created["project"] = project

    monkeypatch.setattr(bq_client, "_bq_client", None)
    monkeypatch.setattr(bq_client.bigquery, "Client", FakeClient)

    bq_client.get_bq_client()

    assert created["project"] == "test-project"


# ---------------------------------------------------------------- #7 invite


@pytest.fixture
def invite_store(monkeypatch):
    import src.api.patients as patients

    saved = []
    monkeypatch.setattr(patients, "create_patient", lambda patient_id: None)
    monkeypatch.setattr(patients, "save_token", lambda token, patient_id: saved.append(patient_id))
    return saved


def test_invite_requires_authentication(client, invite_store):
    response = client.get("/patients/p1/invite-doctor")
    assert response.status_code in (401, 403)
    assert invite_store == []


def test_invite_for_another_patient_is_forbidden(client, login_as, invite_store):
    login_as("attacker")
    response = client.get("/patients/p1/invite-doctor")
    assert response.status_code == 403
    assert invite_store == []


def test_invite_for_self_returns_link(client, login_as, invite_store):
    login_as("p1")
    response = client.get("/patients/p1/invite-doctor")
    assert response.status_code == 200
    assert response.json()["invite_url"].startswith("https://test-service.example/signup?token=")
    assert invite_store == ["p1"]
