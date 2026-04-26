"""Gmail OAuth helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


def load_credentials(
    *,
    client_secret_path: str | Path,
    token_path: str | Path,
    scopes: list[str] | None = None,
) -> Any:
    """Load or bootstrap Gmail API credentials."""
    token_file = Path(token_path).expanduser()
    scopes = scopes or [GMAIL_MODIFY_SCOPE]

    if not token_file.exists():
        if not Path(client_secret_path).expanduser().exists():
            raise ValueError("Client secret file does not exist")

        flow = _import_flow().from_client_secrets_file(
            str(Path(client_secret_path).expanduser()), scopes
        )
        credentials = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    credentials = None
    if token_file.exists():
        credentials = _import_credentials().from_authorized_user_file(
            str(token_file), scopes
        )

    if credentials and getattr(credentials, "valid", False):
        return credentials

    if (
        credentials
        and getattr(credentials, "expired", False)
        and getattr(credentials, "refresh_token", None)
    ):
        credentials.refresh(_import_request()())
    else:
        flow = _import_flow().from_client_secrets_file(
            str(Path(client_secret_path).expanduser()), scopes
        )
        credentials = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _import_credentials() -> Any:
    from google.oauth2.credentials import Credentials

    return Credentials


def _import_flow() -> Any:
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow


def _import_request() -> Any:
    from google.auth.transport.requests import Request

    return Request
