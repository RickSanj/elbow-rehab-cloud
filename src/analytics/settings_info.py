from __future__ import annotations

from pathlib import Path


def write_settings_info_report(
    output_path: Path,
    *,
    filter_setting: str,
    filter_class: str,
    estimator_setting: str,
    estimator_class: str,
    sample_rate_hz: float,
) -> Path:
    lines = [
        "Settings Info",
        f"filter_setting: {filter_setting}",
        f"filter_class: {filter_class}",
        f"estimator_setting: {estimator_setting}",
        f"estimator_class: {estimator_class}",
        f"sample_rate_hz: {sample_rate_hz:.6f}",
    ]

    output_path = Path(output_path)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
