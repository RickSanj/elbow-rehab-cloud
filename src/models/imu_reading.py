from pydantic import BaseModel, Field, model_validator
from datetime import datetime, timezone

class ZeroPose(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    session_time_iso: str
    zero_pose_timestamp_iso: str

class ImuReading(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    session_time_iso: str
    ingestion_timestamp_iso: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    esp32_ms_A: int # TODO remove esp32_ms_A and esp32_ms_B from the model and calculate session_time_iso based on the first reading's timestamp and the esp32_ms values
    esp32_ms_B: int
    ax_A: float
    ay_A: float
    az_A: float
    gx_A: float
    gy_A: float
    gz_A: float
    ax_B: float
    ay_B: float
    az_B: float
    gx_B: float
    gy_B: float
    gz_B: float


class Pain(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    session_time_iso: str
    timestamp: str
    pain_level: float


class Report(BaseModel):
    session_id: str
    duration: float
    max_flexion: float
    max_extension: float
    max_pronation: float
    max_supination: float
    rep_count: int
    pain_level: float | None = None
