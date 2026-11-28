"""`clip`: download the chosen seconds of a YouTube video, muted, and make the piece (§4.7 step 3).

Only `use` plus `CLIP_PAD_S` on each side is downloaded, at up to 1080 pixels on the shorter side,
video only, re-encoded to H.264 so that the file starts on the first frame asked for. The cut
times are found again on this file and its strip of frames is written, so the agent's last look
and the review see what the app will draw. Times in the result are seconds of the source video.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from typing import Final

from ..rounds import Refused, sha256_of
from ..youtube import format_time_tenths, licence_of, upload_date_of, watch_url
from . import (
    CLIP_MAX_S,
    CLIP_MIN_S,
    CLIP_PAD_S,
    DURATION_TOLERANCE_S,
    LOW_RES_SHORT_SIDE,
    MAX_CLIP_BYTES,
    MAX_SHORT_SIDE,
)
from .frames import VideoFacts, find_cuts, probe, strip_layout, write_strip
from .rounds import Captured, Described, FootageRound, file_names, piece_entry
from .ytdl import SCALE_CAP, download_range, open_video, text_of

CLIP_CRF: Final = 18
# A time given in tenths is kept to a thousandth, which is finer than any frame.
_EPS: Final = 1e-6
VIDEO_CODEC: Final = "h264"
PIXEL_FORMAT: Final = "yuv420p"


def media_problems(facts: VideoFacts, expected_s: float) -> list[str]:
    """Why a downloaded window is not what the tool makes (§4.8 check 3), or an empty list."""
    problems: list[str] = []
    if facts.video_streams != 1:
        problems.append(f"it needs exactly one video stream (it has {facts.video_streams})")
    if facts.audio_streams:
        problems.append("it has an audio stream, but footage is always muted")
    if facts.video_streams == 1:
        if facts.codec != VIDEO_CODEC:
            problems.append(f"the video codec is {facts.codec!r}, not {VIDEO_CODEC}")
        if facts.pix_fmt != PIXEL_FORMAT:
            problems.append(f"the pixel format is {facts.pix_fmt!r}, not {PIXEL_FORMAT}")
        if facts.width <= 0 or facts.height <= 0:
            problems.append("it has no picture size")
        elif facts.short_side > MAX_SHORT_SIDE:
            problems.append(
                f"its shorter side is {facts.short_side} px, the limit is {MAX_SHORT_SIDE}"
            )
        if facts.fps <= 0:
            problems.append("it has no frame rate")
    if abs(facts.duration_s - expected_s) > DURATION_TOLERANCE_S:
        problems.append(
            f"it lasts {facts.duration_s:.2f} s, but the window is {expected_s:.2f} s "
            f"(more than {DURATION_TOLERANCE_S} s apart)"
        )
    return problems


def check_use(use_from: float, use_to: float, moment: float | None) -> None:
    """The `use` and the `moment` asked for (§4.6): 2 to 15 s, and the moment inside it."""
    length = use_to - use_from
    if use_from < 0 or use_to <= use_from:
        raise Refused("--to must be later than --from, and both must be zero or more.")
    if length < CLIP_MIN_S - _EPS:
        raise Refused(
            f"The part to use lasts {length:.1f} s. It must last at least {CLIP_MIN_S:.0f} s."
        )
    if length > CLIP_MAX_S + _EPS:
        raise Refused(
            f"The part to use lasts {length:.1f} s. It may last at most {CLIP_MAX_S:.0f} s: "
            "choose the shot that shows what the note asks."
        )
    if moment is not None and not use_from - _EPS <= moment <= use_to + _EPS:
        raise Refused(
            f"--moment {format_time_tenths(moment)} is outside the part to use "
            f"({format_time_tenths(use_from)} to {format_time_tenths(use_to)})."
        )


def capture_clip(
    rnd: FootageRound,
    *,
    mark_id: str,
    piece_id: str,
    url: str,
    use_from: float,
    use_to: float,
    moment: float | None,
    described: Described,
) -> Captured:
    """Download the part of the video to use, and make the entry of a piece of kind `video`."""
    rnd.mark(mark_id)
    rnd.check_room(mark_id, piece_id)
    check_use(use_from, use_to, moment)

    with open_video(url, command="clip") as video:
        if use_to > video.duration_s + _EPS:
            raise Refused(
                f"--to {format_time_tenths(use_to)} is past the end of the video, which lasts "
                f"{format_time_tenths(video.duration_s)}."
            )
        use_to = min(use_to, video.duration_s)
        if use_to - use_from < CLIP_MIN_S - _EPS:
            raise Refused(
                "The part to use is shorter than "
                f"{CLIP_MIN_S:.0f} s once it is cut at the end of the video."
            )
        window_start = round(max(0.0, use_from - CLIP_PAD_S), 3)
        window_end = round(min(video.duration_s, use_to + CLIP_PAD_S), 3)
        expected_s = window_end - window_start

        with tempfile.TemporaryDirectory(prefix="visio-clip-") as temp:
            work = Path(temp)
            media = download_range(
                video,
                work,
                window_start,
                window_end,
                short_side=MAX_SHORT_SIDE,
                crf=CLIP_CRF,
                scale=SCALE_CAP,
            )
            facts = probe(media)
            problems = media_problems(facts, expected_s)
            if problems:
                raise Refused("The downloaded part is not usable: " + "; ".join(problems) + ".")
            size = media.stat().st_size
            if size > MAX_CLIP_BYTES:
                raise Refused(
                    f"The part is larger than {MAX_CLIP_BYTES // (1024 * 1024)} MB "
                    f"({size} bytes). Use a shorter part."
                )
            layout = strip_layout(facts.duration_s)
            strip_path = work / "strip.jpg"
            write_strip(media, strip_path, layout)
            cuts = [round(window_start + cut, 3) for cut in find_cuts(media, facts.duration_s)]
            video_bytes = media.read_bytes()
            strip_bytes = strip_path.read_bytes()

        names = file_names(piece_id)
        files = {names["video"]: video_bytes, names["strip"]: strip_bytes}
        info = video.info
        capture = {
            "video_id": video.video_id,
            "channel": text_of(info.get("channel") or info.get("uploader")),
            "channel_id": text_of(info.get("channel_id")),
            "upload_date": upload_date_of(info),
            "youtube_licence": licence_of(info),
            "duration_s": video.duration_s,
            "window": {"start_s": window_start, "end_s": window_end},
            "use": {"start_s": round(use_from, 3), "end_s": round(use_to, 3)},
            "moment_s": None if moment is None else round(moment, 3),
            "cuts": cuts,
            "media": names["video"],
            "strip": names["strip"],
            "strip_every_s": layout.every_s,
            "strip_columns": layout.columns,
            "strip_rows": layout.rows,
            "strip_tile_px": [layout.tile_w, layout.tile_h],
            "strip_frames": layout.frames,
            "video_px": [facts.width, facts.height],
            "fps": round(facts.fps, 3),
            "sha256": {name: sha256_of(data) for name, data in files.items()},
        }
        upload_date = capture["upload_date"]
        described = dataclasses.replace(described, published=described.published or upload_date)
        entry = piece_entry(
            piece_id=piece_id,
            kind="video",
            described=described,
            url=url,
            final_url=watch_url(video.video_id),
            title=text_of(info.get("title"), 300),
            capture=capture,
        )

        notes = [
            f"Captured {format_time_tenths(use_from)} to {format_time_tenths(use_to)} "
            f"({use_to - use_from:.1f} s) of {video.video_id}, with {window_start:g} to "
            f"{window_end:g} s downloaded ({expected_s:.1f} s), {facts.width}x{facts.height}, "
            f"{facts.fps:.2f} fps, {size / (1024 * 1024):.1f} MB, no sound.",
            f"Licence: {capture['youtube_licence']}. Channel: {capture['channel']!r}. "
            f"Upload date: {upload_date}.",
        ]
        inside = [cut for cut in cuts if use_from < cut < use_to]
        notes.append(
            "Cuts inside the part to use: "
            + (", ".join(format_time_tenths(cut) for cut in inside) or "none")
            + ". The app never shows a cut in the first or last 0.5 s of the clip and moves "
            "the start to avoid one."
        )
        notes.append(
            f"Look at the strip ({names['strip']}, a frame every {layout.every_s} s) for a "
            "logo, a ticker, an anchor or large text, and check that it shows what the note asks."
        )
        if facts.short_side < LOW_RES_SHORT_SIDE:
            notes.append(
                f"WARNING: the video is small ({facts.width}x{facts.height}); it will look soft "
                "full screen."
            )
        channel = (capture["channel"] or "").casefold()
        publisher = described.publisher.casefold()
        if channel and publisher not in channel and channel not in publisher:
            notes.append(
                f"WARNING: the publisher {described.publisher!r} is not the YouTube channel "
                f"{capture['channel']!r}. The review shows this."
            )
        if moment is None:
            notes.append(
                "No --moment was given, so the clip will start at the start of the part to use."
            )
        if described.published and upload_date and described.published > upload_date:
            notes.append(
                f"WARNING: --published {described.published} is later than the upload date "
                f"{upload_date}."
            )
        for warning in video.log.warnings:
            notes.append(f"yt-dlp: {warning[:300]}")
        return Captured(entry=entry, files=files, notes=notes)
