"""Capture of a web page: find the exact quote, then screenshot it and measure its lines."""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, sync_playwright

from . import (
    CAPTURE_TIMEOUT_S,
    LANDSCAPE_VIEWPORT,
    MAX_IMAGE_BYTES,
    MAX_RECTS,
    MAX_TEXT_BYTES,
    PAGE_LOAD_TIMEOUT_S,
    PORTRAIT_USER_AGENT,
    PORTRAIT_VIEWPORT,
    QUOTE_MAX_CHARS,
    QUOTE_MIN_CHARS,
)
from .geometry import Rect, merge_lines, pad_inside, to_fractions
from .netguard import DOWNLOAD_USER_AGENT, check_address_text, check_url
from .rounds import Captured, Described, Refused, Round, evidence_entry, file_names, sha256_of
from .text import compact_copy, find_quote, nearest_text, normalise, normalise_with_map

# How far down the screenshot the quote's middle is put.
QUOTE_HEIGHT_FRACTION = 0.4
# A quote taller than this share of the viewport cannot be read after the zoom.
MAX_QUOTE_HEIGHT_SHARE = 0.8
CONTEXT_HEIGHTS = 3
# CSS pixels of room added around each line of the quote.
RECT_PAD_PX = 2.0

# Known consent buttons, reject first. These are the buttons of common consent tools; there is no
# code for particular sites.
KNOWN_CONSENT_SELECTORS = [
    "#onetrust-reject-all-handler",
    "#onetrust-accept-btn-handler",
    "#didomi-notice-disagree-button",
    "#didomi-notice-agree-button",
    "#CybotCookiebotDialogBodyButtonDecline",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#truste-consent-required",
    "#truste-consent-button",
    ".qc-cmp2-summary-buttons button[mode='primary']",
]
# Button texts, in the order they are tried (reject first). Only a button inside something that
# looks like a consent box is clicked.
CONSENT_BUTTON_TEXTS = [
    "reject all",
    "reject",
    "decline",
    "necessary only",
    "only necessary",
    "accept all",
    "accept all cookies",
    "accept",
    "i agree",
    "agree",
    "got it",
]
CONSENT_WORDS = r"cookie|consent|gdpr|cmp|privacy|sp[-_]|message_id|onetrust|didomi|cybot"

_JS_CONSENT = """
([known, texts, consentWords, inConsentFrame]) => {
  const wordsRe = new RegExp(consentWords, 'i');
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  for (const sel of known) {
    const el = document.querySelector(sel);
    if (el && visible(el)) { el.click(); return 'button ' + sel; }
  }
  const looksLikeConsent = (el) => {
    if (inConsentFrame) return true;
    let node = el;
    for (let i = 0; i < 10 && node && node !== document.body; i += 1, node = node.parentElement) {
      const cs = getComputedStyle(node);
      if (cs.position === 'fixed' || cs.position === 'sticky') return true;
      if (node.getAttribute('role') === 'dialog' || node.getAttribute('aria-modal') === 'true') {
        return true;
      }
      const cls = typeof node.className === 'string' ? node.className : '';
      if (wordsRe.test((node.id || '') + ' ' + cls)) return true;
    }
    return false;
  };
  const label = (el) =>
    (el.innerText || el.value || el.getAttribute('aria-label') || '')
      .trim().toLowerCase().replace(/\\s+/g, ' ');
  const buttons = [
    ...document.querySelectorAll(
      'button, [role="button"], a[role="button"], input[type="button"], input[type="submit"]'
    ),
  ].filter(visible);
  for (const wanted of texts) {
    const found = buttons.find((el) => label(el) === wanted && looksLikeConsent(el));
    if (found) { found.click(); return 'text ' + wanted; }
  }
  return null;
}
"""

# Removes what hides or covers the page: fixed elements are hidden, sticky ones stop sticking,
# and a locked scroll is released.
_JS_TIDY = """
() => {
  const style = document.createElement('style');
  style.textContent = 'html { scroll-behavior: auto !important; }';
  document.head.appendChild(style);
  for (const el of document.querySelectorAll('body *')) {
    const position = getComputedStyle(el).position;
    if (position === 'fixed') el.style.setProperty('display', 'none', 'important');
    else if (position === 'sticky') el.style.setProperty('position', 'static', 'important');
  }
  for (const el of [document.documentElement, document.body]) {
    if (el && getComputedStyle(el).overflow === 'hidden') {
      el.style.setProperty('overflow', 'visible', 'important');
    }
  }
}
"""

