"""`scan` and `scan --fine`: finding a moment in a YouTube video by its picture (§4.7).

`scan` downloads none of the video. It writes the video's facts, its English captions as plain
text and YouTube's own preview pictures (the ones shown over the progress bar) laid out as contact
sheets with each frame's time stamped on it. `scan --fine` downloads only a short range at low
resolution and writes sheets of frames half a second apart, and the exact cut times in it.

Everything is written to `results/<mark>/scans/<video_id>/`. The agent reads it; it is never part
of a result and the import never reads it.
"""

from __future__ import annotations

import io
import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from PIL import Image, UnidentifiedImageError

from ..netguard import check_url
from ..rounds import Refused, _unlink_own, _write_atomic
from ..video import _caption_track
from ..youtube import (
    format_time,
    format_time_tenths,
    licence_of,
    parse_json3,
    upload_date_of,
)
from . import (
    CUT_SCENE_THRESHOLD,
    DESCRIPTION_CHARS,
    FINE_SHORT_SIDE,
    MAX_CAPTION_LINES_BYTES,
    MAX_FINE_BYTES,
    MAX_FINE_S,
    MAX_PREVIEW_PART_BYTES,
    MAX_SCAN_BYTES,
    MAX_SCAN_S,
    STRIP_EVERY_S,
)
from .frames import Sheet, find_cuts, probe, sample_pictures, write_sheets
from .rounds import FootageRound
from .ytdl import OpenVideo, download_range, open_video, text_of

_STORYBOARD_ID: Final = re.compile(r"^sb\d$")
MIN_FINE_S: Final = 1.0
FINE_CRF: Final = 28


# --- The video's facts and captions ----------------------------------------------------------


def _info_file(video: OpenVideo) -> dict[str, Any]:
    info = video.info
    chapters = []
    for chapter in info.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        start = chapter.get("start_time")
        title = text_of(chapter.get("title"), 150)
        if isinstance(start, int | float) and title:
            chapters.append({"start_s": round(float(start), 1), "title": title})
    return {
        "video_id": video.video_id,
        "title": text_of(info.get("title"), 300),
        "channel": text_of(info.get("channel") or info.get("uploader")),
        "channel_id": text_of(info.get("channel_id")),
        "upload_date": upload_date_of(info),
        "duration_s": video.duration_s,
        "licence": licence_of(info),
        "chapters": chapters,
        "description_start": text_of(info.get("description"), DESCRIPTION_CHARS),
    }


def _captions_text(video: OpenVideo) -> tuple[str | None, str]:
    """`(text, note)`: the English captions, one line each with its time first, or None."""
    try:
        source, language, track = _caption_track(video.ydl, video.info)
    except Refused:
        return None, "The video has no English captions that the tool may use."
    captions = parse_json3(track)
    if not captions.lines:
        return None, "The caption track has no words."
    rows = []
    last = ""
    for line in captions.lines:
        row = f"{format_time(line.start_s)}  {line.text}"
        if row != last:
            rows.append(row)
        last = row
    text = "\n".join(rows) + "\n"
    if len(text.encode("utf-8")) > MAX_CAPTION_LINES_BYTES:
        return None, "The captions are too large to keep."
    return text, f"Captions: {source} English track ({language}), {len(rows)} lines."


# --- YouTube's preview pictures --------------------------------------------------------------


@dataclass(frozen=True)
class Storyboard:
    format_id: str
    tile_w: int
    tile_h: int
    rows: int
    columns: int
    interval_s: float
    # (start of the sheet in the video, its length, its address)
    fragments: list[tuple[float, float, str]]


def _int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _interval_of(
    item: dict[str, Any], fragments: list[tuple[float, float, str]], per_sheet: int
) -> float:
    """The seconds between two preview frames.

    yt-dlp does not give the spacing. It gives `fps`, the number of preview frames (the last
    sheet counted as full) over the length of the video, which is a little below the real rate.
    YouTube's real spacing is a whole number of seconds: measured on a 3 min 33 s video, frame
    `k` is the picture at `2 * k` s, where `fps` says 1.97 s and would drift by 3 s over the
    video. So the spacing is `1 / fps` rounded to whole seconds, at least 1 s.
    """
    rate = item.get("fps")
    if isinstance(rate, int | float) and not isinstance(rate, bool) and rate > 0:
        return float(max(1, round(1 / rate)))
    total = sum(length for _, length, _ in fragments)
    return float(max(1, round(total / (len(fragments) * per_sheet))))


