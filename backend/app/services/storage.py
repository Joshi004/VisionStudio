"""Where files live (ANALYSIS.md Section 3.5).

Every stored file goes through `Storage`, so a later move to S3 or MinIO
changes one class. The rules:

- names are generated here (`<project_id>/<32 hex>.<ext>`), never taken from
  the client;
- every path is checked to stay inside the media folder;
- the database keeps only the relative path, and the URL is `/media/` plus
  that path (nginx serves it read-only from the same volume);
- stored files are never deleted in iteration 1. Only temporary working files
  in `tmp_dir` are.

An upload is received into `tmp_dir` first, checked by the caller, and then
moved into place with `save`. Temp files are created with `open(..., "xb")`
and never with `tempfile.mkstemp`, which would make them readable by their
owner only, and nginx (another user) must be able to read the finished file.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections.abc import AsyncIterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

import anyio
import anyio.to_thread

from app.core.config import get_config

_logger = logging.getLogger(__name__)

MEDIA_URL_PREFIX = "/media/"
_EXTENSION = re.compile(r"[a-z0-9]{1,5}")
_RELATIVE_PATH = re.compile(r"[0-9]+/[0-9a-f]{32}\.[a-z0-9]{1,5}")


class StorageError(Exception):
    """A path or file name that Storage refuses."""


class TooLargeError(StorageError):
    """An upload that went past its size limit."""


@dataclass(frozen=True)
class TempFile:
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    path: Path
    url: str


def media_url(relative_path: str) -> str:
    return f"{MEDIA_URL_PREFIX}{relative_path}"


class Storage:
    def __init__(self, media_dir: Path, tmp_dir: Path) -> None:
        self._media_dir = media_dir
        self._tmp_dir = tmp_dir

    async def receive(self, chunks: AsyncIterable[bytes], *, max_bytes: int) -> TempFile:
        """Writes an incoming stream to a new temp file, counting bytes and hashing as it goes.

        The limit applies while receiving, so an oversized upload stops early.
        The temp file is removed on any failure.
        """
        path = self._tmp_dir / f"{uuid.uuid4().hex}.upload"
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            async with await anyio.open_file(path, "xb") as file:
                async for chunk in chunks:
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        raise TooLargeError(f"The upload is larger than {max_bytes} bytes.")
                    digest.update(chunk)
                    await file.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return TempFile(path=path, size_bytes=size_bytes, sha256=digest.hexdigest())

    async def save(self, temp: TempFile, project_id: int, ext: str) -> StoredFile:
        """Moves a received file into the media folder under a generated name."""
        if not _EXTENSION.fullmatch(ext):
            raise StorageError(f"Not a valid file extension: {ext!r}")
        relative_path = f"{project_id}/{uuid.uuid4().hex}.{ext}"
        destination = self.get_path(relative_path)
        await anyio.to_thread.run_sync(self._move, temp.path, destination)
        return StoredFile(
            relative_path=relative_path, path=destination, url=media_url(relative_path)
        )

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Same volume, so this is an atomic rename.
        source.replace(destination)

    def get_path(self, relative_path: str) -> Path:
        """The absolute path of a stored file, or StorageError if it is not a valid one."""
        if not _RELATIVE_PATH.fullmatch(relative_path):
            raise StorageError(f"Not a stored file path: {relative_path!r}")
        media_root = self._media_dir.resolve()
        resolved = (media_root / relative_path).resolve()
        if not resolved.is_relative_to(media_root):
            raise StorageError(f"Path leaves the media folder: {relative_path!r}")
        return resolved

    def open(self, relative_path: str) -> BinaryIO:
        """Opens a stored file for reading. Blocking: call it from a thread."""
        return self.get_path(relative_path).open("rb")

    def discard(self, temp: TempFile | Path) -> None:
        """Removes a temp file. Refuses anything outside the temp folder."""
        path = temp.path if isinstance(temp, TempFile) else temp
        if path.resolve().parent != self._tmp_dir.resolve():
            raise StorageError(f"Not a temp file: {path}")
        path.unlink(missing_ok=True)

    def clear_tmp(self) -> None:
        """Creates the temp folder if needed and removes the files in it.

        Temporary working files may be deleted (ITERATION_1_PHASES.md Section 4.2).
        This only ever touches the temp folder, never stored media.
        """
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        removed = 0
        for entry in self._tmp_dir.iterdir():
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
                removed += 1
        if removed:
            _logger.info("removed %d leftover temp file(s)", removed)


@lru_cache
def get_storage() -> Storage:
    config = get_config()
    return Storage(config.media_dir, config.tmp_dir)