# The visible text of the page, in reading order. A line break is put between blocks and at
# <br>. The text nodes are kept in `window.__vecNodes` with their place in the text, counted in
# code points (not UTF-16 units) like Python counts.
_JS_COLLECT = """
() => {
  const skip = new Set([
    'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE', 'META', 'LINK', 'SVG', 'CANVAS',
    'IFRAME', 'OBJECT', 'EMBED', 'AUDIO', 'VIDEO', 'SELECT', 'OPTION', 'TEXTAREA', 'INPUT',
  ]);
  const parts = [];
  const nodes = [];
  let cp = 0;
  const lastIsBreak = () => parts.length > 0 && parts[parts.length - 1] === '\\n';
  const addBreak = () => { parts.push('\\n'); cp += 1; };
  const walk = (el) => {
    const tag = el.tagName.toUpperCase();
    if (skip.has(tag)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return;
    if (tag === 'BR') { addBreak(); return; }
    const block = !cs.display.startsWith('inline') && cs.display !== 'contents';
    if (block && !lastIsBreak()) addBreak();
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const text = child.nodeValue;
        if (!text) continue;
        const length = Array.from(text).length;
        nodes.push({ node: child, cpStart: cp, cpLen: length });
        parts.push(text);
        cp += length;
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        walk(child);
      }
    }
    if (block && !lastIsBreak()) addBreak();
  };
  walk(document.body);
  window.__vecNodes = nodes;
  return parts.join('');
}
"""

_JS_SCROLL_TO = """
([start]) => {
  const hit = window.__vecNodes.find((n) => start >= n.cpStart && start < n.cpStart + n.cpLen);
  const el = hit && hit.node.parentElement;
  if (el) el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
}
"""

_JS_SCROLL_BY = "(dy) => window.scrollBy({ top: dy, left: 0, behavior: 'instant' })"

# The rectangles of the quote's text, one set per text node (a range over several nodes would
# also give the boxes of whole elements). `covered` is true when something else is on top.
_JS_RECTS = """
([start, end]) => {
  const out = [];
  for (const n of window.__vecNodes) {
    const a = Math.max(start, n.cpStart);
    const b = Math.min(end, n.cpStart + n.cpLen);
    if (a >= b) continue;
    const chars = Array.from(n.node.nodeValue);
    const range = document.createRange();
    range.setStart(n.node, chars.slice(0, a - n.cpStart).join('').length);
    range.setEnd(n.node, chars.slice(0, b - n.cpStart).join('').length);
    const owner = n.node.parentElement;
    for (const r of range.getClientRects()) {
      if (r.width < 1 || r.height < 1) continue;
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const related = top && owner && (owner.contains(top) || top.contains(owner));
      out.push({ x: r.left, y: r.top, w: r.width, h: r.height, covered: !related });
    }
  }
  return out;
}
"""

_JS_PAGE_INFO = """
() => {
  const root = document.documentElement;
  const body = document.body || root;
  return {
    scrollY: window.scrollY,
    innerWidth: window.innerWidth,
    docHeight: Math.max(root.scrollHeight, body.scrollHeight),
    scale: window.visualViewport ? window.visualViewport.scale : 1,
  };
}
"""


@dataclass(frozen=True)
class _Viewport:
    width: int
    height: int
    device_scale: int
    mobile: bool

    def as_record(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height, "device_scale": self.device_scale}


def viewport_for(orientation: str) -> _Viewport:
    """§4.7: a landscape project is captured at a desktop viewport, a portrait one at a phone's."""
    if orientation == "portrait":
        return _Viewport(**PORTRAIT_VIEWPORT, mobile=True)
    return _Viewport(**LANDSCAPE_VIEWPORT, mobile=False)


def check_quote_length(quote: str) -> str:
    """Normalise the quote and check its length."""
    cleaned = normalise(quote)
    if len(cleaned) < QUOTE_MIN_CHARS:
        raise Refused(f"The quote is too short (at least {QUOTE_MIN_CHARS} characters).")
    if len(cleaned) > QUOTE_MAX_CHARS:
        raise Refused(
            f"The quote is too long ({len(cleaned)} characters, the limit is {QUOTE_MAX_CHARS}). "
            "Choose the few words that prove the claim."
        )
    return cleaned