def pick_storyboard(info: dict[str, Any]) -> Storyboard | None:
    """YouTube's largest preview pictures (yt-dlp lists them as the formats `sb0` to `sb3`), or
    None. Their spacing is YouTube's own, even through the video, not on the cuts."""
    best: Storyboard | None = None
    for item in info.get("formats") or []:
        if not isinstance(item, dict) or not _STORYBOARD_ID.match(str(item.get("format_id"))):
            continue
        width, height = _int(item.get("width")), _int(item.get("height"))
        rows, columns = _int(item.get("rows")), _int(item.get("columns"))
        raw = item.get("fragments")
        if not (width and height and rows and columns and isinstance(raw, list) and raw):
            continue
        fragments: list[tuple[float, float, str]] = []
        start = 0.0
        for part in raw:
            if not isinstance(part, dict):
                break
            length, address = part.get("duration"), part.get("url")
            if not (
                isinstance(length, int | float)
                and not isinstance(length, bool)
                and length > 0
                and isinstance(address, str)
            ):
                break
            fragments.append((start, float(length), address))
            start += float(length)
        else:
            interval = _interval_of(item, fragments, rows * columns)
            found = Storyboard(
                str(item["format_id"]), width, height, rows, columns, interval, fragments
            )
            if best is None or width * height > best.tile_w * best.tile_h:
                best = found
    return best


def _read_preview(video: OpenVideo, address: str) -> bytes:
    from yt_dlp.utils import YoutubeDLError

    check_url(address)
    try:
        data = video.ydl.urlopen(address).read(MAX_PREVIEW_PART_BYTES + 1)
    except YoutubeDLError as error:
        raise Refused(f"A preview picture could not be downloaded: {error}") from error
    if len(data) > MAX_PREVIEW_PART_BYTES:
        raise Refused("A preview picture is too large to keep.")
    return data


def preview_tiles(
    video: OpenVideo, board: Storyboard, from_s: float, to_s: float
) -> tuple[list[tuple[float, Image.Image]], int]:
    """The preview frames from `from_s` to `to_s` with the time of each, and the bytes read. Only
    the preview pictures that overlap the range are downloaded."""
    tiles: list[tuple[float, Image.Image]] = []
    total = 0
    per_sheet = board.rows * board.columns
    # Sheet `i` holds the frames `i * per_sheet` and on, and frame `k` is the picture at
    # `k * interval_s`. A sheet's own length (from yt-dlp) is not used: it is the video's length
    # shared out evenly, which is not where the frames are.
    for sheet_number, (_, _, address) in enumerate(board.fragments):
        first_frame = sheet_number * per_sheet
        if first_frame * board.interval_s > to_s or (
            (first_frame + per_sheet) * board.interval_s <= from_s
        ):
            continue
        data = _read_preview(video, address)
        total += len(data)
        if total > MAX_SCAN_BYTES:
            raise Refused(
                "The preview pictures of this range are more than "
                f"{MAX_SCAN_BYTES // (1024 * 1024)} MB. Scan a shorter range."
            )
        try:
            with Image.open(io.BytesIO(data)) as sheet:
                sheet.load()
                picture = sheet.convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise Refused(f"A preview picture cannot be read: {error}") from error
        for index in range(per_sheet):
            time_s = (first_frame + index) * board.interval_s
            if time_s < from_s - 1e-6 or time_s > to_s or time_s >= video.duration_s:
                continue
            column, row = index % board.columns, index // board.columns
            left, top = column * board.tile_w, row * board.tile_h
            if left + board.tile_w > picture.width or top + board.tile_h > picture.height:
                continue
            tiles.append(
                (time_s, picture.crop((left, top, left + board.tile_w, top + board.tile_h)))
            )
    return tiles, total


