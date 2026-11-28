"""yt-dlp for the footage commands: open one video, and download a range of it, muted.

The options are the evidence `video` command's (`video._options`): one video, no cookies, no
account, no cache, no remote code. Only a YouTube address is taken, and the tool hands yt-dlp the
address it builds itself (`watch_url`), never the one it was given.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..netguard import check_url
from ..rounds import Refused
from ..video import BLOCKED_ADVICE, _Log, _options, _refusal_for
from ..youtube import video_id_from_url, watch_url
from . import MAX_SHORT_SIDE

# The scale of a stored video (the app's `footage_frames.prepare_args`): the shorter side is at
# most `MAX_SHORT_SIDE` and the shape is kept. `-2` makes a size `yuv420p` can take.
SCALE_CAP: Final = (
    f"scale=w='if(gte(iw,ih),-2,min(iw,{MAX_SHORT_SIDE}))'"
    f":h='if(gte(iw,ih),min(ih,{MAX_SHORT_SIDE}),-2)',setsar=1,format=yuv420p"
)


@dataclass(frozen=True)
class OpenVideo:
    ydl: Any  # the open YoutubeDL, for reading captions and previews with its own session
    info: dict[str, Any]
    video_id: str
    address: str
    duration_s: float
    log: _Log


def need_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise Refused(
                f"{tool} is not installed. The owner installs it with `brew install ffmpeg`."
            )


def text_of(value: object, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


@contextmanager
def open_video(url: str, *, command: str) -> Iterator[OpenVideo]:
    """Ask YouTube about one video (no download). Refuses a live stream or premiere."""
    video_id = video_id_from_url(url, command=command, other_command="the page command")
    need_ffmpeg()
    address = watch_url(video_id)
    check_url(address)

    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, YoutubeDLError

    log = _Log()
    with YoutubeDL({**_options(log), "skip_download": True}) as ydl:
        try:
            info = ydl.extract_info(address, download=False)
        except (DownloadError, YoutubeDLError) as error:
            raise _refusal_for(error) from error
        if not isinstance(info, dict) or info.get("id") != video_id:
            raise Refused("YouTube did not answer with the video that was asked for.")
        if info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
            raise Refused(
                f"The video is a live stream or a premiere that is not finished. {BLOCKED_ADVICE}"
            )
        duration = info.get("duration")
        if not isinstance(duration, int | float) or isinstance(duration, bool) or duration <= 0:
            raise Refused("YouTube gave no length for the video, so a range cannot be chosen.")
        yield OpenVideo(ydl, info, video_id, address, float(duration), log)


def download_range(
    video: OpenVideo,
    folder: Path,
    start_s: float,
    end_s: float,
    *,
    short_side: int,
    crf: int,
    scale: str | None,
) -> Path:
    """Download only `[start_s, end_s]` of the video into `folder` as `range.mp4`: video only, no
    sound, re-encoded to H.264 so that it starts on the first frame asked for (a section download
    otherwise starts on the previous keyframe). The shorter side of the picture asked for is
    `short_side` or the nearest below it. Returns the file."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, YoutubeDLError, download_range_func

    output_args = ["-an", "-sn", "-dn", "-map_metadata", "-1"]
    if scale is not None:
        output_args += ["-vf", scale]
    output_args += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-fps_mode", "cfr", "-movflags", "+faststart",
    ]  # fmt: skip
    target = folder / "range.mp4"
    options = {
        **_options(video.log),
        "format": "bv*/b",
        "format_sort": [f"res:{short_side}"],
        "download_ranges": download_range_func(None, [(start_s, end_s)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(target),
        "external_downloader_args": {"ffmpeg_o": output_args},
    }
    try:
        with YoutubeDL(options) as ydl:
            ydl.download([video.address])
    except (DownloadError, YoutubeDLError) as error:
        raise _refusal_for(error) from error
    if not target.is_file():
        raise Refused("yt-dlp finished but made no mp4 file. Try again, or report it as blocked.")
    return target
