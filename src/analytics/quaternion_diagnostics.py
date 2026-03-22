from __future__ import annotations

from pathlib import Path

import numpy as np


def quat_conj(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    return np.array([q[0], -q[1], -q[2], -q[3]], dtype=float)


def quat_mul(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    q1 = np.asarray(q1, dtype=float)
    q2 = np.asarray(q2, dtype=float)

    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=float,
    )


def quaternion_relative_angle_deg(
    q1: np.ndarray,
    q2: np.ndarray,
) -> float:
    """Return the relative rotation angle between two quaternions in degrees."""
    q1 = np.asarray(q1, dtype=float)
    q2 = np.asarray(q2, dtype=float)

    if q1.shape != (4,) or q2.shape != (4,):
        raise ValueError("Expected quaternions shaped as (4,)")
    if not np.isfinite(q1).all() or not np.isfinite(q2).all():
        return float("nan")

    norm_q1 = np.linalg.norm(q1)
    norm_q2 = np.linalg.norm(q2)
    if norm_q1 == 0.0 or norm_q2 == 0.0:
        return float("nan")

    q1_unit = q1 / norm_q1
    q2_unit = q2 / norm_q2
    q_rel = quat_mul(quat_conj(q1_unit), q2_unit)
    return float(np.degrees(2.0 * np.arccos(np.clip(abs(q_rel[0]), -1.0, 1.0))))


def compute_quaternion_diagnostics(quaternions: np.ndarray) -> dict[str, object]:
    """Summarize quaternion stability over time for one sensor."""
    quaternions = _coerce_quaternion_array(quaternions)

    total_samples = int(len(quaternions))
    norms = np.linalg.norm(quaternions, axis=1)
    valid_mask = np.isfinite(quaternions).all(axis=1) & np.isfinite(norms) & (norms > 0.0)

    normalized = np.full_like(quaternions, np.nan)
    normalized[valid_mask] = quaternions[valid_mask] / norms[valid_mask, None]

    angle_from_reference_deg = np.full(total_samples, np.nan)
    sample_change_deg = np.full(total_samples, np.nan)

    valid_indices = np.flatnonzero(valid_mask)
    reference_index = int(valid_indices[0]) if valid_indices.size else None

    if valid_indices.size:
        reference_quaternion = normalized[reference_index]
        dots = np.sum(normalized[valid_mask] * reference_quaternion, axis=1)
        dots = np.clip(np.abs(dots), 0.0, 1.0)
        angle_from_reference_deg[valid_mask] = np.degrees(2.0 * np.arccos(dots))

    if valid_indices.size > 1:
        previous = normalized[valid_indices[:-1]]
        current = normalized[valid_indices[1:]]
        dots = np.sum(previous * current, axis=1)
        dots = np.clip(np.abs(dots), 0.0, 1.0)
        sample_change_deg[valid_indices[1:]] = np.degrees(2.0 * np.arccos(dots))

    invalid_indices = np.flatnonzero(~valid_mask)

    return {
        "total_samples": total_samples,
        "valid_samples": int(valid_mask.sum()),
        "invalid_samples": int((~valid_mask).sum()),
        "reference_index": reference_index,
        "first_invalid_index": int(invalid_indices[0]) if invalid_indices.size else None,
        "norm_min": _safe_stat(np.min, norms[valid_mask]),
        "norm_mean": _safe_stat(np.mean, norms[valid_mask]),
        "norm_max": _safe_stat(np.max, norms[valid_mask]),
        "max_abs_norm_error": _safe_stat(
            np.max,
            np.abs(norms[valid_mask] - 1.0),
        ),
        "angle_from_reference_deg": angle_from_reference_deg,
        "angle_from_reference_stats": _summarize_series(angle_from_reference_deg),
        "sample_change_deg": sample_change_deg,
        "sample_change_stats": _summarize_series(sample_change_deg),
        "max_reference_angle_index": _argmax_finite(angle_from_reference_deg),
        "max_sample_change_index": _argmax_finite(sample_change_deg),
    }


def compute_pairwise_quaternion_diagnostics(
    quaternions_a: np.ndarray,
    quaternions_b: np.ndarray,
) -> dict[str, object]:
    """Summarize the relative angle between two quaternion time series."""
    quaternions_a = _coerce_quaternion_array(quaternions_a)
    quaternions_b = _coerce_quaternion_array(quaternions_b)
    if len(quaternions_a) != len(quaternions_b):
        raise ValueError("Quaternion series must have the same number of samples")

    total_samples = int(len(quaternions_a))
    norms_a = np.linalg.norm(quaternions_a, axis=1)
    norms_b = np.linalg.norm(quaternions_b, axis=1)
    valid_mask = (
        np.isfinite(quaternions_a).all(axis=1)
        & np.isfinite(quaternions_b).all(axis=1)
        & np.isfinite(norms_a)
        & np.isfinite(norms_b)
        & (norms_a > 0.0)
        & (norms_b > 0.0)
    )

    relative_angles_deg = np.full(total_samples, np.nan)
    valid_indices = np.flatnonzero(valid_mask)
    for index in valid_indices:
        relative_angles_deg[index] = quaternion_relative_angle_deg(
            quaternions_a[index],
            quaternions_b[index],
        )

    invalid_indices = np.flatnonzero(~valid_mask)

    return {
        "total_samples": total_samples,
        "valid_samples": int(valid_mask.sum()),
        "invalid_samples": int((~valid_mask).sum()),
        "first_invalid_index": int(invalid_indices[0]) if invalid_indices.size else None,
        "relative_angle_deg": relative_angles_deg,
        "relative_angle_stats": _summarize_series(relative_angles_deg),
        "min_relative_angle_index": _argmin_finite(relative_angles_deg),
        "max_relative_angle_index": _argmax_finite(relative_angles_deg),
    }


def write_quaternion_diagnostics_report(
    output_path: Path,
    sensor_quaternions: dict[str, np.ndarray],
) -> Path:
    """Write a human-readable quaternion stability report to disk."""
    sections = [
        "Quaternion Stability Report",
        (
            "Angles are computed from unit-normalized quaternions using "
            "theta = 2 * arccos(|q_ref . q|), so q and -q represent the same orientation."
        ),
        (
            "Large drift from the first quaternion can reflect filter convergence "
            "if the initial sample is not yet settled."
        ),
    ]

    for sensor_name, quaternions in sensor_quaternions.items():
        diagnostics = compute_quaternion_diagnostics(quaternions)
        sections.append(_format_sensor_section(sensor_name, diagnostics))

    if "Sensor A" in sensor_quaternions and "Sensor B" in sensor_quaternions:
        pair_diagnostics = compute_pairwise_quaternion_diagnostics(
            sensor_quaternions["Sensor A"],
            sensor_quaternions["Sensor B"],
        )
        sections.append(
            _format_sensor_pair_section("Sensor A vs Sensor B", pair_diagnostics)
        )

    output_path = Path(output_path)
    output_path.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    return output_path


def _summarize_series(values: np.ndarray) -> dict[str, float | None]:
    finite_values = np.asarray(values, dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]
    if finite_values.size == 0:
        return {
            "min": None,
            "mean": None,
            "median": None,
            "p95": None,
            "max": None,
        }

    return {
        "min": float(np.min(finite_values)),
        "mean": float(np.mean(finite_values)),
        "median": float(np.median(finite_values)),
        "p95": float(np.percentile(finite_values, 95)),
        "max": float(np.max(finite_values)),
    }


def _safe_stat(func, values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    return float(func(values))


def _argmax_finite(values: np.ndarray) -> int | None:
    finite_indices = np.flatnonzero(np.isfinite(values))
    if finite_indices.size == 0:
        return None
    return int(finite_indices[np.argmax(values[finite_indices])])


def _argmin_finite(values: np.ndarray) -> int | None:
    finite_indices = np.flatnonzero(np.isfinite(values))
    if finite_indices.size == 0:
        return None
    return int(finite_indices[np.argmin(values[finite_indices])])


def _format_sensor_section(sensor_name: str, diagnostics: dict[str, object]) -> str:
    lines = [
        sensor_name,
        f"total samples: {diagnostics['total_samples']}",
        f"valid quaternions: {diagnostics['valid_samples']}",
        f"invalid quaternions: {diagnostics['invalid_samples']}",
        f"reference sample index: {_format_optional_int(diagnostics['reference_index'])}",
        f"first invalid sample index: {_format_optional_int(diagnostics['first_invalid_index'])}",
        "norm statistics:",
        (
            "  min / mean / max = "
            f"{_format_float(diagnostics['norm_min'])} / "
            f"{_format_float(diagnostics['norm_mean'])} / "
            f"{_format_float(diagnostics['norm_max'])}"
        ),
        f"  max |norm - 1| = {_format_float(diagnostics['max_abs_norm_error'])}",
        "angle from reference quaternion [deg]:",
        _format_series_summary(diagnostics["angle_from_reference_stats"]),
        (
            "  max at sample index = "
            f"{_format_optional_int(diagnostics['max_reference_angle_index'])}"
        ),
        "sample-to-sample quaternion change [deg]:",
        _format_series_summary(diagnostics["sample_change_stats"]),
        (
            "  max at sample index = "
            f"{_format_optional_int(diagnostics['max_sample_change_index'])}"
        ),
    ]
    return "\n".join(lines)


def _format_sensor_pair_section(
    section_name: str,
    diagnostics: dict[str, object],
) -> str:
    lines = [
        section_name,
        f"total samples: {diagnostics['total_samples']}",
        f"valid sample pairs: {diagnostics['valid_samples']}",
        f"invalid sample pairs: {diagnostics['invalid_samples']}",
        f"first invalid sample index: {_format_optional_int(diagnostics['first_invalid_index'])}",
        (
            "relative angle q_rel = conj(qA) * qB [deg]:"
        ),
        _format_series_summary_with_min(diagnostics["relative_angle_stats"]),
        (
            "  min at sample index = "
            f"{_format_optional_int(diagnostics['min_relative_angle_index'])}"
        ),
        (
            "  max at sample index = "
            f"{_format_optional_int(diagnostics['max_relative_angle_index'])}"
        ),
    ]
    return "\n".join(lines)


def _format_series_summary(stats: object) -> str:
    stats = stats if isinstance(stats, dict) else {}
    return (
        "  mean / median / p95 / max = "
        f"{_format_float(stats.get('mean'))} / "
        f"{_format_float(stats.get('median'))} / "
        f"{_format_float(stats.get('p95'))} / "
        f"{_format_float(stats.get('max'))}"
    )


def _format_series_summary_with_min(stats: object) -> str:
    stats = stats if isinstance(stats, dict) else {}
    return (
        "  min / mean / median / p95 / max = "
        f"{_format_float(stats.get('min'))} / "
        f"{_format_float(stats.get('mean'))} / "
        f"{_format_float(stats.get('median'))} / "
        f"{_format_float(stats.get('p95'))} / "
        f"{_format_float(stats.get('max'))}"
    )


def _coerce_quaternion_array(quaternions: np.ndarray) -> np.ndarray:
    quaternions = np.asarray(quaternions, dtype=float)
    if quaternions.ndim == 1 and quaternions.size == 0:
        quaternions = quaternions.reshape(0, 4)
    elif quaternions.ndim == 1 and quaternions.shape[0] == 4:
        quaternions = quaternions.reshape(1, 4)
    if quaternions.ndim != 2 or quaternions.shape[1] != 4:
        raise ValueError("Expected an array shaped as (n_samples, 4)")
    return quaternions


def _format_float(value: object) -> str:
    if value is None:
        return "n/a"
    value = float(value)
    if not np.isfinite(value):
        return "n/a"
    return f"{value:.6f}"


def _format_optional_int(value: object) -> str:
    if value is None:
        return "n/a"
    return str(int(value))
