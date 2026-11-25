"""Shared pytest fixtures.

Tests never talk to GCP. The autouse fixtures below

* replace every GCP-related environment variable with dummy values, and
* make the real BigQuery / Cloud SQL / Firebase / Cloud Tasks clients raise if
  anything tries to construct them,

so a test that accidentally reaches a real backend fails instead of touching
production data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402

_GCP_ENV_VARS = (
    "PROJECT_ID",
    "OUTPUT_DATASET",
    "IMU_READINGS_TABLE",
    "CALCULATED_ANGLES_TABLE",
    "RAW_PACKETS_TABLE",
    "ANGLES_V2_TABLE",
    "DB_USER",
    "DB_PASS",
    "DB_NAME",
    "INSTANCE_NAME",
    "PRIVATE_IP",
    "FIREBASE_CRED",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "SERVICE_URL",
    "TASKS_QUEUE",
    "TASKS_LOCATION",
    "TASKS_SERVICE_ACCOUNT",
    "TASKS_AUDIENCE",
    "GIT_SHA",
    "ALGORITHM_VERSION",
)

TEST_SERVICE_URL = "https://test-service.example"
TEST_TASKS_SA = "tasks-invoker@test-project.iam.gserviceaccount.com"


class NetworkDisabled(RuntimeError):
    pass


def _forbidden(*_args, **_kwargs):
    raise NetworkDisabled("Real GCP clients are disabled in unit tests; use the fakes.")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for name in _GCP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROJECT_ID", "test-project")
    monkeypatch.setenv("OUTPUT_DATASET", "test_dataset")
    monkeypatch.setenv("IMU_READINGS_TABLE", "imu_readings")
    monkeypatch.setenv("CALCULATED_ANGLES_TABLE", "angles")
    monkeypatch.setenv("SERVICE_URL", TEST_SERVICE_URL)
    monkeypatch.setenv("TASKS_SERVICE_ACCOUNT", TEST_TASKS_SA)
    monkeypatch.setenv("ALGORITHM_VERSION", "test-algo")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_real_gcp_clients(monkeypatch):
    from google.cloud import bigquery
    from google.cloud.sql import connector

    monkeypatch.setattr(bigquery.Client, "__init__", _forbidden)
    monkeypatch.setattr(connector.Connector, "__init__", _forbidden)

    import firebase_admin
    from firebase_admin import auth as firebase_auth

    monkeypatch.setattr(firebase_admin, "initialize_app", _forbidden)
    monkeypatch.setattr(firebase_auth, "verify_id_token", _forbidden)

    try:
        from google.cloud import tasks_v2
    except ImportError:  # pragma: no cover - optional until the trigger step
        tasks_v2 = None
    if tasks_v2 is not None:
        monkeypatch.setattr(tasks_v2.CloudTasksClient, "__init__", _forbidden)


@pytest.fixture
def app():
    from src.main import app as fastapi_app

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def login_as(app):
    """Override Firebase auth so requests run as the given user id."""
    from src.infrastructure.firebase.firebase_client import get_user_id

    def _login(user_id: str | None):
        if user_id is None:
            app.dependency_overrides.pop(get_user_id, None)
        else:
            app.dependency_overrides[get_user_id] = lambda: user_id

    return _login


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