class _Network:
    """Watches what the page asks for and what answers. Refused requests are aborted."""

    def __init__(self) -> None:
        self._decisions: dict[str, bool] = {}
        self.responses: list[Any] = []

    def route(self, route: Route) -> None:
        url = route.request.url
        scheme = urlsplit(url).scheme
        if scheme in ("data", "blob", "about"):
            route.continue_()
            return
        host = urlsplit(url).hostname or ""
        if host not in self._decisions:
            try:
                check_url(url)
                self._decisions[host] = True
            except Refused:
                self._decisions[host] = False
        if self._decisions[host]:
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def verify(self, main_url: str, main_response: Any) -> None:
        """Every response must have come from a public server address, and every step of the
        redirect chain of the page must be a public address. Redirects between servers are not
        shown to the route handler, so this is where they are checked.
        """
        for response in self.responses:
            try:
                server = response.server_addr()
            except PlaywrightError:
                server = None
            if server and server.get("ipAddress"):
                check_address_text(server["ipAddress"])
        request = main_response.request if main_response is not None else None
        seen = 0
        while request is not None and seen < 20:
            check_url(request.url)
            request = request.redirected_from
            seen += 1
        check_url(main_url)


def _deadline_check(started: float) -> None:
    if time.monotonic() - started > CAPTURE_TIMEOUT_S:
        raise Refused(f"The capture took longer than {CAPTURE_TIMEOUT_S} seconds.")


def _dismiss_consent(page: Page) -> str | None:
    """Click a consent button if there is one, in the page or in a consent frame."""
    for frame in page.frames:
        in_consent_frame = frame != page.main_frame and bool(
            re.search(CONSENT_WORDS, f"{frame.name} {frame.url}", re.IGNORECASE)
        )
        try:
            clicked = frame.evaluate(
                _JS_CONSENT,
                [KNOWN_CONSENT_SELECTORS, CONSENT_BUTTON_TEXTS, CONSENT_WORDS, in_consent_frame],
            )
        except PlaywrightError:
            continue
        if clicked:
            return str(clicked)
    return None


def _rects_of(page: Page, span: tuple[int, int]) -> list[dict[str, Any]]:
    return page.evaluate(_JS_RECTS, list(span))


def _place_quote(page: Page, span: tuple[int, int], viewport: _Viewport) -> list[dict[str, Any]]:
    """Scroll so that the quote is in the viewport with its middle at 40% of the height, and
    return the rectangles of its text there. Refuses when it cannot be seen properly.
    """
    page.evaluate(_JS_SCROLL_TO, [span[0]])
    rects: list[dict[str, Any]] = []
    for _ in range(3):
        rects = _rects_of(page, span)
        if not rects:
            raise Refused(
                "The quote is in the page's text but has no visible place (it may be hidden or "
                "clipped). Choose another source or other words."
            )
        top = min(r["y"] for r in rects)
        bottom = max(r["y"] + r["h"] for r in rects)
        if bottom - top > MAX_QUOTE_HEIGHT_SHARE * viewport.height:
            raise Refused(
                "The quote is too long to read once zoomed in: it fills more than 80% of the "
                "screen. Choose fewer words."
            )
        shift = (top + bottom) / 2 - QUOTE_HEIGHT_FRACTION * viewport.height
        if abs(shift) < 1:
            break
        page.evaluate(_JS_SCROLL_BY, shift)
        page.wait_for_timeout(250)
    return _rects_of(page, span)


def _check_visible(rects: list[dict[str, Any]], viewport: _Viewport) -> None:
    for r in rects:
        if (
            r["x"] < -1
            or r["y"] < -1
            or r["x"] + r["w"] > viewport.width + 1
            or r["y"] + r["h"] > viewport.height + 1
        ):
            raise Refused(
                "Part of the quote is outside the screenshot (a box that scrolls, or a page "
                "wider than the screen). Choose another source or other words."
            )
        if r["covered"]:
            raise Refused(
                "Something is on top of the quote (a banner, a pop-up or a paywall). It cannot "
                "be captured as it is."
            )