# --- scan ------------------------------------------------------------------------------------


def _clear(folder: Path, *patterns: str) -> None:
    for pattern in patterns:
        for path in folder.glob(pattern):
            _unlink_own(path)


def _write_text(path: Path, text: str) -> None:
    _write_atomic(path, text.encode("utf-8"))


def _sheet_lines(sheets: list[Sheet], root: Path, every: str) -> list[str]:
    lines = []
    for sheet in sheets:
        lines.append(
            f"  {sheet.path.relative_to(root)}  {sheet.frames} frames, "
            f"{format_time_tenths(sheet.first_s)} to {format_time_tenths(sheet.last_s)}"
        )
    lines.append(f"  {every}")
    return lines


def _range(from_s: float | None, to_s: float | None, duration_s: float, limit: float, what: str):
    """The range asked for, kept inside the video; refuses a range that cannot be used."""
    if (from_s is None) != (to_s is None):
        raise Refused("--from and --to go together.")
    if from_s is None or to_s is None:
        return None
    if from_s < 0 or to_s <= from_s:
        raise Refused("--to must be later than --from, and both must be zero or more.")
    if from_s >= duration_s:
        raise Refused(
            f"--from is past the end of the video, which lasts {format_time(duration_s)}."
        )
    to_s = min(to_s, duration_s)
    if to_s - from_s > limit:
        raise Refused(
            f"A {what} covers at most {limit:.0f} s, and {to_s - from_s:.0f} s was asked for. "
            "Choose a shorter range."
        )
    return from_s, to_s


def scan_previews(
    rnd: FootageRound, *, mark_id: str, url: str, from_s: float | None, to_s: float | None
) -> list[str]:
    """`scan`: the video's facts, its captions and YouTube's preview pictures as contact sheets.
    Nothing of the video is downloaded. Returns the lines to tell the agent."""
    rnd.mark(mark_id)
    with open_video(url, command="scan") as video:
        chosen = _range(from_s, to_s, video.duration_s, MAX_SCAN_S, "scan")
        folder = rnd.scan_dir(mark_id, video.video_id)
        lines = [
            f"Video {video.video_id}: {text_of(video.info.get('title'), 120)!r}, "
            f"{format_time(video.duration_s)} long, channel "
            f"{text_of(video.info.get('channel') or video.info.get('uploader'))!r}."
        ]
        _clear(folder, "sheet-*.jpg")
        _write_text(
            folder / "info.json",
            json.dumps(_info_file(video), indent=2, ensure_ascii=False) + "\n",
        )
        lines.append(f"Wrote {folder.relative_to(rnd.root)}/info.json.")
        captions, note = _captions_text(video)
        if captions is None:
            _unlink_own(folder / "captions.txt")
        else:
            _write_text(folder / "captions.txt", captions)
        lines.append(note + (" Wrote captions.txt." if captions else ""))
        for warning in video.log.warnings:
            lines.append(f"yt-dlp: {warning[:300]}")

        if chosen is None:
            if video.duration_s > MAX_SCAN_S:
                lines.append(
                    f"The video is longer than {MAX_SCAN_S / 60:.0f} minutes, so no preview "
                    "pictures were made. Find the area from the chapters, the captions or the "
                    "description, then run scan again with --from and --to (at most "
                    f"{MAX_SCAN_S / 60:.0f} minutes apart)."
                )
                return lines
            chosen = (0.0, video.duration_s)
        start_s, end_s = chosen

        board = pick_storyboard(video.info)
        if board is None:
            lines.append(
                "YouTube gave no preview pictures for this video. Use `scan --fine` on a range "
                f"of at most {MAX_FINE_S:.0f} s that you narrowed down from the captions."
            )
            return lines
        tiles, used = preview_tiles(video, board, start_s, end_s)
        if not tiles:
            lines.append("There are no preview pictures in that range.")
            return lines
        sheets = write_sheets(tiles, folder, format_time_tenths)
        lines.append(
            f"Preview pictures {board.tile_w}x{board.tile_h}, one every {board.interval_s:.1f} s "
            f"(YouTube's spacing, not on the cuts): {len(tiles)} frames from "
            f"{format_time(tiles[0][0])} to {format_time(tiles[-1][0])}, {used / 1024:.0f} KB "
            "downloaded."
        )
        lines.extend(
            _sheet_lines(sheets, rnd.root, "Each frame has its time stamped in its corner.")
        )
        lines.append(
            "A shot shorter than the spacing can fall between two frames and not be seen. When "
            f"you have a range of at most {MAX_FINE_S:.0f} s, run `scan --fine` on it."
        )
        return lines


