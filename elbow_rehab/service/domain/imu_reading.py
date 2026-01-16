from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ImuReading(BaseModel):
    pc_time_iso: datetime
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
