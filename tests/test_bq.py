import pytest
from src.models.data_models import PainSchema
from src.infrastructure.bigquery.bigquery_operations import get_imu_reading_df
from src.api.sessions import calculate_angles, get_session_report
from src.api.patients import generate_invite_link


def test_get_df_from_session_id():
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-01-21T19:27:03Z"
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-11T16:33:58Z" #new with ingestion time
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-15T14:29:08Z" #very long session
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-18T17:11:11Z" #session with pronation/supination and fe swapted
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-18T17:29:52Z" #session with pronation/supination and fe swapted, but also with negative
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-02-18T18:08:55Z"


    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-03-12T16:00:10Z" # zero pose
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-03-19T14:24:24.342Z" # last 
    # session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-03-19T15:49:44.129Z"
    session_id = "zWwE7FlIf2dix6c0SzmtphrSib23_2026-03-24T19:37:23.054Z"
    # patient_id = "zWwE7FlIf2dix6c0SzmtphrSib23"

    pain_data = PainSchema(
        session_id="zWwE7FlIf2dix6c0SzmtphrSib23_2026-03-12T16:00:10Z",
        pain_level=3.5,
        session_time_iso=session_id.split("_")[1],
        timestamp=session_id.split("_")[1],
        user_id="zWwE7FlIf2dix6c0SzmtphrSib23"
    )
    # print(get_imu_reading_df(session_id))
    # assert get_imu_reading_df(session_id) == "d"

    print(calculate_angles(session_id))
    # print(generate_invite_link(patient_id))

    # print(get_session_report(pain_data))


# print(get_imu_reading_df("zWwE7FlIf2dix6c0SzmtphrSib23_2026-01-21T17:28:23Z"))
