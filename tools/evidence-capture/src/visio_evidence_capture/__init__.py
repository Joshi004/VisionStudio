"""Visio Studio evidence capture tool (EVD-004).

The only thing that makes screenshots and highlight rectangles (EV-5). It writes inside
`results/<claim_id>/` of a research round and nowhere else.
"""

from typing import Final

TOOL_NAME: Final = "visio-evidence-capture"
TOOL_VERSION: Final = "1"

RESULT_SCHEMA: Final = "visio.evidence.result"
RESULT_VERSION: Final = 1
BRIEF_SCHEMA: Final = "visio.evidence.brief"
BRIEF_VERSION: Final = 1

# Limits. The import (EVD-006) applies its own limits to what it finds.
PAGE_LOAD_TIMEOUT_S: Final = 30
CAPTURE_TIMEOUT_S: Final = 120
MAX_PDF_BYTES: Final = 50 * 1024 * 1024
MAX_TEXT_BYTES: Final = 5 * 1024 * 1024
MAX_IMAGE_BYTES: Final = 20 * 1024 * 1024
MAX_RECTS: Final = 12
QUOTE_MIN_CHARS: Final = 3
QUOTE_MAX_CHARS: Final = 600
MAX_REDIRECTS: Final = 5

# What the agent may say (§4.5).
STATUSES: Final = ("found", "partial", "not_found", "contradicted", "blocked")
RELATIONS: Final = ("supports", "partly_supports", "contradicts", "context")
TIERS: Final = ("primary", "secondary", "other")
KINDS: Final = ("web", "pdf")
STATUSES_WITH_EVIDENCE: Final = ("found", "partial", "contradicted")

# Viewports by orientation (§4.7). `image_px` is `viewport * device_scale`.
LANDSCAPE_VIEWPORT: Final = {"width": 1280, "height": 720, "device_scale": 2}
PORTRAIT_VIEWPORT: Final = {"width": 360, "height": 640, "device_scale": 4}
PORTRAIT_USER_AGENT: Final = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
