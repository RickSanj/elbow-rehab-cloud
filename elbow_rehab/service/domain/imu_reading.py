from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ImuReading(BaseModel):
    pc_time_iso: datetime
    esp32_ms_A: int
    ax_A: float
    ay_A: float
    az_A: float
    gx_A: float
    gy_A: float
    gz_A: float
    esp32_ms_B: int
    ax_B: float
    ay_B: float
    az_B: float
    gx_B: float
    gy_B: float
    gz_B: float
    
    # Optional: Field alias if your JSON keys differ slightly, 
    # but based on your example they match the class attributes.