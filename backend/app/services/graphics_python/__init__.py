"""The Python renderer of the template engine `python_templates` (GFX-008).

It draws the same five templates as the Remotion renderer (GFX-007) from the same template spec,
the same resolved brief and the same layout (§4.5.1), so the two videos can be compared on equal
terms. Each module here is a port of the file of the same name in `motion/src/templates/`.

**How it runs.** Drawing with Pillow is CPU-bound Python, so it runs in a child process
(`python -m app.services.graphics_python`, see `__main__.py`), not in a thread: it would hold the
interpreter's lock and slow the API. The child pipes raw frames into FFmpeg. `render` below is the
parent's side: it starts the child, waits with `asyncio` (the event loop stays free), and stops it
at the time limit or when the job is cancelled.

`render` is `graphics_render.python_renderer`.
"""

from __future__ import annotations

import asyncio
import asyncio.subprocess
import json
import sys
from pathlib import Path
from typing import Any, Final

from app.services.graphics_render import RENDER_TIME_LIMIT_S, PythonRenderFailed

# The child exit code that means "the template cannot be drawn" (see `__main__.py`).
EXIT_DRAW_FAILED: Final = 2
# `nice` level of the child, as the other renders of the backend (`services/ffmpeg.py`).
_NICE_LEVEL: Final = "10"
_ERROR_TAIL_CHARS: Final = 500
# The directory that holds the `app` package: the child's working directory.
_BACKEND_DIR: Final = Path(__file__).resolve().parents[3]


async def render(body: dict[str, Any], dest: Path) -> None:
    """Draws the render of `body` into the new file `dest` (an H.264 MP4, no audio).

    Raises PythonRenderFailed: with the child's own words when the template cannot be drawn,
    with a general message for any other failure, and when the time limit passes.
    """
    limit_s = float(body.get("time_limit_s") or RENDER_TIME_LIMIT_S)
    try:
        process = await asyncio.create_subprocess_exec(
            "nice",
            "-n",
            _NICE_LEVEL,
            sys.executable,
            "-m",
            "app.services.graphics_python",
            str(dest),
            cwd=_BACKEND_DIR,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise PythonRenderFailed("The Python renderer could not be started.") from exc

    try:
        _stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(body).encode()), timeout=limit_s
        )
    except (TimeoutError, asyncio.CancelledError) as exc:
        process.kill()
        await process.wait()
        if isinstance(exc, TimeoutError):
            raise PythonRenderFailed(
                f"The render ran past its time limit of {limit_s:g} s and was stopped."
            ) from None
        raise

    if process.returncode == 0:
        return
    text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode == EXIT_DRAW_FAILED and text:
        raise PythonRenderFailed(text.splitlines()[-1])
    raise PythonRenderFailed(
        f"The Python renderer failed: {text[-_ERROR_TAIL_CHARS:] or 'no error text'}"
    )
