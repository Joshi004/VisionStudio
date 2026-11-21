"""Capture of a quote in a YouTube video (SB-003).

The tool reads the video's English captions, finds the quote in them, and downloads only a padded
window around it with yt-dlp, re-encoded so that it starts on the first frame asked for (a
section download otherwise starts on the previous keyframe, which can be 10 s early). No cookies,
no login and no account are used, and the remote challenge solver of yt-dlp is not allowed.
Searching YouTube is the agent's job; this module only opens the address it is given.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from . import (
    MAX_CAPTIONS_BYTES,
    MAX_VIDEO_BYTES,
    MAX_VIDEO_HEIGHT,
    MAX_WINDOW_S,
    VIDEO_DURATION_TOLERANCE_S,
    VIDEO_PAD_S,
)
from .netguard import check_url
from .rounds import Captured, Described, Refused, Round, evidence_entry, file_names, sha256_of
from .web import check_quote_length
from .youtube import (
    MIN_QUOTE_WORDS,
    Captions,
    find_quote_in_captions,
    format_time,
    licence_of,
    nearest_caption_lines,
    parse_json3,
    parse_time,
    pick_caption_track,
    quote_word_count,
    upload_date_of,
    video_id_from_url,
    watch_url,
)

# The most seconds a quote may run: the window is the quote plus the padding on both sides.
MAX_QUOTE_S: Final = MAX_WINDOW_S - 2 * VIDEO_PAD_S
# A sound bite is 3 to 15 s (§4.7). The review enforces it; the tool only says so early.
LONG_QUOTE_S: Final = 15.0
PROBE_TIMEOUT_S: Final = 60

FORMAT: Final = f"bv*[height<={MAX_VIDEO_HEIGHT}]+ba/b[height<={MAX_VIDEO_HEIGHT}]"
# Passed to the ffmpeg that makes the window (`external_downloader_args`, the output side).
FFMPEG_OUTPUT_ARGS: Final = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
]  # fmt: skip
VIDEO_CODEC: Final = "h264"
AUDIO_CODEC: Final = "aac"

BLOCKED_ADVICE: Final = (
    "Do not try to get around it: report the claim as blocked (report --status blocked) and "
    "list this as an --attempt."
)
# A quote cut short by the end of the video must still last this long.
MIN_QUOTE_KEPT_S: Final = 0.5


# --- ffprobe -------------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoProbe:
    duration_s: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    video_streams: int
    audio_streams: int


def probe_video(path: Path) -> VideoProbe:
    """What ffprobe says about a media file. Refuses when it cannot be read."""
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
             str(path)],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refused(f"ffprobe could not read {path.name}: {error}") from error
    if done.returncode != 0:
        raise Refused(f"{path.name} is not a media file that ffprobe can read.")
    try:
        data = json.loads(done.stdout)
        streams = data.get("streams") or []
        video = [s for s in streams if s.get("codec_type") == "video"]
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        duration = float(data["format"]["duration"])
        first = video[0] if video else {}
        return VideoProbe(
            duration_s=duration,
            width=int(first.get("width") or 0),
            height=int(first.get("height") or 0),
            video_codec=str(first.get("codec_name") or ""),
            audio_codec=str((audio[0] if audio else {}).get("codec_name") or ""),
            video_streams=len(video),
            audio_streams=len(audio),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise Refused(f"ffprobe's answer for {path.name} cannot be read.") from error


def media_problems(probe: VideoProbe, expected_s: float) -> list[str]:
    """Why a window's media is not what the tool makes, or an empty list."""
    problems: list[str] = []
    if probe.video_streams != 1 or probe.audio_streams != 1:
        problems.append(
            "it needs exactly one video and one audio stream "
            f"(it has {probe.video_streams} and {probe.audio_streams})"
        )
    if probe.video_streams == 1 and probe.video_codec != VIDEO_CODEC:
        problems.append(f"the video codec is {probe.video_codec!r}, not {VIDEO_CODEC}")
    if probe.audio_streams == 1 and probe.audio_codec != AUDIO_CODEC:
        problems.append(f"the audio codec is {probe.audio_codec!r}, not {AUDIO_CODEC}")
    if abs(probe.duration_s - expected_s) > VIDEO_DURATION_TOLERANCE_S:
        problems.append(
            f"it lasts {probe.duration_s:.2f} s, but the window is {expected_s:.2f} s "
            f"(more than {VIDEO_DURATION_TOLERANCE_S} s apart)"
        )
    if probe.width <= 0 or probe.height <= 0:
        problems.append("it has no picture size")
    elif probe.height > MAX_VIDEO_HEIGHT:
        problems.append(f"it is {probe.height} px high, the limit is {MAX_VIDEO_HEIGHT}")
    return problems


