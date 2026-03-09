import pytest
from src.service.big_query import get_imu_reading_df
from src.service.main import calculate_angles, get_session_report


def test_get_df_from_session_id():
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-01-21T19:27:03Z"
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-11T16:33:58Z" #new with ingestion time
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-15T14:29:08Z" #very long session
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-18T17:11:11Z" #session with pronation/supination and fe swapted
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-18T17:29:52Z" #session with pronation/supination and fe swapted, but also with negative
    session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-18T18:08:55Z"
    # print(get_imu_reading_df(session_id))
    # assert get_imu_reading_df(session_id) == "d"
    print(get_session_report(session_id))


# print(get_imu_reading_df("zWwE7FlIf2dix6c0SzmtphrSib23_2026-01-21T17:28:23Z"))
