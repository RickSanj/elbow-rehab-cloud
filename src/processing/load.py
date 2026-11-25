"""Raw packet loading helpers: deduplication and per-role split."""

from __future__ import annotations

import pandas as pd

# Same key as the BigQuery QUALIFY in BigQueryPacketStore.load_packets. It
# includes device_ts_us so packets from before and after a board reboot
# (same seq, different board time) are both kept.
DEDUP_KEY = ["role", "seq", "device_ts_us"]

NUMERIC_COLUMNS = {
    "seq": "int64",
    "device_ts_us": "int64",
    "phone_rx_s": "float64",
    "ax": "float64",
    "ay": "float64",
    "az": "float64",
    "gx": "float64",
    "gy": "float64",
    "gz": "float64",
}


def dedup_packets(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the first-ingested copy of every (role, seq, device_ts_us)."""
    if df.empty:
        return df.copy()
    if "ingested_at" in df.columns:
        df = df.sort_values("ingested_at", kind="mergesort")
    return df.drop_duplicates(subset=DEDUP_KEY, keep="first")


def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for column, dtype in NUMERIC_COLUMNS.items():
        if column in out.columns:
            out[column] = out[column].astype(dtype)
    if "role" in out.columns:
        out["role"] = out["role"].astype(str)
    return out


def split_by_role(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Deduplicate and split raw packets into one DataFrame per sensor role."""
    clean = normalize_types(dedup_packets(df))
    return {
        role: clean[clean["role"] == role].reset_index(drop=True)
        for role in ("A", "B")
    }
