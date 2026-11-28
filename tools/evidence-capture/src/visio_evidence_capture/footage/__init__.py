"""Visio Studio footage capture (FTG-008): images, web pages and PDF pages for a footage round.

A second command of the evidence capture tool's package. It reads `brief/footage.json` and writes
inside `results/<mark_id>/` of a footage round and nowhere else. The folder, the brief and the
result are fixed in `Footage_broll_implementation_phases.md` (§4.3, §4.5, §4.6).
"""

from typing import Final

TOOL_NAME: Final = "visio-footage-capture"
TOOL_VERSION: Final = "1"

BRIEF_SCHEMA: Final = "visio.footage.brief"
BRIEF_VERSION: Final = 1
RESULT_SCHEMA: Final = "visio.footage.result"
RESULT_VERSION: Final = 1

# What the agent may say (§4.6). There is no `partial` or `contradicted`: footage proves nothing.
STATUSES: Final = ("found", "not_found", "blocked")
STATUSES_WITH_PIECES: Final = ("found",)
# `video` is made by the YouTube commands (FTG-009); this phase makes the other three.
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
