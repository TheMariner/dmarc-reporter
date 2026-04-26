# DMARC Reporter

Local Python application for downloading aggregate DMARC reports from a Gmail mailbox,
normalizing them into SQLite, and publishing self-contained weekly, monthly, and
yearly HTML reports. The operator workflow is split into `sync` for mailbox/data
refresh and `build-reports` for report generation from stored data.

## Primary Commands

- `./dmarc-sync`: download new DMARC reports and update the local database
- `./dmarc-build-reports`: generate or refresh report artifacts from stored data
- `./dmarc-sync --reset`: clear local state and restore Gmail unread state without implicitly rebuilding reports

## What It Does

- Reads Gmail messages labeled `DMARC`
- Treats unread labeled messages as eligible for ingestion
- Marks messages read after successful ingest, including duplicate-only messages
- Stores normalized report data and operational state in `data/dmarc.sqlite`
- Lets operators run acquisition and report generation independently
- Generates richer self-contained interactive HTML reports under
  `reports/weekly/`, `reports/monthly/`, and `reports/yearly/` from stored data
  only
- Generates a self-contained `reports/index.html` report library for finding
  artifacts by cadence and available calendar slices
- Supports `sync --reset` to clear local state and restore all labeled Gmail
  messages to unread without implicitly rebuilding reports

## Environment

Required environment variables:

- `DMARC_GMAIL_CLIENT_SECRET`: Path to the Gmail OAuth client secret JSON file.
- `DMARC_GMAIL_TOKEN_PATH`: Path to the Gmail OAuth token cache JSON file.

Optional environment variables:

- `DMARC_LABEL`: Gmail label name. Default: `DMARC`
- `DMARC_DATA_DIR`: Local data directory. Default: `data`
- `DMARC_REPORTS_DIR`: Report output directory. Default: `reports`
- `DMARC_DATABASE_PATH`: SQLite database path. Default: `data/dmarc.sqlite`
- `DMARC_LOG_LEVEL`: Logging level. Default: `INFO`
- `DMARC_BROWSER_AUTO_OPEN`: Boolean flag for browser auto-open behavior. Default:
  `false`

Credential files are intentionally required to live outside the project workspace so
OAuth secrets and token caches do not end up in the repository tree.

## Obtain Gmail Credentials

This application uses a Google OAuth 2.0 Desktop client. The result you need is a
downloaded Google client JSON file for a Desktop app, plus a token JSON file that
this application creates on first run.

### 1. Create or choose a Google Cloud project

1. Open the Google Cloud Console.
2. Create a new project, or select an existing project for this DMARC reporter.
3. Make sure your account or organization policies allow Gmail API and OAuth client
   configuration.

### 2. Enable the Gmail API

1. In Google Cloud Console, open `APIs & Services`.
2. Search for `Gmail API`.
3. Open the Gmail API page.
4. Click `Enable`.

### 3. Configure the Google Auth Platform consent screen

1. In Google Cloud Console, open `Google Auth Platform`.
2. Configure branding / consent details.
3. Enter an app name such as `DMARC Reporter`.
4. Choose a support email address.
5. Choose the audience:
   - Use `Internal` if the mailbox and project are in the same Workspace organization.
   - Use `External` for personal Gmail or cross-organization use.
6. Enter a developer contact email.
7. Accept the policy acknowledgement and create the app.

If you choose `External`, keep the app in testing unless you have a reason to publish
it. Add the Gmail account you will use as a test user if Google prompts for test-user
configuration.

### 4. Create the correct OAuth client

1. In Google Cloud Console, open `Google Auth Platform > Clients`.
2. Click `Create Client`.
3. For application type, choose `Desktop app`.
4. Give it a recognizable name such as `DMARC Reporter Local Desktop`.
5. Click `Create`.
6. Download the client JSON file.

The downloaded file is your `DMARC_GMAIL_CLIENT_SECRET` file.

### 5. Store the files outside this project

Create a private directory outside this repository:

```bash
mkdir -p "$HOME/.config/dmarc"
mv /path/to/downloaded-client-secret.json "$HOME/.config/dmarc/client-secret.json"
```

Set environment variables:

```bash
export DMARC_GMAIL_CLIENT_SECRET="$HOME/.config/dmarc/client-secret.json"
export DMARC_GMAIL_TOKEN_PATH="$HOME/.config/dmarc/token.json"
```

