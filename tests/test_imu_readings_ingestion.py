import pytest
import fastapi
import requests
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from elbow_rehab.service.main import app
from elbow_rehab.service.auth import get_user_id


def fake_get_user_id():
    return "test_user"

app.dependency_overrides[get_user_id] = fake_get_user_id


client = TestClient(app)

data = {
    "esp32_ms_A": 1000,
    "esp32_ms_B": 1000,
    "ax_A": 0.0,
    "ay_A": 0.0,
    "az_A": 0.0,
    "gx_A": 0.0,
    "gy_A": 0.0,
    "gz_A": 0.0,
    "ax_B": 0.0,
    "ay_B": 0.0,
    "az_B": 0.0,
    "gx_B": 0.0,
    "gy_B": 0.0,
    "gz_B": 0.0,
}
ENDPOINT = "http://localhost:8080/imu/readings"
def test_ingest_imu_readings():
    response = requests.post(
        url=ENDPOINT,
        json=[data],
    )
    # response = client.post(
    #     "/imu/readings",
    #     json=[data],
    # )

    assert response.status_code == 200
    assert "Successfully inserted" in response.json()["message"]
