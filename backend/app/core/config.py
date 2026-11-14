"""Application configuration, read from environment variables.

Section 3.1 of ANALYSIS.md describes two configuration layers: settings
saved in the UI (Phase 2 adds the database-backed registry for those), and
environment variables for secrets and first-run defaults. This module is
the second layer only. Phase 1 reads no secrets; it only needs to know
where the data volume is mounted and how verbose to log.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str) -> str:
    """Reads an environment variable, treating a blank value as unset."""
    value = os.environ.get(name, "")
    return value if value.strip() else default


def env_value(name: str) -> str | None:
    """Reads an environment variable at the moment of use (ANALYSIS.md Section 3.1).

    Returns None when the variable is unset or blank, so a blank `.env` line
    never counts as a value. Unlike `get_config()`, nothing is cached.
    """
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class AppConfig:
    """Resolved configuration for this process. Construct via `get_config()`."""

    data_dir: Path
    # Where `media/` and `tmp/` live. The same as `data_dir` unless FILES_DIR is set (STOR-001),
    # which puts them in a folder on the host. The database always stays under `data_dir`.
    files_dir: Path
    log_level: str

    @property
    def files_dir_is_separate(self) -> bool:
        """True when the files are in their own folder, not in the data volume."""
        return self.files_dir != self.data_dir

    @property
    def db_path(self) -> Path:
        """The SQLite file. Alongside it SQLite also keeps `-wal` and `-shm` files."""
        return self.data_dir / "app.db"

    @property
    def media_dir(self) -> Path:
        """Uploaded and generated media, served read-only by nginx at `/media/`."""
        return self.files_dir / "media"

    @property
    def tmp_dir(self) -> Path:
        """Working files for uploads in progress. On the same mount as `media_dir` (both are
        under `files_dir`), so a finished file is moved into place with an atomic rename. Not
        served by nginx.
        """
        return self.files_dir / "tmp"

    @property
    def async_database_url(self) -> str:
        """Used by the app itself: async SQLAlchemy with the aiosqlite driver."""
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def sync_database_url(self) -> str:
        """Used by Alembic only, which runs synchronously."""
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_config() -> AppConfig:
    """Returns the process-wide configuration, read once and cached.

    Safe to call repeatedly: environment variables do not change while this
    process runs.
    """
    data_dir = Path(_env("DATA_DIR", "/data"))
    return AppConfig(
        data_dir=data_dir,
        files_dir=Path(_env("FILES_DIR", str(data_dir))),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
    )
