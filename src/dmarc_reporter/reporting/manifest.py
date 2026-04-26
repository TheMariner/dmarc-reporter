"""Report manifest and publishing orchestration."""

from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path
import shutil
import uuid

from dmarc_reporter.config import AppConfig
from dmarc_reporter.logging import get_logger
from dmarc_reporter.reporting.aggregations import fetch_period_records, summarize_period
from dmarc_reporter.reporting.builder import (
    DEFAULT_LOGO_PATH,
    build_report_library_catalog,
    build_report_library_entry,
    build_static_index,
    build_static_report,
)
from dmarc_reporter.reporting.periods import (
    ReportingPeriod,
    determine_report_build_action,
    periods_for_coverage_window,
)
from dmarc_reporter.storage.repository import Repository, utc_now


class ReportGenerationResult(dict):
    """Typed-ish mapping for report generation stats."""


def generate_reports(
    *,
    config: AppConfig,
    repository: Repository,
    run_id: str,
    as_of: datetime | None = None,
) -> ReportGenerationResult:
    """Generate completed period reports from normalized records."""
    logger = get_logger(__name__)
    _ensure_report_brand_assets(config)
    sync_reporting_period_states(repository=repository, as_of=as_of)
    candidate_periods = _candidate_periods(repository)
    generated = 0
    refreshed = 0
    skipped = 0
    failed = 0
    outputs: list[str] = []
    decisions: list[dict[str, str | bool | None]] = []

    for row in candidate_periods:
        period = _period_from_row(row)
        output_path = _report_output_path(config, period)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prior_artifact = repository.get_generated_report_artifact(period.period_id)
        had_existing_artifact = prior_artifact is not None and output_path.exists()
        decision, reason = determine_report_build_action(
            refresh_status=str(row["refresh_status"]),
            has_existing_artifact=prior_artifact is not None,
            artifact_exists=output_path.exists(),
        )
        decisions.append(
            _build_decision(
                period_id=period.period_id,
                decision=decision,
                reason=reason,
                row=row,
            )
        )

        if decision == "skip_unchanged":
            repository.upsert_reporting_period(
                {
                    **_period_payload(period),
                    "completeness_status": "complete",
                    "refresh_status": "current",
                    "latest_source_date": period.latest_source_date,
                    "last_data_change_at": row.get("last_data_change_at"),
                    "last_built_at": row.get("last_built_at"),
                    "last_built_run_id": row.get("last_built_run_id"),
                    "last_change_reason": "unchanged_data",
                }
            )
            repository.upsert_generated_report_artifact(
                {
                    "generated_report_id": period.period_id,
                    "period_id": period.period_id,
                    "output_path": str(output_path),
                    "content_hash": str(prior_artifact["content_hash"]) if prior_artifact is not None else "",
                    "record_count": 0 if prior_artifact is None else int(prior_artifact["record_count"]),
                    "build_status": "skipped",
                    "partial_data_flag": 0 if prior_artifact is None else int(prior_artifact["partial_data_flag"]),
                    "generated_at": utc_now(),
                    "generated_by_run_id": run_id,
                    "failure_reason": None,
                }
            )
            if prior_artifact is not None and output_path.exists():
                _sync_report_library_entry(
                    repository=repository,
                    period=period,
                    output_path=output_path,
                    reports_dir=config.reports_dir,
                    artifact=prior_artifact,
                )
            skipped += 1
            logger.info("Skipping unchanged report for period %s", period.period_id)
            print(
                f"skipped_unchanged period_id={period.period_id} path={output_path}",
                flush=True,
            )
            continue

        start_dt = datetime.combine(period.period_start, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(period.period_end, time.max, tzinfo=timezone.utc)
        records = fetch_period_records(repository, period_start=start_dt, period_end=end_dt)
        if not records:
            continue

        summary = summarize_period(records)
        html, content_hash = build_static_report(
            period=period,
            summary=summary,
            template_path=Path("src/dmarc_reporter/web/template.html.j2"),
            styles_path=Path("src/dmarc_reporter/web/styles.css"),
            script_path=Path("src/dmarc_reporter/web/app.js"),
        )

        try:
            if decision == "refresh":
                repository.record_event(
                    event_id=str(uuid.uuid4()),
                    run_id=run_id,
                    severity="info",
                    event_type="report_regenerated",
                    detail=f"Regenerating report for period {period.period_id}",
                    period_ref=period.period_id,
                )
                logger.info("Regenerating report for period %s", period.period_id)

            print(
                f"{'writing_new_report' if not had_existing_artifact else 'rewriting_report'} "
                f"period_id={period.period_id} path={output_path}",
                flush=True,
            )
            _write_report_atomically(output_path, html)
            print(
                f"wrote_report period_id={period.period_id} path={output_path}",
                flush=True,
            )
        except Exception as exc:
            failed += 1
            repository.upsert_reporting_period(
                {
                    **_period_payload(period),
                    "completeness_status": "complete",
                    "refresh_status": "failed",
                    "latest_source_date": period.latest_source_date,
                    "last_data_change_at": row.get("last_data_change_at"),
                    "last_built_at": row.get("last_built_at"),
                    "last_built_run_id": row.get("last_built_run_id"),
                    "last_change_reason": "build_failure_retry",
                }
            )
            repository.upsert_generated_report_artifact(
                {
                    "generated_report_id": period.period_id,
                    "period_id": period.period_id,
                    "output_path": str(output_path),
                    "content_hash": content_hash,
                    "record_count": summary["record_count"],
                    "build_status": "failed",
                    "partial_data_flag": int(summary["partial_data"]),
                    "generated_at": utc_now(),
                    "generated_by_run_id": run_id,
                    "failure_reason": str(exc),
                }
            )
            repository.record_event(
                event_id=str(uuid.uuid4()),
                run_id=run_id,
                severity="error",
                event_type="report_build_failed",
                detail=f"Failed to build report for period {period.period_id}: {exc}",
                period_ref=period.period_id,
            )
            logger.exception("Failed to build report for period %s", period.period_id)
            continue

        if had_existing_artifact:
            refreshed += 1
        else:
            generated += 1

        repository.upsert_reporting_period(
            {
                **_period_payload(period),
                "completeness_status": "complete",
                "refresh_status": "current",
                "latest_source_date": period.latest_source_date,
                "last_data_change_at": row.get("last_data_change_at"),
                "last_built_at": utc_now(),
                "last_built_run_id": run_id,
                "last_change_reason": "new_data" if decision == "generate" else "late_data",
            }
        )
        repository.upsert_generated_report_artifact(
            {
                "generated_report_id": period.period_id,
                "period_id": period.period_id,
                "output_path": str(output_path),
                "content_hash": content_hash,
                "record_count": summary["record_count"],
                "build_status": "generated" if decision == "generate" else "refreshed",
                "partial_data_flag": int(summary["partial_data"]),
                "generated_at": utc_now(),
                "generated_by_run_id": run_id,
                "failure_reason": None,
            }
        )
        _sync_report_library_entry(
            repository=repository,
            period=period,
            output_path=output_path,
            reports_dir=config.reports_dir,
            artifact={
                "content_hash": content_hash,
                "build_status": "generated" if decision == "generate" else "refreshed",
                "generated_at": utc_now(),
            },
        )
        outputs.append(str(output_path))

    index_path = _publish_report_index(config=config, repository=repository)
    outputs.append(str(index_path))

    return ReportGenerationResult(
        considered=len(candidate_periods),
        generated=generated,
        regenerated=refreshed,
        skipped=skipped,
        skipped_unchanged=skipped,
        failed=failed,
        outputs=outputs,
        decisions=decisions,
    )


def sync_reporting_period_states(
    *,
    repository: Repository,
    as_of: datetime | None = None,
) -> int:
    changed = 0
    rows = repository.connection.execute(
        """
        SELECT coverage_date_begin, coverage_date_end, MAX(created_at) AS last_record_created_at
        FROM normalized_records
        GROUP BY coverage_date_begin, coverage_date_end
        ORDER BY coverage_date_begin, coverage_date_end
        """
    ).fetchall()
    period_inputs: dict[str, dict[str, object]] = {}
    for row in rows:
        for period in periods_for_coverage_window(
            row["coverage_date_begin"],
            row["coverage_date_end"],
            as_of=as_of,
        ):
            existing_input = period_inputs.get(period.period_id)
            if existing_input is None:
                period_inputs[period.period_id] = {
                    "period": period,
                    "latest_source_date": period.latest_source_date,
                    "latest_record_created_at": row["last_record_created_at"],
                }
                continue
            if str(row["last_record_created_at"]) > str(existing_input["latest_record_created_at"]):
                existing_input["latest_record_created_at"] = row["last_record_created_at"]
            if period.latest_source_date and (
                existing_input["latest_source_date"] is None
                or str(period.latest_source_date) > str(existing_input["latest_source_date"])
            ):
                existing_input["latest_source_date"] = period.latest_source_date

    for period_id, input_state in period_inputs.items():
        period = input_state["period"]
        assert isinstance(period, ReportingPeriod)
        latest_source_date = None if input_state["latest_source_date"] is None else str(input_state["latest_source_date"])
        latest_record_created_at = (
            None if input_state["latest_record_created_at"] is None else str(input_state["latest_record_created_at"])
        )
        existing = repository.get_reporting_period(period_id)
        state_changed = False
        if existing is None:
            refresh_status = "pending_initial"
            last_built_at = None
            last_built_run_id = None
            last_data_change_at = latest_record_created_at or utc_now()
            last_change_reason = "new_data"
            state_changed = period.completeness_status == "complete"
        else:
            refresh_status = str(existing["refresh_status"])
            if period.completeness_status == "complete" and existing["last_built_at"] is None:
                refresh_status = "pending_initial"
            elif (
                period.completeness_status == "complete"
                and latest_record_created_at is not None
                and existing["last_built_at"] is not None
                and latest_record_created_at > str(existing["last_built_at"])
                and str(existing["refresh_status"]) == "current"
            ):
                refresh_status = "stale"
            state_changed = (
                existing["latest_source_date"] != latest_source_date
                or existing["refresh_status"] != refresh_status
                or (
                    refresh_status == "stale"
                    and latest_record_created_at is not None
                    and (
                        existing["last_data_change_at"] is None
                        or latest_record_created_at > str(existing["last_data_change_at"])
                    )
                )
            ) and period.completeness_status == "complete"
            last_built_at = existing["last_built_at"]
            last_built_run_id = existing["last_built_run_id"]
            last_data_change_at = (
                latest_record_created_at or utc_now()
                if refresh_status in {"pending_initial", "stale"} and state_changed
                else existing["last_data_change_at"]
            )
            last_change_reason = (
                "late_data"
                if refresh_status == "stale"
                else str(existing["last_change_reason"] or "new_data")
            )
        payload = {
            **_period_payload(period),
            "refresh_status": refresh_status,
            "latest_source_date": latest_source_date,
            "last_data_change_at": last_data_change_at,
            "last_built_at": last_built_at,
            "last_built_run_id": last_built_run_id,
            "last_change_reason": last_change_reason,
        }
        repository.upsert_reporting_period(payload)
        if state_changed and refresh_status in {"pending_initial", "stale"}:
            changed += 1
    return changed


def _candidate_periods(repository: Repository) -> list[dict[str, str | None]]:
    return repository.list_complete_reporting_periods()


def _write_report_atomically(output_path: Path, html: str) -> None:
    temp_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temp_path.write_text(html, encoding="utf-8")
    temp_path.replace(output_path)


def _report_output_path(config: AppConfig, period: ReportingPeriod) -> Path:
    subdir = {
        "weekly": "weekly",
        "monthly": "monthly",
        "yearly": "yearly",
    }[period.period_type]
    return config.reports_dir / subdir / f"{period.period_id}.html"


def _report_index_path(config: AppConfig) -> Path:
    return config.reports_dir / "index.html"


def _report_brand_asset_path(config: AppConfig) -> Path:
    return config.reports_dir / "images" / DEFAULT_LOGO_PATH.name


def _period_payload(period: ReportingPeriod) -> dict[str, str | None]:
    return {
        "period_id": period.period_id,
        "period_type": period.period_type,
        "period_start": period.period_start.isoformat(),
        "period_end": period.period_end.isoformat(),
        "calendar_rule": period.calendar_rule,
        "completeness_status": period.completeness_status,
        "refresh_status": period.refresh_status,
        "latest_source_date": period.latest_source_date,
        "last_data_change_at": period.last_data_change_at,
        "last_built_at": period.last_built_at,
        "last_built_run_id": period.last_built_run_id,
        "last_change_reason": period.last_change_reason,
    }


def _period_from_row(row: dict[str, str | None]) -> ReportingPeriod:
    return ReportingPeriod(
        period_id=str(row["period_id"]),
        period_type=str(row["period_type"]),
        period_start=datetime.fromisoformat(str(row["period_start"])).date(),
        period_end=datetime.fromisoformat(str(row["period_end"])).date(),
        calendar_rule=str(row["calendar_rule"]),
        completeness_status=str(row["completeness_status"]),
        refresh_status=str(row["refresh_status"]),
        latest_source_date=None if row["latest_source_date"] is None else str(row["latest_source_date"]),
        last_data_change_at=None if row["last_data_change_at"] is None else str(row["last_data_change_at"]),
        last_built_at=None if row["last_built_at"] is None else str(row["last_built_at"]),
        last_built_run_id=None if row["last_built_run_id"] is None else str(row["last_built_run_id"]),
        last_change_reason=None if row["last_change_reason"] is None else str(row["last_change_reason"]),
    )


def _build_decision(
    *,
    period_id: str,
    decision: str,
    reason: str,
    row: dict[str, str | None],
) -> dict[str, str | bool | None]:
    return {
        "period_id": period_id,
        "decision": decision,
        "decision_reason": reason,
        "source_state_hash": _source_state_hash(row),
        "reported_in_summary": True,
    }


def _source_state_hash(row: dict[str, str | None]) -> str:
    return "|".join(
        [
            str(row.get("period_id") or ""),
            str(row.get("last_data_change_at") or ""),
            str(row.get("last_built_at") or ""),
            str(row.get("refresh_status") or ""),
        ]
    )


def _sync_report_library_entry(
    *,
    repository: Repository,
    period: ReportingPeriod,
    output_path: Path,
    reports_dir: Path,
    artifact: dict[str, str | int | None],
) -> None:
    entry = build_report_library_entry(
        period=period,
        output_path=output_path,
        reports_dir=reports_dir,
        content_hash=str(artifact.get("content_hash") or ""),
        build_status=str(artifact.get("build_status") or "generated"),
        generated_at=str(artifact.get("generated_at") or utc_now()),
    )
    repository.upsert_report_library_entry(entry)


def _publish_report_index(*, config: AppConfig, repository: Repository) -> Path:
    index_path = _report_index_path(config)
    entries = [
        entry
        for entry in repository.list_report_library_entries()
        if Path(str(entry["output_path"])).exists()
    ]
    catalog = build_report_library_catalog(entries)
    html, _content_hash = build_static_index(
        catalog=catalog,
        template_path=Path("src/dmarc_reporter/web/index.html.j2"),
        styles_path=Path("src/dmarc_reporter/web/styles.css"),
        script_path=Path("src/dmarc_reporter/web/index.js"),
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    _write_report_atomically(index_path, html)
    return index_path


def _ensure_report_brand_assets(config: AppConfig) -> None:
    source_path = Path(DEFAULT_LOGO_PATH)
    if not source_path.exists():
        return
    target_path = _report_brand_asset_path(config)
    if target_path.exists():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)
