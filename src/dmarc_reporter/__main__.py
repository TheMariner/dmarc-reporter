"""Module entrypoint for `python -m dmarc_reporter`."""

from __future__ import annotations

from dmarc_reporter.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
