"""CLI entrypoint for the DMARC reporter project."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from dmarc_reporter.config import AppConfig, load_config
from dmarc_reporter.gmail.auth import load_credentials
from dmarc_reporter.gmail.client import GmailClient, build_gmail_service
from dmarc_reporter.ingest.pipeline import RunSummary, run_ingestion
from dmarc_reporter.logging import configure_logging, get_logger, log_workflow_summary
from dmarc_reporter.reporting.manifest import generate_reports
from dmarc_reporter.storage.repository import ProcessingRun, Repository, utc_now
from dmarc_reporter.storage.reset import perform_reset


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(
        prog="python -m dmarc_reporter",
        description="Local DMARC acquisition and reporting workflows.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="dmarc-reporter 0.1.0",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Download and ingest DMARC data without building reports.",
    )
    sync_parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear local state, restore DMARC-labeled messages to unread, and stop.",
    )
    sync_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a configuration file.",
    )
    sync_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    sync_parser.set_defaults(handler=handle_sync)

    reports_parser = subparsers.add_parser(
        "build-reports",
        help="Generate or refresh reports from persisted data only.",
    )
    reports_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a configuration file.",
    )
    reports_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    reports_parser.set_defaults(handler=handle_build_reports)

    return parser


def handle_sync(args: argparse.Namespace) -> int:
    """Run the acquisition workflow."""
    logger = get_logger(__name__)
    try:
        config = load_config(args.config, require_gmail=True)
        config.ensure_directories()
        configure_logging(verbose=args.verbose, log_level=config.log_level)
        repository, gmail_client = _build_sync_runtime(config)
        try:
            if args.reset:
                reset_result = perform_reset(
                    config=config,
                    repository=repository,
                    gmail_client=gmail_client,
                )
                repository = reset_result.repository
                reset_run = _latest_reset_run(repository)
                summary = RunSummary(
                    run_id="reset" if reset_run is None else str(reset_run["run_id"]),
                    mode="reset",
                    status="completed" if reset_run is None else str(reset_run["status"]),
                    messages_restored_unread=reset_result.messages_restored_unread,
                    warnings=0 if reset_run is None else int(reset_run["failures_count"]),
                )
                log_workflow_summary(
                    logger,
                    "sync",
                    mode=summary.mode,
                    messages_scanned=summary.messages_seen,
                    messages_ingested=summary.messages_ingested,
                    periods_marked_stale=summary.periods_marked_stale,
                    follow_up_reporting_needed=str(summary.follow_up_reporting_needed).lower(),
                    warning_count=summary.warnings,
                )
                _print_sync_summary(summary, config)
                return 2 if summary.status == "completed_with_warnings" else 0
            summary = run_ingestion(
                config=config,
                repository=repository,
                gmail_client=gmail_client,
                reset=False,
            )
        finally:
            repository.close()
            if hasattr(gmail_client, "close"):
                gmail_client.close()
    except Exception as exc:  # pragma: no cover - CLI failure surface
        print(f"sync failed: {exc}", file=sys.stderr)
        return 1

    log_workflow_summary(
        logger,
        "sync",
        mode=summary.mode,
        messages_scanned=summary.messages_seen,
        messages_ingested=summary.messages_ingested,
        periods_marked_stale=summary.periods_marked_stale,
        follow_up_reporting_needed=str(summary.follow_up_reporting_needed).lower(),
        warning_count=summary.warnings,
    )
    _print_sync_summary(summary, config)
    return 2 if summary.warnings else 0


def handle_build_reports(args: argparse.Namespace) -> int:
    """Run the reporting workflow."""
    logger = get_logger(__name__)
    try:
        config = load_config(args.config, require_gmail=False)
        config.ensure_directories()
        configure_logging(verbose=args.verbose, log_level=config.log_level)
        repository = Repository(config.database_path)
        try:
            run_id = _start_reporting_run(repository)
            report_result = generate_reports(
                config=config,
                repository=repository,
                run_id=run_id,
            )
            status = "completed_with_warnings" if int(report_result["failed"]) else "completed"
            repository.finish_processing_run(
                run_id,
                status=status,
                summary_message="report build complete",
                counters={
                    "periods_considered": int(report_result["considered"]),
                    "reports_generated": int(report_result["generated"]),
                    "reports_regenerated": int(report_result["regenerated"]),
                    "reports_skipped": int(report_result["skipped_unchanged"]),
                    "failures_count": int(report_result["failed"]),
                },
            )
        finally:
            repository.close()
    except Exception as exc:  # pragma: no cover - CLI failure surface
        print(f"build-reports failed: {exc}", file=sys.stderr)
        return 1

    log_workflow_summary(
        logger,
        "build_reports",
        periods_considered=int(report_result["considered"]),
        reports_generated=int(report_result["generated"]),
        reports_regenerated=int(report_result["regenerated"]),
        reports_skipped=int(report_result["skipped_unchanged"]),
        warning_count=int(report_result["failed"]),
    )
    _print_report_summary(report_result, config)
    return 2 if int(report_result["failed"]) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return int(handler(args))


def _build_sync_runtime(config: AppConfig) -> tuple[Repository, GmailClient]:
    if config.gmail_client_secret is None or config.gmail_token_path is None:
        raise ValueError("Gmail credentials are required for the sync workflow")
    credentials = load_credentials(
        client_secret_path=config.gmail_client_secret,
        token_path=config.gmail_token_path,
    )
    service = build_gmail_service(credentials)
    gmail_client = GmailClient(service)
    repository = Repository(config.database_path)
    return repository, gmail_client


def _print_sync_summary(summary: RunSummary, config: AppConfig) -> None:
    print("workflow=sync")
    print(f"mode={summary.mode}")
    print(f"messages_scanned={summary.messages_seen}")
    print(f"messages_ingested={summary.messages_ingested}")
    print(f"duplicate_reports={summary.duplicates_detected}")
    print(f"periods_marked_stale={summary.periods_marked_stale}")
    print(f"follow_up_reporting_needed={str(summary.follow_up_reporting_needed).lower()}")
    print(f"messages_restored_unread={summary.messages_restored_unread}")
    print(f"warning_count={summary.warnings}")
    print(f"database_path={config.database_path}")
    print(f"reports_root={config.reports_dir}")


def _print_report_summary(report_result: dict[str, object], config: AppConfig) -> None:
    print("workflow=build-reports")
    print(f"periods_considered={int(report_result['considered'])}")
    print(f"reports_generated={int(report_result['generated'])}")
    print(f"reports_regenerated={int(report_result['regenerated'])}")
    print(f"reports_skipped={int(report_result['skipped'])}")
    print(f"reports_skipped_unchanged={int(report_result['skipped_unchanged'])}")
    print(f"warning_count={int(report_result['failed'])}")
    print(f"reports_root={config.reports_dir}")
    for decision in report_result.get("decisions", []):
        if not bool(decision.get("reported_in_summary")):
            continue
        decision_name = str(decision["decision"])
        if decision_name not in {"generate", "skip_unchanged"}:
            continue
        normalized = "skipped_unchanged" if decision_name == "skip_unchanged" else (
            "refreshed" if decision_name == "refresh" else "generated"
        )
        print(
            f"period_status={normalized} period_id={decision['period_id']} "
            f"reason={decision['decision_reason']}"
        )


def _start_reporting_run(repository: Repository) -> str:
    run_id = str(__import__("uuid").uuid4())
    repository.create_processing_run(
        ProcessingRun(
            run_id=run_id,
            started_at=utc_now(),
            mode="build-reports",
        )
    )
    return run_id


def _latest_reset_run(repository: Repository) -> dict[str, object] | None:
    row = repository.connection.execute(
        """
        SELECT run_id, status, failures_count
        FROM processing_runs
        WHERE mode = 'reset'
        ORDER BY started_at DESC
        LIMIT 1
        """
    ).fetchone()
    return None if row is None else dict(row)


if __name__ == "__main__":
    raise SystemExit(main())
