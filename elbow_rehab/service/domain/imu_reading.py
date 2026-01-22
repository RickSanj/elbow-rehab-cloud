from pydantic import BaseModel, model_validator
from datetime import datetime


class ImuReading(BaseModel):
    user_id: str
    session_time_iso: str
    session_id: str
    ingestion_timestamp_iso: datetime

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
    def build_derived_fields(cls, values):
        user_id = values["user_id"]
        session_time_iso = values["session_time_iso"]

        values["session_id"] = f"{user_id}_{session_time_iso}"
        values["ingestion_timestamp_iso"] = datetime.utcnow()

        return values
