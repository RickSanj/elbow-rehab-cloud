import pytest
from elbow_rehab.service.big_query import get_imu_reading_df
from elbow_rehab.service.main import calculate_angles


def test_get_df_from_session_id():
    session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-01-21T19:27:03Z"
    # print(get_imu_reading_df(session_id))
    # assert get_imu_reading_df(session_id) == "d"
    print(calculate_angles(session_id))


# print(get_imu_reading_df("zWwE7FlIf2dix6c0SzmtphrSib23_2026-01-21T17:28:23Z"))
