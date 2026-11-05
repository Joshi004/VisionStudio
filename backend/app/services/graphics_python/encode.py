"""How the drawn frames become the MP4: the FFmpeg command that reads raw RGB frames on a pipe.

The colour conversion is the one Remotion 4.0.540 uses for `colorSpace: "bt709"` (see
`@remotion/renderer/dist/ffmpeg-args.js`), so the same RGB gives the same YUV in both engines:
BT.709 tags, limited range, and a `zscale` from RGB to BT.709. The codec, CRF, preset and pixel
format come from `graphics_render.ENCODING` (G-4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

_ENCODERS: Final = {"h264": "libx264"}
# Remotion's own filter for bt709, copied as it is.
_ZSCALE: Final = (
    "zscale=matrix=709:range=limited:primariesin=709:primaries=709:transferin=709:transfer=709"
)
# The time base Remotion gives its files.
_TIMESCALE: Final = "90000"


def ffmpeg_args(
    *, width: int, height: int, fps: int, encoding: dict[str, Any], dest: Path
) -> list[str]:
    """The arguments of an FFmpeg that reads `width` x `height` RGB frames from its standard
    input and writes `dest` with no audio. Raises ValueError for an encoding it does not know.
    """
    encoder = _ENCODERS.get(str(encoding.get("codec")))
    if encoder is None or encoding.get("color_space") != "bt709":
        raise ValueError(f"The Python renderer cannot encode {encoding!r}.")
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        encoder,
        "-colorspace:v",
        "bt709",
        "-color_primaries:v",
        "bt709",
        "-color_trc:v",
        "bt709",
        "-color_range",
        "tv",
        "-vf",
        _ZSCALE,
        "-pix_fmt",
        str(encoding["pixel_format"]),
        "-preset",
        str(encoding["preset"]),
        "-video_track_timescale",
        _TIMESCALE,
        "-crf",
        str(encoding["crf"]),
        "-r",
        str(fps),
        str(dest),
    ]
