import importlib
import textwrap
from unittest.mock import MagicMock

import pytest
from src.models.data_models import ZeroPoseSchema

REQUIRED_ENV_VARS = {
    "DB_USER": "test-user",
    "DB_PASS": "test-pass",
    "DB_NAME": "test-db",
    "PROJECT_ID": "test-project",
    "OUTPUT_DATASET": "test-dataset",
    "IMU_READINGS_TABLE": "imu-readings",
    "CALCULATED_ANGLES_TABLE": "angles",
    "LOCATION": "us-central1",
    "INSTANCE_NAME": "test-instance",
}


@pytest.fixture()
def configure_db(monkeypatch):
    for key, value in REQUIRED_ENV_VARS.items():
        monkeypatch.setenv(key, value)

    import src.infrastructure.cloud_sql.cloud_sql_client as cloud_sql_client

    return importlib.reload(cloud_sql_client)


def _build_engine_mock(connection_mock: MagicMock) -> MagicMock:
    class _ContextManager:
        def __enter__(self):
            return connection_mock

        def __exit__(self, exc_type, exc, tb):
            return False

    engine_mock = MagicMock()
    engine_mock.begin.return_value = _ContextManager()
    return engine_mock


def _build_zero_pose() -> ZeroPoseSchema:
    return ZeroPoseSchema(
        user_id="user-123",
        session_id="user-123_2026-03-10T10:00:00Z",
        session_time_iso="2026-03-10T10:00:00Z",
        zero_pose_timestamp_iso="2026-03-10T10:05:00Z",
    )


def test_record_zero_pose_event_inserts_session_metadata(monkeypatch, configure_db):
    connection_mock = MagicMock()
    engine_mock = _build_engine_mock(connection_mock)
    monkeypatch.setattr(configure_db, "get_engine", lambda: engine_mock)

    configure_db.record_zero_pose_event(_build_zero_pose())

    engine_mock.begin.assert_called_once()
    connection_mock.execute.assert_called_once()

    statement, params = connection_mock.execute.call_args[0]
    assert not connection_mock.execute.call_args.kwargs

    expected_sql = textwrap.dedent(
        """
        INSERT INTO sessions (session_id, patient_id, started_at, zero_pose_at)
        VALUES (:session_id, :patient_id, :started_at, :zero_pose_at)
        ON CONFLICT (session_id)
        DO UPDATE SET zero_pose_at = EXCLUDED.zero_pose_at
        """
    ).strip()

    assert textwrap.dedent(statement.text).strip() == expected_sql
    assert params == {
        "session_id": "user-123_2026-03-10T10:00:00Z",
        "patient_id": "user-123",
        "started_at": "2026-03-10T10:00:00Z",
        "zero_pose_at": "2026-03-10T10:05:00Z",
    }


def test_record_zero_pose_event_logs_and_reraises(monkeypatch, configure_db):
    connection_mock = MagicMock()
    connection_mock.execute.side_effect = RuntimeError("db failure")
    engine_mock = _build_engine_mock(connection_mock)
    monkeypatch.setattr(configure_db, "get_engine", lambda: engine_mock)

    logger_mock = MagicMock()
    monkeypatch.setattr(configure_db, "logger", logger_mock)

    with pytest.raises(RuntimeError, match="db failure"):
        configure_db.record_zero_pose_event(_build_zero_pose())

    engine_mock.begin.assert_called_once()
    connection_mock.execute.assert_called_once()
    logger_mock.exception.assert_called_once()
    assert "Zero pose insert failed" in logger_mock.exception.call_args[0][0]
