"""Runtime configuration loading for the DMARC reporter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
from typing import Any

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - exercised on Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_LABEL = "DMARC"
DEFAULT_DATA_DIR = Path("data")
DEFAULT_REPORTS_DIR = Path("reports")
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "dmarc.sqlite"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass
class AppConfig:
    """Application runtime configuration."""

    gmail_client_secret: Path | None
    gmail_token_path: Path | None
    gmail_label: str = DEFAULT_LABEL
    data_dir: Path = DEFAULT_DATA_DIR
    reports_dir: Path = DEFAULT_REPORTS_DIR
    database_path: Path = DEFAULT_DB_PATH
    log_level: str = DEFAULT_LOG_LEVEL
    browser_auto_open: bool = False

    def ensure_directories(self) -> None:
        """Create local runtime directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(
    config_path: str | os.PathLike[str] | None = None,
    *,
    require_gmail: bool = True,
) -> AppConfig:
    """Load configuration from optional file and environment variables."""
    file_data = _load_config_file(config_path)
    env_data = {
        key: value
        for key, value in _load_env_config().items()
        if value not in {None, ""}
    }

    merged = {**file_data, **env_data}

    client_secret: Path | None = None
    token_path: Path | None = None
    if require_gmail:
        client_secret = _require_existing_file_path(
            merged.get("gmail_client_secret"),
            "DMARC_GMAIL_CLIENT_SECRET",
        )
        token_path = _require_output_file_path(
            merged.get("gmail_token_path"),
            "DMARC_GMAIL_TOKEN_PATH",
        )
        _require_external_secret_path(client_secret, "DMARC_GMAIL_CLIENT_SECRET")
        _require_external_secret_path(token_path, "DMARC_GMAIL_TOKEN_PATH")

    data_dir = _normalize_path(merged.get("data_dir", DEFAULT_DATA_DIR))
    reports_dir = _normalize_path(merged.get("reports_dir", DEFAULT_REPORTS_DIR))
    database_path = _normalize_path(merged.get("database_path", data_dir / "dmarc.sqlite"))

    return AppConfig(
        gmail_client_secret=client_secret,
        gmail_token_path=token_path,
        gmail_label=str(merged.get("gmail_label", DEFAULT_LABEL)),
        data_dir=data_dir,
        reports_dir=reports_dir,
        database_path=database_path,
        log_level=str(merged.get("log_level", DEFAULT_LOG_LEVEL)).upper(),
        browser_auto_open=_to_bool(merged.get("browser_auto_open", False)),
    )


def _load_config_file(config_path: str | os.PathLike[str] | None) -> dict[str, Any]:
    if config_path is None:
        return {}

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".toml", ".tml"}:
        with path.open("rb") as handle:
            return tomllib.load(handle)

    raise ValueError(f"Unsupported config file type: {path.suffix}")


def _load_env_config() -> dict[str, Any]:
    env = os.environ
    return {
        "gmail_client_secret": env.get("DMARC_GMAIL_CLIENT_SECRET"),
        "gmail_token_path": env.get("DMARC_GMAIL_TOKEN_PATH"),
        "gmail_label": env.get("DMARC_LABEL"),
        "data_dir": env.get("DMARC_DATA_DIR"),
        "reports_dir": env.get("DMARC_REPORTS_DIR"),
        "database_path": env.get("DMARC_DATABASE_PATH"),
        "log_level": env.get("DMARC_LOG_LEVEL"),
        "browser_auto_open": env.get("DMARC_BROWSER_AUTO_OPEN"),
    }


def _require_existing_file_path(value: Any, env_name: str) -> Path:
    if value in {None, ""}:
        raise ValueError(f"Missing required configuration: {env_name}")
    path = _normalize_path(value)
    if not path.exists():
        raise FileNotFoundError(f"Configured file does not exist for {env_name}: {path}")
    if not path.is_file():
        raise ValueError(f"Configured path must be a file for {env_name}: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError(f"Configured file for {env_name} must be a JSON file: {path}")
    return path


def _require_output_file_path(value: Any, env_name: str) -> Path:
    if value in {None, ""}:
        raise ValueError(f"Missing required configuration: {env_name}")
    path = _normalize_path(value)
    if path.exists() and not path.is_file():
        raise ValueError(f"Configured path must be a file for {env_name}: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError(f"Configured file for {env_name} must be a JSON file: {path}")
    return path


def _require_external_secret_path(path: Path, env_name: str) -> None:
    workspace_root = Path.cwd().resolve()
    try:
        path.relative_to(workspace_root)
    except ValueError:
        return
    raise ValueError(
        f"{env_name} must point outside the project workspace to avoid storing Gmail secrets in the repository tree: {path}"
    )


def _normalize_path(value: Any) -> Path:
    return Path(str(value)).expanduser().resolve(strict=False)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
