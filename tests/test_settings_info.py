from src.analytics.settings_info import write_settings_info_report


def test_write_settings_info_report_includes_runtime_configuration(tmp_path):
    output_path = tmp_path / "settings_info.txt"

    write_settings_info_report(
        output_path,
        filter_setting="ekf",
        filter_class="ExtendedKalmanFilter",
        estimator_setting="mahony",
        estimator_class="AlignmentFreeElbowEstimator",
        sample_rate_hz=123.456789,
    )

    assert output_path.read_text(encoding="utf-8") == (
        "Settings Info\n"
        "filter_setting: ekf\n"
        "filter_class: ExtendedKalmanFilter\n"
        "estimator_setting: mahony\n"
        "estimator_class: AlignmentFreeElbowEstimator\n"
        "sample_rate_hz: 123.456789\n"
    )
