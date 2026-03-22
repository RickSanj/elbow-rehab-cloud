import pytest

from src.angle_calculation.calculations import normalize_fe, normalize_ps


@pytest.mark.parametrize(
    ("raw_angle", "expected"),
    [
        (0.0, 0.0),
        (35.0, 35.0),
        (-35.0, 35.0),
        (350.0, 10.0),
        (190.0, 150.0),
    ],
)
def test_normalize_fe_maps_to_hinge_range(raw_angle, expected):
    assert normalize_fe(raw_angle) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw_angle", "expected"),
    [
        (0.0, 0.0),
        (45.0, 45.0),
        (100.0, -80.0),
        (-100.0, 80.0),
        (170.0, -10.0),
    ],
)
def test_normalize_ps_wraps_to_centered_half_turn(raw_angle, expected):
    assert normalize_ps(raw_angle) == pytest.approx(expected)
