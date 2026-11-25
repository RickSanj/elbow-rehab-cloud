from datetime import datetime, timedelta, timezone

import sqlalchemy
from sqlalchemy import text

from src.config import get_settings
from src.models.data_models import PainSchema, ReportSchema, ZeroPoseSchema
from src.utils.logger import get_logger

logger = get_logger()


def connect_with_connector() -> sqlalchemy.engine.Engine:
    """
    Initializes a connection pool for a Cloud SQL instance of PostgreSQL.

    Uses the Cloud SQL Python Connector package.
    """
    from google.cloud.sql.connector import Connector, IPTypes

    settings = get_settings()
    settings.require("db_user", "db_pass", "db_name", "project_id", "location", "instance_name")
    instance_connection_name = f"{settings.project_id}:{settings.location}:{settings.instance_name}"
    ip_type = IPTypes.PRIVATE if settings.private_ip else IPTypes.PUBLIC

    connector = Connector(ip_type=ip_type, refresh_strategy="LAZY")

    def getconn():
        conn = connector.connect(
            instance_connection_name,
            "pg8000",
            user=settings.db_user,
            password=settings.db_pass.get_secret_value(),
            db=settings.db_name,
        )
        return conn

    engine_ = sqlalchemy.create_engine(
        "postgresql+pg8000://",
        creator=getconn,
        pool_size=5,
        max_overflow=2,
        pool_timeout=30,
        pool_recycle=1800,
    )
    return engine_

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = connect_with_connector()
    return _engine


def create_patient(user_id: str):
    engine = get_engine()
    with engine.begin() as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO patients (patient_id)
                    VALUES (:patient_id)
                    ON CONFLICT (patient_id) DO NOTHING
                """),
                {"patient_id": user_id},
            )
        except Exception as exc:
            logger.exception("Patient insert failed: {exc}")
            raise exc

def create_doctor(user_id: str):
    engine = get_engine()
    with engine.begin() as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO doctors (doctor_id)
                    VALUES (:doctor_id)
                    ON CONFLICT (doctor_id) DO NOTHING
                """),
                {"doctor_id": user_id},
            )
        except Exception as exc:
            logger.exception("Doctor insert failed: {exc}")
            raise exc


def load_report(report_data: ReportSchema):
    """Loads specific rehab metrics to Cloud SQL."""
    logger.debug(f"Loading report {report_data.session_id} to reports table")

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO reports (session_id, duration, max_flexion, max_extension, max_pronation, max_supination, rep_count, pain_level)
                    VALUES (:session_id, :duration, :max_flexion, :max_extension, :max_pronation, :max_supination, :rep_count, :pain_level)
                """),
                report_data.model_dump()
            )
        except Exception as exc:
            logger.exception("Report insert failed: {exc}")
            raise exc
    return


def update_pain_level(pain_data: PainSchema):
    """Updates pain_level for an existing report row by session_id.
       Raises error if the row does not exist.
    """
    logger.info(f"Updating pain_level for session_id={pain_data.session_id}")
    engine = get_engine()
    with engine.begin() as conn:
        try:
            result = conn.execute(
                text("""
                    UPDATE reports
                    SET pain_level = :pain_level
                    WHERE session_id = :session_id
                """),
                {
                    "session_id": pain_data.session_id,
                    "pain_level": pain_data.pain_level,
                },
            )

            if result.rowcount == 0:
                raise ValueError(f"No report found for session_id={pain_data.session_id}")
        except Exception as exc:
            logger.exception("Pain level insert failed: {exc}")
            raise exc


def record_zero_pose_event(zero_pose: ZeroPoseSchema):
    """Persists (or updates) session metadata with zero-pose timestamp."""
    logger.info(
        "Recording zero-pose timestamp for session_id=%s at %s",
        zero_pose.session_id,
        zero_pose.zero_pose_timestamp_iso,
    )

    engine = get_engine()
    with engine.begin() as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO sessions (session_id, patient_id, started_at, zero_pose_at)
                    VALUES (:session_id, :patient_id, :started_at, :zero_pose_at)
                    ON CONFLICT (session_id)
                    DO UPDATE SET zero_pose_at = EXCLUDED.zero_pose_at
                """),
                {
                    "session_id": zero_pose.session_id,
                    "patient_id": zero_pose.user_id,
                    "started_at": zero_pose.session_time_iso,
                    "zero_pose_at": zero_pose.zero_pose_timestamp_iso,
                },
            )
        except Exception as exc:
            logger.exception("Zero pose insert failed: {exc}")
            raise exc


def patient_exists(user_id: str) -> bool:
    """Return True if patient with such user_id exists"""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1 FROM patients WHERE patient_id = :patient_id
            """),
            {"patient_id": user_id},
        )
        return result.fetchone() is not None


def doctor_exists(user_id: str) -> bool:
    """Return True if doctor with such user_id exists"""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 1 FROM doctors WHERE doctor_id = :doctor_id
            """),
            {"doctor_id": user_id},
        )
        return result.fetchone() is not None

def create_doctor_patient_link(doctor_id: str, patient_id: str):
    """Create doctor patient link. Raises ValueError if patient or doctor doesn't exist."""
    logger.info(
        "Creating doctor-patient link for doctor_id=%s and patient_id=%s",
        doctor_id,
        patient_id
    )

    engine = get_engine()

    with engine.connect() as conn:
        if not patient_exists(patient_id):
            raise ValueError(f"Patient with patient_id={patient_id} does not exist")

        if not doctor_exists(doctor_id):
            raise ValueError(f"Doctor with doctor_id={doctor_id} does not exist")

    with engine.begin() as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO doctor_patient_link (patient_id, doctor_id)
                    VALUES (:patient_id, :doctor_id)
                """),
                {
                    "patient_id": patient_id,
                    "doctor_id": doctor_id,
                },
            )
        except Exception as exc:
            logger.exception("Doctor-patient link creation failed: {exc}")
            raise exc


def save_token(token: str, patient_id: str, ttl_hours: int = 24):
    """Save invite token with expiration."""

    engine = get_engine()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO invite_tokens (token, patient_id, expires_at)
                VALUES (:token, :patient_id, :expires_at)
            """),
            {
                "token": token,
                "patient_id": patient_id,
                "expires_at": expires_at,
            },
        )

def get_patient_id_from_token(token: str) -> str | None:
    engine = get_engine()

    with engine.begin() as conn:
        result = conn.execute(
            text("""
                UPDATE invite_tokens
                SET is_used = TRUE
                WHERE token = :token
                  AND is_used = FALSE
                  AND expires_at > NOW()
                RETURNING patient_id
            """),
            {"token": token},
        ).fetchone()

        return result[0] if result else None