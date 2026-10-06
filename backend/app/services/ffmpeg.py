"""Reads the FFmpeg and ffprobe versions baked into this image.

Phase 1 only needs the version string for `GET /api/health`. Phase 3 grows
this module into the full wrapper (Section 5.6 of ANALYSIS.md): argument
lists only, never `shell=True`, run at low priority.
"""

from __future__ import annotations

import asyncio
import asyncio.subprocess
import logging
from typing import Literal

_logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 10


async def tool_version(tool: Literal["ffmpeg", "ffprobe"]) -> str | None:
    """Returns the tool's version string (e.g. "7.1.5-0+deb13u1").

    Returns None if the binary is missing, times out, or prints something
    this function does not recognise. Never raises.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            tool,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        _logger.warning("could not start %s", tool)
        return None

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        _logger.warning("%s -version timed out", tool)
        return None

    first_line = stdout.decode("utf-8", errors="replace").splitlines()[:1]
    if not first_line:
        return None

    # Expected shape: "ffmpeg version 7.1.5-0+deb13u1 Copyright (c) 2000-2025 ..."
    parts = first_line[0].split()
    if len(parts) >= 3 and parts[0] == tool and parts[1] == "version":
        return parts[2]
    return None