# --- scan --fine -----------------------------------------------------------------------------


def scan_fine(
    rnd: FootageRound, *, mark_id: str, url: str, from_s: float | None, to_s: float | None
) -> list[str]:
    """`scan --fine`: download only the range at low resolution, without sound, and write sheets
    of frames half a second apart and the cut times in it. The download is not kept."""
    rnd.mark(mark_id)
    if from_s is None or to_s is None:
        raise Refused("scan --fine needs --from and --to.")
    if to_s - from_s < MIN_FINE_S:
        raise Refused(f"A fine scan covers at least {MIN_FINE_S:.0f} s.")
    with open_video(url, command="scan") as video:
        chosen = _range(from_s, to_s, video.duration_s, MAX_FINE_S, "fine scan")
        assert chosen is not None
        start_s, end_s = chosen
        if end_s - start_s < MIN_FINE_S:
            raise Refused("That range is too short, or past the end of the video.")
        folder = rnd.scan_dir(
            mark_id, video.video_id, f"fine-{math.floor(start_s)}-{math.ceil(end_s)}"
        )
        with tempfile.TemporaryDirectory(prefix="visio-fine-") as temp:
            work = Path(temp)
            clip = download_range(
                video, work, start_s, end_s, short_side=FINE_SHORT_SIDE, crf=FINE_CRF, scale=None
            )
            size = clip.stat().st_size
            if size > MAX_FINE_BYTES:
                raise Refused(
                    f"The range is larger than {MAX_FINE_BYTES // (1024 * 1024)} MB ({size} bytes)."
                )
            facts = probe(clip)
            if facts.video_streams != 1 or facts.audio_streams:
                raise Refused("The downloaded range is not one picture stream with no sound.")
            pictures_dir = work / "pictures"
            pictures_dir.mkdir()
            pictures = sample_pictures(clip, pictures_dir)
            cuts = find_cuts(clip, facts.duration_s)
            tiles: list[tuple[float, Image.Image]] = []
            for index, path in enumerate(pictures):
                time_s = start_s + index * STRIP_EVERY_S
                if time_s > end_s + 1e-6:
                    break
                with Image.open(path) as picture:
                    picture.load()
                    tiles.append((time_s, picture.copy()))
            if not tiles:
                raise Refused("No pictures could be taken from the range.")
            _clear(folder, "sheet-*.jpg", "cuts.json")
            sheets = write_sheets(tiles, folder, format_time_tenths)
        source_cuts = [round(start_s + cut, 3) for cut in cuts]
        _write_text(
            folder / "cuts.json",
            json.dumps(
                {
                    "from_s": round(start_s, 3),
                    "to_s": round(end_s, 3),
                    "threshold": CUT_SCENE_THRESHOLD,
                    "cuts": source_cuts,
                },
                indent=2,
            )
            + "\n",
        )
        lines = [
            f"Fine scan of {format_time_tenths(start_s)} to {format_time_tenths(end_s)} "
            f"({end_s - start_s:.1f} s) of {video.video_id}, {facts.width}x{facts.height}, "
            f"{size / 1024:.0f} KB downloaded, no sound. A frame every {STRIP_EVERY_S} s.",
            *_sheet_lines(
                sheets, rnd.root, "Each frame has its time (to 0.1 s) stamped in its corner."
            ),
            f"Cuts found ({len(source_cuts)}): "
            + (", ".join(format_time_tenths(cut) for cut in source_cuts) or "none")
            + f". Written to {folder.relative_to(rnd.root)}/cuts.json.",
        ]
        for warning in video.log.warnings:
            lines.append(f"yt-dlp: {warning[:300]}")
        return lines