Notes:

- `DMARC_GMAIL_CLIENT_SECRET` must point to the downloaded Desktop OAuth client JSON.
- `DMARC_GMAIL_TOKEN_PATH` should point to a token file location; it does not need to
  exist yet.
- Both paths should be outside this workspace.

### 6. First run authorization

On the first sync:

```bash
./dmarc-sync
```

Google should open a browser window for consent. Sign in with the Gmail account that
receives the DMARC mail, approve access, and let the local redirect complete. After
that:

- Google stores the refresh/access token at `DMARC_GMAIL_TOKEN_PATH`
- Later runs reuse that token automatically
- If you change scopes or credentials, delete the token JSON and run again

### 7. Common mistakes

- Do not create an `API key`; this app needs OAuth user consent.
- Do not create a `Web application` client; use `Desktop app`.
- Do not place the client secret or token file under this repository.
- Do not use a service account for a normal personal Gmail mailbox workflow.
- If the consent screen is `External` and still in testing, make sure your Gmail
  account is added as an allowed test user.

### Personal Gmail vs Google Workspace

Use this decision rule:

- If the mailbox is a normal `@gmail.com` account, configure the consent screen as
  `External`.
- If the mailbox is a managed Google Workspace mailbox in your organization, you can
  usually configure the consent screen as `Internal`.

Personal Gmail (`@gmail.com`) notes:

- `Internal` will not work for a personal Gmail account.
- If the app is in testing mode, the Gmail account you will sign into must be listed
  as a test user.
- If Google shows `This app isn't verified`, that is expected for an unpublished local
  tool. Continue only if you recognize the project and credential you created.

Google Workspace notes:

- `Internal` is usually the simpler choice if the Gmail mailbox belongs to the same
  Workspace organization as the Cloud project.
- Some Workspace admins restrict Gmail API access or OAuth app usage. If consent or
  token creation fails, check Admin Console policies before debugging the Python app.
- If the mailbox is in Workspace but outside the organization that owns the Cloud
  project, treat it like an external-user case and use `External`.

If you are unsure which type you have:

- `name@gmail.com` is personal Gmail.
- `name@yourcompany.com` is usually Google Workspace, but only if that domain is
  actually hosted in Google Workspace.

## Setup

```bash
./setup
```

The script creates `.venv`, installs the development dependencies, and installs the
project package into that environment in editable mode. After it finishes, activate
the environment:

```bash
source .venv/bin/activate
```

## Run Workflows

```bash
./dmarc-sync
```

Equivalent module invocation:

```bash
python -m dmarc_reporter sync
```

Generate reports from the stored dataset only:

```bash
./dmarc-build-reports
```

The generated artifact is a self-contained report application: the default load
surfaces top findings first, keeps the full normalized detail available inside the
same HTML file, and is designed for local browser use without a backend. Reports
now use a dark shell with a left filter sidebar that scrolls
independently from the analytical pane. The top-left logo is sourced from
`images/logo.png`, embedded into the generated HTML, and copied into
`reports/images/` on report builds if that asset is not already present there.

Each reporting run also refreshes `reports/index.html`, a branded report library
that lets you filter available artifacts by cadence and applicable calendar
dimensions before opening a report.

When nothing changed for a completed period, `./dmarc-build-reports` now reports
that period as `skipped unchanged` instead of silently doing nothing or rewriting
the artifact. The report library is still refreshed from stored catalog metadata
so navigation remains current. The CLI summary prints per-period lines for
newly generated reports and for `skipped unchanged` periods, while refreshed
periods are counted in the totals without per-period log spam.

Reset to a clean baseline without rebuilding reports:

```bash
./dmarc-sync --reset
```

## Verification

Useful local checks:

```bash
python -m dmarc_reporter --version
PYTHONPATH=src .venv/bin/python -m pytest tests/contract/test_cli_contract.py tests/integration/test_report_artifacts.py tests/integration/test_report_index.py tests/integration/test_report_regeneration.py tests/unit/test_aggregations.py tests/unit/test_periods.py tests/unit/test_report_catalog.py
```

More detail is in [specs/002-split-ingest-reporting/quickstart.md](/Users/jkhoury/Downloads/Work/dmarc/specs/002-split-ingest-reporting/quickstart.md:1).