def _context_screenshot(page: Page, viewport: _Viewport, top: int, height: int) -> bytes:
    """The page from `top` for `height` CSS pixels, built from screenshots of the viewport.
    (A single screenshot of a tall page is very slow, so the strips are joined here.)
    """
    scale = viewport.device_scale
    canvas = Image.new("RGB", (viewport.width * scale, height * scale), "white")
    strip_top = top
    while strip_top < top + height:
        page.evaluate("(y) => window.scrollTo({ top: y, left: 0, behavior: 'instant' })", strip_top)
        page.wait_for_timeout(200)
        actual = page.evaluate("window.scrollY")
        strip = page.screenshot(type="png", animations="disabled", caret="hide")
        with Image.open(io.BytesIO(strip)) as shot:
            canvas.paste(shot.convert("RGB"), (0, round((actual - top) * scale)))
        strip_top += viewport.height
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _png_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as image:
        return image.size


def capture_web(
    rnd: Round,
    *,
    claim_id: str,
    evidence_id: str,
    url: str,
    quote: str,
    described: Described,
) -> Captured:
    """Open `url`, find `quote`, and make the screenshot, the context image, the text copy and
    the rectangles of one line each. Refuses clearly when anything is wrong.
    """
    started = time.monotonic()
    rnd.claim(claim_id)
    rnd.check_room(claim_id, evidence_id)
    wanted = check_quote_length(quote)
    check_url(url)
    viewport = viewport_for(rnd.orientation)
    network = _Network()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            options: dict[str, Any] = {
                "viewport": {"width": viewport.width, "height": viewport.height},
                "device_scale_factor": viewport.device_scale,
                "user_agent": PORTRAIT_USER_AGENT if viewport.mobile else DOWNLOAD_USER_AGENT,
                "has_touch": viewport.mobile,
                "locale": "en-US",
                "service_workers": "block",
                "accept_downloads": False,
                "permissions": [],
            }
            context = browser.new_context(**options)
            context.set_default_timeout(PAGE_LOAD_TIMEOUT_S * 1000)
            context.route("**/*", network.route)
            page = context.new_page()
            page.on("response", lambda response: network.responses.append(response))
            return _capture_in_page(
                page,
                network=network,
                started=started,
                rnd=rnd,
                evidence_id=evidence_id,
                url=url,
                wanted=wanted,
                quote=quote,
                described=described,
                viewport=viewport,
            )
        except PlaywrightError as error:
            raise Refused(_browser_message(error)) from error
        finally:
            browser.close()


def _browser_message(error: PlaywrightError) -> str:
    text = str(error)
    if "ERR_BLOCKED_BY_CLIENT" in text:
        return "The address (or a redirect from it) leads to a local or private address."
    if "Download is starting" in text or "ERR_ABORTED" in text:
        return (
            "That address is a file download (probably a PDF), not a web page. Use the pdf command."
        )
    if "Timeout" in text:
        return f"The page did not load within {PAGE_LOAD_TIMEOUT_S} seconds."
    first_line = text.strip().splitlines()[0] if text.strip() else "unknown error"
    return f"The browser could not capture the page: {first_line}"


