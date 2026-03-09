from pydantic import BaseModel, model_validator
from datetime import datetime

class ZeroPose(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    session_time_iso: str
    zero_pose_timestamp_iso: str

class ImuReading(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    session_time_iso: str
    ingestion_timestamp_iso: str

    esp32_ms_A: int
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

    @model_validator(mode="before")
    @classmethod
    def build_session_id(cls, values: dict) -> dict:
        user_id = values.get("user_id")
        session_time = values.get("session_time_iso")
        if user_id and session_time:
            values["session_id"] = f"{user_id}_{session_time}"
        return values

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
