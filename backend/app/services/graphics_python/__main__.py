"""The child process of the Python renderer: `python -m app.services.graphics_python <dest>`.

It reads the render's body (the motion service's `POST /renders` body) as JSON on its standard
input, draws every frame and pipes the raw RGB frames into FFmpeg, which writes `dest`.

Exit codes: 0 done; 2 the template cannot be drawn (the last line of stderr says why); 1 anything
else (the stderr holds the reason). It imports no database and no settings, only Pillow, NumPy and
the pure helpers, so it starts fast and cannot touch the app's state.

A frame is a function of how far each beat has come, so a frame whose beats are all where they
were in the one before is not drawn again: the same bytes are written (still deterministic).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.services.graphics_python.background import build_background
from app.services.graphics_python.encode import ffmpeg_args
from app.services.graphics_python.spec import DrawFailed, read_spec
from app.services.graphics_python.templates import beat_progress, draw_frame

EXIT_DRAW_FAILED = 2
EXIT_FAILED = 1


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m app.services.graphics_python <dest>", file=sys.stderr)
        return EXIT_FAILED
    dest = Path(argv[1])
    body = json.load(sys.stdin)
    try:
        return _render(body, dest)
    except DrawFailed as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DRAW_FAILED


def _render(body: dict, dest: Path) -> int:
    spec = read_spec(body["input"])
    width, height = int(body["width"]), int(body["height"])
    fps, frames = int(body["fps"]), int(body["frames"])
    background = build_background(body["resolved"]["theme"], width, height)

    # The first frame is drawn before FFmpeg starts, so a template that cannot be drawn fails
    # without leaving a file.
    first = draw_frame(background, body, spec, 0).rgb_bytes()

    args = ffmpeg_args(width=width, height=height, fps=fps, encoding=body["encoding"], dest=dest)
    # FFmpeg's own stderr goes to ours, where the parent reads it.
    ffmpeg = subprocess.Popen(args, stdin=subprocess.PIPE)
    assert ffmpeg.stdin is not None
    try:
        last_progress = beat_progress(body, 0)
        picture = first
        for frame in range(frames):
            progress = beat_progress(body, frame)
            if frame > 0 and progress != last_progress:
                picture = draw_frame(background, body, spec, frame).rgb_bytes()
                last_progress = progress
            ffmpeg.stdin.write(picture)
        ffmpeg.stdin.close()
    except BrokenPipeError:
        print("FFmpeg stopped before the last frame was written.", file=sys.stderr)
        ffmpeg.wait()
        return EXIT_FAILED
    except BaseException:
        ffmpeg.kill()
        ffmpeg.wait()
        raise
    code = ffmpeg.wait()
    if code != 0:
        print(f"FFmpeg stopped with code {code}.", file=sys.stderr)
        return EXIT_FAILED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