def _capture_in_page(
    page: Page,
    *,
    network: _Network,
    started: float,
    rnd: Round,
    evidence_id: str,
    url: str,
    wanted: str,
    quote: str,
    described: Described,
    viewport: _Viewport,
) -> Captured:
    notes: list[str] = []
    response = page.goto(url, wait_until="load")
    if response is None:
        raise Refused("The page gave no answer.")
    if response.status >= 400:
        raise Refused(
            f"The server answered {response.status}. If the page is behind a paywall or a login, "
            "report the claim as blocked."
        )
    content_type = response.headers.get("content-type", "")
    if "pdf" in content_type.lower():
        raise Refused("That address is a PDF. Use the pdf command.")
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PlaywrightError:
        pass  # Pages that never go quiet are captured as they are.
    network.verify(page.url, response)
    _deadline_check(started)

    consent = _dismiss_consent(page)
    if consent:
        notes.append(f"Closed a consent notice ({consent}).")
        page.wait_for_timeout(800)
    page.evaluate(_JS_TIDY)

    raw_text = page.evaluate(_JS_COLLECT)
    copy_text = compact_copy(raw_text)
    if len(copy_text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise Refused("The page's text is too large to keep.")
    source = normalise_with_map(raw_text)
    match = find_quote(source, wanted)
    if match is None:
        near = nearest_text(source.text, wanted)
        lines = ["The quote is not on the page (checked after normalising quotes and spaces)."]
        if near:
            lines.append("Nearest text on the page, to choose the exact words from:")
            lines.extend(f"  {number}. {text}" for number, text in enumerate(near, start=1))
        else:
            lines.append("No similar text was found on the page.")
        raise Refused("\n".join(lines))
    if find_quote(normalise_with_map(copy_text), wanted) is None:
        raise Refused("Internal error: the quote is in the page but not in its text copy.")
    if match.count > 1:
        notes.append(f"The quote is on the page {match.count} times. The first one is used.")
    _deadline_check(started)

    # Characters of the raw text (code points) that the quote covers.
    span = (match.start, match.end)
    rects = _place_quote(page, span, viewport)
    page.wait_for_timeout(300)
    rects = _place_quote(page, span, viewport)
    _check_visible(rects, viewport)
    info = page.evaluate(_JS_PAGE_INFO)
    if abs(info["scale"] - 1) > 0.01 or info["innerWidth"] != viewport.width:
        raise Refused("The page does not fit the screenshot size (it is zoomed). Try another page.")

    lines_px = merge_lines([(r["x"], r["y"], r["w"], r["h"]) for r in rects])
    padded: list[Rect] = [
        pad_inside(line, RECT_PAD_PX, RECT_PAD_PX, viewport.width, viewport.height)
        for line in lines_px
    ]
    if len(padded) > MAX_RECTS:
        raise Refused(f"The quote runs over {len(padded)} lines (the limit is {MAX_RECTS}).")

    scroll_y = info["scrollY"]
    image = page.screenshot(type="png", animations="disabled", caret="hide")
    expected = (viewport.width * viewport.device_scale, viewport.height * viewport.device_scale)
    if _png_size(image) != expected:
        raise Refused(f"The screenshot has size {_png_size(image)}, not the expected {expected}.")

    context_height = max(
        viewport.height, min(CONTEXT_HEIGHTS * viewport.height, int(info["docHeight"]))
    )
    centre = scroll_y + viewport.height / 2
    context_top = int(
        min(max(0, centre - context_height / 2), max(0, info["docHeight"] - context_height))
    )
    context_image = _context_screenshot(page, viewport, context_top, context_height)
    context_px = _png_size(context_image)
    # Scrolling can load more of the page and move the quote. It must still be where it was.
    page.evaluate(_JS_SCROLL_BY, scroll_y - page.evaluate("window.scrollY"))
    page.wait_for_timeout(200)
    after = merge_lines([(r["x"], r["y"], r["w"], r["h"]) for r in _rects_of(page, span)])
    if len(after) != len(lines_px) or any(
        abs(a[0] - b[0]) > 1 or abs(a[1] - b[1]) > 1 for a, b in zip(after, lines_px, strict=True)
    ):
        raise Refused("The page moved while it was captured (it loads more as it scrolls). Retry.")
    context_box = [
        0.0,
        round((scroll_y - context_top) / context_height, 6),
        1.0,
        round(viewport.height / context_height, 6),
    ]
    if context_box[1] < 0 or context_box[1] + context_box[3] > 1 + 1e-5:
        raise Refused("The page moved while it was captured. Try again.")
    for data in (image, context_image):
        if len(data) > MAX_IMAGE_BYTES:
            raise Refused(f"An image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")

    network.verify(page.url, response)
    names = file_names(evidence_id)
    files = {
        names["image"]: image,
        names["context_image"]: context_image,
        names["text_copy"]: copy_text.encode("utf-8"),
    }
    capture = {
        "image": names["image"],
        "image_px": list(expected),
        "context_image": names["context_image"],
        "context_box": context_box,
        "text_copy": names["text_copy"],
        "source_copy": None,
        "page": None,
        "viewport": viewport.as_record(),
        "rects": to_fractions(padded, viewport.width, viewport.height),
        "sha256": {name: sha256_of(data) for name, data in files.items()},
    }
    notes.append(
        f"Captured {len(padded)} line{'s' if len(padded) != 1 else ''}; "
        f"image {expected[0]}x{expected[1]}, context {context_px[0]}x{context_px[1]}."
    )
    entry = evidence_entry(
        evidence_id=evidence_id,
        kind="web",
        described=described,
        url=url,
        final_url=page.url,
        title=_clean_title(page.title()),
        quote=" ".join(raw_text[match.start : match.end].split()),
        capture=capture,
    )
    return Captured(entry=entry, files=files, notes=notes)


def _clean_title(title: str) -> str | None:
    cleaned = " ".join(title.split())
    return cleaned[:300] or None
