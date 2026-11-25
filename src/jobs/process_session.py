"""Process one session: load raw packets, run the pipeline, store results.

Used by the Cloud Tasks endpoint (POST /internal/v2/process/{session_id}) and
as a CLI for re-processing and thesis experiments:

    python -m src.jobs.process_session <session_id> [--force] [--dry-run --out angles.csv]

``--force`` skips the readiness check (process whatever is stored now).
``--dry-run`` computes everything but writes nothing to Cloud SQL/BigQuery.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.config import get_settings
from src.processing.pipeline import PipelineResult, run_pipeline
from src.processing.quality import clean_json
from src.processing.settings import PROCESSING_LEASE_S, PROCESSING_MAX_ATTEMPTS
from src.repositories.interfaces import MetadataRepository, PacketStore, ProcessedReport, SessionRecord
from src.utils.logger import get_logger

logger = get_logger()


@dataclass
class ProcessingOutcome:
    status: str  # done | not_ready | busy | not_found | active | failed
    session_id: UUID
    detail: dict = field(default_factory=dict)
    result: PipelineResult | None = None


def expected_counts(app_stats: dict | None) -> dict[str, int]:
    """Packets the app says it uploaded, per role: received - dropped_overflow."""
    expected = {}
    for role, stats in (app_stats or {}).items():
        if isinstance(stats, dict):
            expected[role] = int(stats.get("received", 0)) - int(stats.get("dropped_overflow", 0))
    return expected


def missing_packets(app_stats: dict | None, stored: dict[str, int]) -> dict[str, int]:
    return {
        role: n - stored.get(role, 0)
        for role, n in expected_counts(app_stats).items()
        if stored.get(role, 0) < n
    }


def _since(session: SessionRecord) -> datetime | None:
    return session.created_at - timedelta(days=1) if session.created_at else None


def process_session(
    session_id: UUID,
    repo: MetadataRepository,
    store: PacketStore,
    *,
    force: bool = False,
    write: bool = True,
    max_attempts: int = PROCESSING_MAX_ATTEMPTS,
    lease_s: float = PROCESSING_LEASE_S,
    algorithm_version: str | None = None,
    now=lambda: datetime.now(timezone.utc),
) -> ProcessingOutcome:
    session = repo.get_session(session_id)
    if session is None:
        return ProcessingOutcome("not_found", session_id)

    if write:
        claimed = repo.claim_processing(session_id, lease_s)
        if claimed is None:
            status = "active" if session.status == "active" else "busy"
            return ProcessingOutcome(status, session_id)
        session = claimed

    try:
        since = _since(session)
        missing = missing_packets(session.app_stats, store.count_packets(session_id, since))
        if missing and not force and session.processing_attempts < max_attempts:
            if write:
                repo.release_claim(session_id)
            logger.info("Session %s not ready (attempt %d): missing %s", session_id, session.processing_attempts, missing)
            return ProcessingOutcome(
                "not_ready", session_id, {"missing": missing, "attempts": session.processing_attempts}
            )

        packets = store.load_packets(session_id, since)
        events = repo.list_events(session_id)
        result = run_pipeline(
            packets,
            uptime_anchor_s=session.uptime_anchor_s,
            stopped_uptime_s=session.stopped_uptime_s,
            zero_pose_uptimes=[e.uptime_s for e in events if e.type == "zero_pose"],
            app_stats=session.app_stats,
        )

        quality = dict(result.quality)
        quality["readiness"] = {
            "attempts": session.processing_attempts,
            "missing_vs_app": missing,
            "forced": force,
        }
        quality_ok = result.quality_ok
        if missing:
            quality["reasons"] = list(quality.get("reasons", [])) + ["incomplete_upload"]
            quality_ok = False
        quality = clean_json(quality)

        version = algorithm_version or get_settings().full_algorithm_version
        computed_at = now()
        metrics = result.metrics
        if write:
            store.replace_angles(session_id, result.angles, version, computed_at)
            repo.save_processing_result(
                session_id,
                ProcessedReport(
                    duration_s=metrics.duration_s,
                    max_flexion=metrics.max_flexion,
                    max_extension=metrics.max_extension,
                    max_pronation=metrics.max_pronation,
                    max_supination=metrics.max_supination,
                    rep_count=metrics.rep_count,
                    smoothness=metrics.smoothness,
                    quality=quality,
                    quality_ok=quality_ok,
                    algorithm_version=version,
                    computed_at=computed_at,
                ),
            )
        result.quality, result.quality_ok = quality, quality_ok
        logger.info("Processed session %s (quality_ok=%s)", session_id, quality_ok)
        return ProcessingOutcome("done", session_id, {"metrics": asdict(metrics), "quality_ok": quality_ok}, result)
    except Exception as exc:
        logger.exception("Processing failed for session %s", session_id)
        if write:
            repo.mark_failed(session_id, f"{type(exc).__name__}: {exc}")
        return ProcessingOutcome("failed", session_id, {"error": f"{type(exc).__name__}: {exc}"})


def main(argv: list[str] | None = None, *, repo=None, store=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session_id", type=UUID)
    parser.add_argument("--force", action="store_true", help="skip the readiness check")
    parser.add_argument("--dry-run", action="store_true", help="do not write to Cloud SQL / BigQuery")
    parser.add_argument("--out", help="also save the angle rows to this CSV file")
    args = parser.parse_args(argv)

    if repo is None or store is None:
        from src.api.v2.dependencies import get_metadata_repo, get_packet_store

        repo = repo or get_metadata_repo()
        store = store or get_packet_store()

    outcome = process_session(args.session_id, repo, store, force=args.force, write=not args.dry_run)
    if args.out and outcome.result is not None:
        outcome.result.angles.to_csv(args.out, index=False)
    print(json.dumps({"status": outcome.status, **clean_json(outcome.detail)}, indent=2, default=str))
    return 0 if outcome.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