# --- yt-dlp --------------------------------------------------------------------------------


class _Log:
    """yt-dlp's messages. Only its warnings are kept, to tell the agent."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        text = " ".join(message.removeprefix("WARNING:").split())
        if text and text not in self.warnings:
            self.warnings.append(text)


def _options(log: _Log) -> dict[str, Any]:
    """The options of every yt-dlp call: one video, no account, no remote code, no cache."""
    return {
        "logger": log,
        # `quiet` also tells the ffmpeg of a section download to say nothing.
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        "cookiefile": None,
        "cachedir": False,
        "socket_timeout": 30,
        "remote_components": [],
    }


def _refusal_for(error: Exception) -> Refused:
    """A plain sentence for what YouTube or yt-dlp said."""
    raw = " ".join(str(error).split())
    text = raw.casefold()
    if "sign in to confirm" in text or "not a bot" in text:
        reason = "YouTube asked for a sign-in to prove this is not a bot."
    elif "confirm your age" in text or "age-restricted" in text or "age restricted" in text:
        reason = "The video is age-restricted and needs a sign-in."
    elif "private video" in text:
        reason = "The video is private."
    elif "members-only" in text or "members only" in text or "join this channel" in text:
        reason = "The video is for channel members only."
    elif "live event will begin" in text or "premieres in" in text:
        reason = "The video is a live event or premiere that has not happened yet."
    elif any(
        part in text
        for part in (
            "unavailable",
            "no longer available",
            "has been removed",
            "account associated",
            "terminated",
            "does not exist",
            "not available",
        )
    ):
        reason = "The video is unavailable (removed, or not shown in this country)."
    else:
        short = raw.removeprefix("ERROR:").strip()[:300]
        return Refused(
            f"yt-dlp could not get the video: {short}\nIf YouTube is refusing it: "
            f"{BLOCKED_ADVICE}\nIf it looks like a fault of yt-dlp itself (YouTube changes "
            "often), tell the owner: it is updated with `uv lock --upgrade-package yt-dlp`."
        )
    return Refused(f"{reason} {BLOCKED_ADVICE}")


def _read_captions(ydl: Any, address: str) -> dict[str, Any]:
    from yt_dlp.utils import YoutubeDLError

    try:
        response = ydl.urlopen(address)
        data = response.read(MAX_CAPTIONS_BYTES + 1)
    except YoutubeDLError as error:
        raise Refused(f"The captions could not be downloaded: {error}") from error
    if len(data) > MAX_CAPTIONS_BYTES:
        raise Refused("The caption track is too large to keep.")
    try:
        track = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise Refused("The caption track is not readable (not json3).") from error
    if not isinstance(track, dict):
        raise Refused("The caption track is not readable (not json3).")
    return track


def _window_part(track: dict[str, Any], start_s: float, end_s: float) -> dict[str, Any]:
    """The track with only the events that overlap the window. The events are not changed."""
    kept = []
    for event in track.get("events") or []:
        if not isinstance(event, dict) or not isinstance(event.get("tStartMs"), int | float):
            continue
        begins = event["tStartMs"] / 1000
        duration = event.get("dDurationMs")
        ends = begins + (duration / 1000 if isinstance(duration, int | float) else 0)
        if begins < end_s and ends >= start_s:
            kept.append(event)
    return {**{key: value for key, value in track.items() if key != "events"}, "events": kept}


def window_text(captions: Captions) -> str:
    """The plain text of a window's caption lines, one per line."""
    return "\n".join(line.text for line in captions.lines) + "\n"


# --- The capture ---------------------------------------------------------------------------


