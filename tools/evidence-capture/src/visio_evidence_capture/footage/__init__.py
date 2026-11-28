"""Visio Studio footage capture (FTG-008, FTG-009): images, web pages, PDF pages and YouTube clips
for a footage round.

A second command of the evidence capture tool's package. It reads `brief/footage.json` and writes
inside `results/<mark_id>/` of a footage round and nowhere else. The folder, the brief and the
result are fixed in `Footage_broll_implementation_phases.md` (§4.3, §4.5, §4.6).
"""

from typing import Final

TOOL_NAME: Final = "visio-footage-capture"
# Version 2 (FTG-009) adds `scan`, `scan --fine` and `clip` and the `video` kind.
TOOL_VERSION: Final = "2"

BRIEF_SCHEMA: Final = "visio.footage.brief"
BRIEF_VERSION: Final = 1
RESULT_SCHEMA: Final = "visio.footage.result"
RESULT_VERSION: Final = 1

# What the agent may say (§4.6). There is no `partial` or `contradicted`: footage proves nothing.
STATUSES: Final = ("found", "not_found", "blocked")
STATUSES_WITH_PIECES: Final = ("found",)
# `video` is made by `clip` (FTG-009); `image`, `page` and `pdf` by their own commands (FTG-008).
KINDS: Final = ("video", "image", "page", "pdf")
STILL_KINDS: Final = ("image", "page", "pdf")
TIERS: Final = ("official", "press", "commons", "news", "creator", "other")
SAME_EVENT: Final = ("yes", "no", "unknown")
ON_SCREEN_TEXT: Final = ("none", "small", "large")

# Limits. The import (FTG-011) applies its own limits to what it finds.
MAX_IMAGE_PIXELS: Final = 40_000_000
# A picture whose longer side is shorter than this gets a warning.
LOW_RES_LONG_SIDE: Final = 1280
# A page is captured from its top, at most this many screens tall.
PAGE_HEIGHTS: Final = 4
# A PDF page is rendered with its longer side at this many pixels (never more than the pixel cap).
PDF_LONG_SIDE_PX: Final = 4096

# --- YouTube scans and clips (§4.7, FTG-009) ---------------------------------------------------

# A whole video is scanned (YouTube's previews) only up to this long; a longer one needs a range.
MAX_SCAN_S: Final = 1200.0
# A fine scan (frames 0.5 s apart) covers at most this many seconds.
MAX_FINE_S: Final = 90.0
# A piece's `use` lasts this long (§4.8 check 4) and is downloaded with this much on each side.
CLIP_MIN_S: Final = 2.0
CLIP_MAX_S: Final = 15.0
CLIP_PAD_S: Final = 2.0
# A stored video's shorter side is at most this (as the app's own copy, FTG-003).
MAX_SHORT_SIDE: Final = 1080
# Below this shorter side a clip gets a low-resolution warning.
LOW_RES_SHORT_SIDE: Final = 720
# The scans' picture height: yt-dlp's `res` counts the shorter side.
FINE_SHORT_SIDE: Final = 360
# How far a downloaded file's length may be from the window asked for.
DURATION_TOLERANCE_S: Final = 0.5
# Bytes the tool will keep or download.
MAX_CLIP_BYTES: Final = 60 * 1024 * 1024
MAX_SCAN_BYTES: Final = 20 * 1024 * 1024  # the preview pictures of one scan
MAX_PREVIEW_PART_BYTES: Final = 2 * 1024 * 1024  # one preview picture
MAX_FINE_BYTES: Final = 40 * 1024 * 1024  # the 360p range of a fine scan
MAX_CAPTION_LINES_BYTES: Final = 2 * 1024 * 1024
DESCRIPTION_CHARS: Final = 2000

# The strip and the cut finding are a copy of the app's (`backend/app/services/footage_frames.py`).
# Keep these values the same.
STRIP_EVERY_S: Final = 0.5
STRIP_COLUMNS: Final = 10
STRIP_TILE_W: Final = 192
STRIP_TILE_H: Final = 108
STRIP_JPEG_QUALITY: Final = 4
CUT_SCENE_THRESHOLD: Final = 0.3
CUT_PROBE_WIDTH: Final = 320

# Contact sheets the agent reads: 6 x 6 frames of 320 x 180, one 1920 x 1080 picture.
SHEET_COLUMNS: Final = 6
SHEET_ROWS: Final = 6
SHEET_TILE_W: Final = 320
SHEET_TILE_H: Final = 180
SHEET_JPEG_QUALITY: Final = 85
