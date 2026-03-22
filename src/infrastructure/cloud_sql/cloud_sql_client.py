import os
from src.models.data_models import ReportSchema
import sqlalchemy
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from google.cloud.sql.connector import Connector, IPTypes
import pg8000

from src.models.data_models import PainSchema, ZeroPoseSchema
from src.utils.logger import get_logger
from src.utils.helpers import require_env

logger = get_logger()


db_user = require_env("DB_USER")
db_pass = require_env("DB_PASS")
db_name = require_env("DB_NAME")

PROJECT_ID = require_env("PROJECT_ID")
LOCATION = require_env("LOCATION")
INSTANCE_NAME = require_env("INSTANCE_NAME")
instance_connection_name = f"{PROJECT_ID}:{LOCATION}:{INSTANCE_NAME}"

def connect_with_connector() -> sqlalchemy.engine.Engine:
    """
    Initializes a connection pool for a Cloud SQL instance of PostgreSQL.

    Uses the Cloud SQL Python Connector package.
    """
    ip_type = IPTypes.PRIVATE if os.environ.get("PRIVATE_IP") else IPTypes.PUBLIC

    connector = Connector(ip_type=ip_type, refresh_strategy="LAZY")

    def getconn() -> pg8000.dbapi.Connection:
        conn = connector.connect(
            instance_connection_name,
            "pg8000",
            user=db_user,
            password=db_pass,
            db=db_name,
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


def ensure_patient_exists(user_id: str):
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
        except Exception as e:
            logger.exception("Pain level insert failed: {e}")
            raise

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
        except Exception as e:
            logger.exception("Report insert failed: {e}")
            raise
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
        except Exception as e:
            logger.exception("Pain level insert failed: {e}")
            raise


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
        except Exception as e:
            logger.exception("Zero pose insert failed: {e}")
            raise