def capture_video(
    rnd: Round,
    *,
    claim_id: str,
    evidence_id: str,
    url: str,
    quote: str,
    near: str | None,
    as_context: bool,
    described: Described,
) -> Captured:
    """Find `quote` in the captions of the video at `url`, and download the window around it.
    Refuses clearly when anything is wrong.
    """
    claim = rnd.claim(claim_id)
    if claim.get("want", "evidence") != "soundbite" and not as_context:
        raise Refused(
            f"Claim {claim_id} is not a sound bite claim, so no video is captured for it. "
            "If the video is only context for the claim, add --as-context."
        )
    rnd.check_room(claim_id, evidence_id)
    wanted = check_quote_length(quote)
    if quote_word_count(wanted) < MIN_QUOTE_WORDS:
        raise Refused(
            f"The quote is too short to find in captions (at least {MIN_QUOTE_WORDS} words)."
        )
    video_id = video_id_from_url(url)
    near_s = parse_time(near) if near else None
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise Refused(
                f"{tool} is not installed. The owner installs it with `brew install ffmpeg`."
            )
    address = watch_url(video_id)
    check_url(address)

    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, YoutubeDLError

    log = _Log()
    notes: list[str] = []
    try:
        with YoutubeDL({**_options(log), "skip_download": True}) as ydl:
            info = ydl.extract_info(address, download=False)
            if not isinstance(info, dict) or info.get("id") != video_id:
                raise Refused("YouTube did not answer with the video that was asked for.")
            source, language, raw_track = _caption_track(ydl, info)
    except (DownloadError, YoutubeDLError) as error:
        raise _refusal_for(error) from error

    if info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise Refused(
            f"The video is a live stream or a premiere that is not finished. {BLOCKED_ADVICE}"
        )
    duration = info.get("duration")
    if not isinstance(duration, int | float) or duration <= 0:
        raise Refused("YouTube gave no length for the video, so a window cannot be chosen.")

    captions = parse_json3(raw_track)
    if not captions.words:
        raise Refused("The caption track has no words.")
    matches = find_quote_in_captions(captions, wanted, near_s)
    if not matches:
        lines = [
            "The quote is not in the captions (a loose match is used: most of its words, in order)."
        ]
        near_lines = nearest_caption_lines(captions, wanted)
        if near_lines:
            lines.append("Nearest caption text, with its time, to choose the exact words from:")
            lines.extend(f"  {number}. {text}" for number, text in enumerate(near_lines, start=1))
        else:
            lines.append("No similar caption text was found.")
        raise Refused("\n".join(lines))
    match = matches[0]
    if len(matches) > 1:
        times = ", ".join(format_time(item.start_s) for item in matches[:5])
        how = "the closest to --near" if near_s is not None else "the best match"
        notes.append(
            f"The quote is in the captions {len(matches)} times (at {times}). "
            f"Used {how}, at {format_time(match.start_s)}. Pass --near to choose."
        )
    quote_end = min(match.end_s, float(duration))
    quote_s = quote_end - match.start_s
    if quote_s < MIN_QUOTE_KEPT_S:
        raise Refused("The captions put the quote at the very end of the video: no window.")
    if quote_s > MAX_QUOTE_S:
        raise Refused(
            f"The quote runs for about {quote_s:.0f} s in the captions, but a window holds at "
            f"most {MAX_QUOTE_S:.0f} s of quote. Choose a shorter quote."
        )
    if quote_s > LONG_QUOTE_S:
        notes.append(
            f"The quote runs for about {quote_s:.0f} s. A sound bite is 3 to 15 s: the review "
            "will not accept a longer one."
        )

    window_start = round(max(0.0, match.start_s - VIDEO_PAD_S), 3)
    window_end = round(min(float(duration), quote_end + VIDEO_PAD_S), 3)
    expected_s = window_end - window_start

    with tempfile.TemporaryDirectory(prefix="visio-video-") as folder:
        clip = _download_window(address, Path(folder), window_start, window_end, log)
        probe = probe_video(clip)
        problems = media_problems(probe, expected_s)
        if problems:
            raise Refused("The downloaded window is not usable: " + "; ".join(problems) + ".")
        size = clip.stat().st_size
        if size > MAX_VIDEO_BYTES:
            raise Refused(
                f"The window is larger than {MAX_VIDEO_BYTES // (1024 * 1024)} MB ({size} bytes)."
            )
        media = clip.read_bytes()

    part = _window_part(raw_track, window_start, window_end)
    part_captions = parse_json3(part)
    captions_bytes = json.dumps(part, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(captions_bytes) > MAX_CAPTIONS_BYTES:
        raise Refused("The window's captions are too large to keep.")
    if not find_quote_in_captions(part_captions, match.text, match.start_s):
        raise Refused("Internal error: the quote is not in the captions of the window.")

    names = file_names(evidence_id)
    files = {
        names["media"]: media,
        names["captions"]: captions_bytes,
        names["text_copy"]: window_text(part_captions).encode("utf-8"),
    }
    capture = {
        "video_id": video_id,
        "channel": _text(info.get("channel") or info.get("uploader")),
        "channel_id": _text(info.get("channel_id")),
        "upload_date": upload_date_of(info),
        "licence": licence_of(info),
        "duration_s": float(duration),
        "window": {"start_s": window_start, "end_s": window_end},
        "quote_at_s": {"start": round(match.start_s, 3), "end": round(quote_end, 3)},
        "media": names["media"],
        "captions": names["captions"],
        "context_text": names["text_copy"],
        "video_px": [probe.width, probe.height],
        "sha256": {name: sha256_of(data) for name, data in files.items()},
    }

    notes.insert(
        0,
        f"Found the quote at {format_time(match.start_s)} ({match.share:.0%} of its words, "
        f"{source} captions {language}). Window {format_time(window_start)} to "
        f"{format_time(window_end)} ({expected_s:.0f} s), {probe.width}x{probe.height}, "
        f"{len(media) / (1024 * 1024):.1f} MB.",
    )
    notes.append(f"Licence: {capture['licence']}. Upload date: {capture['upload_date']}.")
    if source == "automatic":
        notes.append(
            "The captions are YouTube's automatic ones: names and numbers may be wrong. The app "
            "transcribes the clip itself on import."
        )
    upload_date = capture["upload_date"]
    if described.published and upload_date and described.published > upload_date:
        notes.append(
            f"WARNING: --recorded {described.published} is later than the upload date "
            f"{upload_date}. Check the recording date."
        )
    if not described.published:
        notes.append(
            "No --recorded date was given. The review needs the recording date, not the upload "
            "date: say how you know it in --what-it-says."
        )
    for warning in log.warnings:
        notes.append(f"yt-dlp: {warning[:300]}")

    entry = evidence_entry(
        evidence_id=evidence_id,
        kind="video",
        described=described,
        url=url,
        final_url=address,
        title=_text(info.get("title"), 300),
        quote=match.text,
        capture=capture,
    )
    return Captured(entry=entry, files=files, notes=notes)


def _text(value: object, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


def _caption_track(ydl: Any, info: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """`(source, language, track)`: the English captions of the video, downloaded."""
    picked = pick_caption_track(info)
    if picked is None:
        raise Refused(
            "The video has no English captions that the tool may use (a machine translation "
            "does not count), so the quote cannot be found in it. Choose another video, or "
            "report the claim as not_found with this as an --attempt."
        )
    source, language, address = picked
    return source, language, _read_captions(ydl, address)


def _download_window(address: str, folder: Path, start_s: float, end_s: float, log: _Log) -> Path:
    """Download `[start_s, end_s]` into `folder` and return the file."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, YoutubeDLError, download_range_func

    options = {
        **_options(log),
        "format": FORMAT,
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start_s, end_s)]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(folder / "clip.%(ext)s"),
        "external_downloader_args": {"ffmpeg_o": FFMPEG_OUTPUT_ARGS},
    }
    try:
        with YoutubeDL(options) as ydl:
            ydl.download([address])
    except (DownloadError, YoutubeDLError) as error:
        raise _refusal_for(error) from error
    clip = folder / "clip.mp4"
    if not clip.is_file():
        raise Refused("yt-dlp finished but made no mp4 file. Try again, or report it as blocked.")
    return clip
