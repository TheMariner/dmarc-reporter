from __future__ import annotations

from pathlib import Path

from dmarc_reporter.cli import main
from dmarc_reporter.config import AppConfig
from dmarc_reporter.ingest.pipeline import RunSummary


def assert_report_workflow_summary(output: str, *, config: AppConfig, considered: int, generated: int, regenerated: int, skipped: int) -> None:
    assert "workflow=build-reports" in output
    assert f"periods_considered={considered}" in output
    assert f"reports_generated={generated}" in output
    assert f"reports_regenerated={regenerated}" in output
    assert f"reports_skipped={skipped}" in output
    assert f"reports_skipped_unchanged={skipped}" in output
    assert f"reports_root={config.reports_dir}" in output


class DummyRepository:
    def __init__(self) -> None:
        self.created_runs: list[str] = []
        self.finished_runs: list[tuple[str, str]] = []
        self.connection = _ConnectionStub()

    def create_processing_run(self, run) -> None:
        self.created_runs.append(run.run_id)

    def finish_processing_run(self, run_id: str, *, status: str, summary_message=None, counters=None) -> None:
        self.finished_runs.append((run_id, status))

    def close(self) -> None:
        return None


class _ConnectionStub:
    def execute(self, query: str) -> "_RowCursor":
        assert "FROM processing_runs" in query
        return _RowCursor()


class _RowCursor:
    def fetchone(self) -> dict[str, object]:
        return {"run_id": "reset-run", "status": "completed_with_warnings", "failures_count": 1}


class ResetResultStub:
    def __init__(self, messages_restored_unread: int, repository: DummyRepository | None = None) -> None:
        self.messages_restored_unread = messages_restored_unread
        self.repository = DummyRepository() if repository is None else repository


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        gmail_client_secret=tmp_path / "client.json",
        gmail_token_path=tmp_path / "token.json",
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        database_path=tmp_path / "data" / "dmarc.sqlite",
    )


def test_sync_command_prints_contract_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    config = _config(tmp_path)

    monkeypatch.setattr("dmarc_reporter.cli.load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "dmarc_reporter.cli._build_sync_runtime",
        lambda cfg: (DummyRepository(), object()),
    )
    monkeypatch.setattr(
        "dmarc_reporter.cli.run_ingestion",
        lambda **_: RunSummary(
            run_id="run-1",
            mode="normal",
            status="completed_with_warnings",
            messages_seen=2,
            messages_ingested=1,
            duplicates_detected=1,
            periods_marked_stale=3,
            follow_up_reporting_needed=True,
            warnings=1,
        ),
    )

    exit_code = main(["sync"])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "workflow=sync" in output
    assert "messages_scanned=2" in output
    assert "messages_ingested=1" in output
    assert "duplicate_reports=1" in output
    assert "periods_marked_stale=3" in output
    assert "follow_up_reporting_needed=true" in output
    assert f"database_path={config.database_path}" in output


def test_build_reports_command_prints_contract_summary(monkeypatch, capsys, tmp_path: Path) -> None:
    config = _config(tmp_path)
    dummy_repo = DummyRepository()

    monkeypatch.setattr("dmarc_reporter.cli.load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr("dmarc_reporter.cli.Repository", lambda path: dummy_repo)
    monkeypatch.setattr(
        "dmarc_reporter.cli.generate_reports",
        lambda **_: {
            "considered": 4,
            "generated": 2,
            "regenerated": 1,
            "skipped": 1,
            "skipped_unchanged": 1,
            "failed": 0,
            "outputs": ["reports/index.html"],
            "decisions": [
                {
                    "period_id": "weekly-2024-W15",
                    "decision": "generate",
                    "decision_reason": "missing_artifact",
                    "reported_in_summary": True,
                },
                {
                    "period_id": "weekly-2024-W14",
                    "decision": "refresh",
                    "decision_reason": "stale_data",
                    "reported_in_summary": True,
                },
                {
                    "period_id": "weekly-2024-W16",
                    "decision": "skip_unchanged",
                    "decision_reason": "unchanged_data",
                    "reported_in_summary": True,
                }
            ],
        },
    )

    exit_code = main(["build-reports"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert_report_workflow_summary(
        output,
        config=config,
        considered=4,
        generated=2,
        regenerated=1,
        skipped=1,
    )
    assert "period_status=generated period_id=weekly-2024-W15 reason=missing_artifact" in output
    assert "period_status=refreshed period_id=weekly-2024-W14" not in output
    assert "period_status=skipped_unchanged period_id=weekly-2024-W16 reason=unchanged_data" in output
    assert "reports_root=" in output


def test_sync_reset_invokes_reset_flow_without_running_ingestion(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    runtime_repo = DummyRepository()
    reset_repo = DummyRepository()
    reset_calls: list[bool] = []
    ingestion_calls: list[bool] = []

    monkeypatch.setattr("dmarc_reporter.cli.load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        "dmarc_reporter.cli._build_sync_runtime",
        lambda cfg: (runtime_repo, object()),
    )
    monkeypatch.setattr(
        "dmarc_reporter.cli.perform_reset",
        lambda **_: reset_calls.append(True) or ResetResultStub(messages_restored_unread=7, repository=reset_repo),
    )
    monkeypatch.setattr(
        "dmarc_reporter.cli.run_ingestion",
        lambda **_: ingestion_calls.append(True),
    )

    exit_code = main(["sync", "--reset"])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert reset_calls == [True]
    assert ingestion_calls == []
    assert "workflow=sync" in output
    assert "mode=reset" in output
    assert "messages_restored_unread=7" in output
    assert "warning_count=1" in output
