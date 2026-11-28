"""Capture of a web page (the footage `page` command): the page from its top, at most
`PAGE_HEIGHTS` screens tall, and the lines of the words to focus on when asked.

The browser settings are the evidence ones (`web.py`): the same viewports, the same consent
banner handling, the same network guard. What is different: there is no quote to find, so the
words are optional, and the picture is the page from its top, not one screen around the words.
"""

from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from .. import (
    MAX_IMAGE_BYTES,
    MAX_RECTS,
    MAX_TEXT_BYTES,
    PAGE_LOAD_TIMEOUT_S,
    PORTRAIT_USER_AGENT,
    QUOTE_MAX_CHARS,
    QUOTE_MIN_CHARS,
)
from ..geometry import Rect, merge_lines, pad_inside, to_fractions
from ..netguard import DOWNLOAD_USER_AGENT, check_url
from ..rounds import sha256_of
from ..text import compact_copy, find_quote, nearest_text, normalise, normalise_with_map
from ..web import (
    _JS_COLLECT,
    _JS_PAGE_INFO,
    _JS_SCROLL_BY,
    _JS_TIDY,
    RECT_PAD_PX,
    _browser_message,
    _check_visible,
    _clean_title,
    _context_screenshot,
    _deadline_check,
    _dismiss_consent,
    _Network,
    _place_quote,
    _png_size,
    _rects_of,
    _Viewport,
    viewport_for,
)
from . import PAGE_HEIGHTS
from .rounds import Captured, Described, FootageRound, Refused, file_names, piece_entry


def check_focus_length(focus: str) -> str:
    """Normalise the focus words and check their length."""
    cleaned = normalise(focus)
    if len(cleaned) < QUOTE_MIN_CHARS:
        raise Refused(f"The focus is too short (at least {QUOTE_MIN_CHARS} characters).")
    if len(cleaned) > QUOTE_MAX_CHARS:
        raise Refused(
            f"The focus is too long ({len(cleaned)} characters, the limit is {QUOTE_MAX_CHARS}). "
            "Choose the few words the script talks about."
        )
    return cleaned


def screen_of(top_px: float, viewport_height: int) -> int:
    """The screen (counted from 1) that a height of the page falls in."""
    return int(top_px // viewport_height) + 1


def check_focus_inside(
    rects: list[Rect], image_height: float, viewport_height: int, doc_height: float
) -> None:
    """Refuse a focus that is below the part of the page the picture holds."""
    bottom = max(y + h for _, y, _, h in rects)
    if bottom <= image_height + 1:
        return
    screen = screen_of(min(y for _, y, _, _ in rects), viewport_height)
    raise Refused(
        f"The focus words are on screen {screen} of the page, below the first {PAGE_HEIGHTS} "
        f"screens that are captured (the page is {doc_height / viewport_height:.1f} screens "
        "tall). Use a page where the words are higher up, or capture the page with no focus."
    )


def capture_page(
    rnd: FootageRound,
    *,
    mark_id: str,
    piece_id: str,
    url: str,
    focus: str | None,
    described: Described,
) -> Captured:
    """Open `url`, and make the picture of the page from its top, its text and the focus lines."""
    started = time.monotonic()
    rnd.mark(mark_id)
    rnd.check_room(mark_id, piece_id)
    wanted = check_focus_length(focus) if focus is not None else None
    check_url(url)
    viewport = viewport_for(rnd.orientation)
    network = _Network()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": viewport.width, "height": viewport.height},
                device_scale_factor=viewport.device_scale,
                user_agent=PORTRAIT_USER_AGENT if viewport.mobile else DOWNLOAD_USER_AGENT,
                has_touch=viewport.mobile,
                locale="en-US",
                service_workers="block",
                accept_downloads=False,
                permissions=[],
            )
            context.set_default_timeout(PAGE_LOAD_TIMEOUT_S * 1000)
            context.route("**/*", network.route)
            page = context.new_page()
            page.on("response", lambda response: network.responses.append(response))
            return _capture_in_page(
                page,
                network=network,
                started=started,
                piece_id=piece_id,
                url=url,
                wanted=wanted,
                focus=focus,
                described=described,
                viewport=viewport,
            )
        except PlaywrightError as error:
            raise Refused(_browser_message(error)) from error
        finally:
            browser.close()


def _capture_in_page(
    page: Page,
    *,
    network: _Network,
    started: float,
    piece_id: str,
    url: str,
    wanted: str | None,
    focus: str | None,
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
            "report the mark as blocked."
        )
    if "pdf" in response.headers.get("content-type", "").lower():
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

    span: tuple[int, int] | None = None
    if wanted is not None:
        source = normalise_with_map(raw_text)
        match = find_quote(source, wanted)
        if match is None:
            near = nearest_text(source.text, wanted)
            lines = ["The focus words are not on the page (checked after normalising quotes)."]
            if near:
                lines.append("Nearest text on the page, to choose the exact words from:")
                lines.extend(f"  {number}. {text}" for number, text in enumerate(near, start=1))
            else:
                lines.append("No similar text was found on the page.")
            raise Refused("\n".join(lines))
        if find_quote(normalise_with_map(copy_text), wanted) is None:
            raise Refused("Internal error: the focus is in the page but not in its text copy.")
        if match.count > 1:
            notes.append(f"The focus words are on the page {match.count} times. The first is used.")
        span = (match.start, match.end)
    _deadline_check(started)

    info = page.evaluate(_JS_PAGE_INFO)
    if abs(info["scale"] - 1) > 0.01 or info["innerWidth"] != viewport.width:
        raise Refused("The page does not fit the screenshot size (it is zoomed). Try another page.")
    doc_height = float(info["docHeight"])
    height = max(viewport.height, min(PAGE_HEIGHTS * viewport.height, int(doc_height)))
    if doc_height > height + 1:
        notes.append(
            f"The page is {doc_height / viewport.height:.1f} screens tall. The first "
            f"{height / viewport.height:.1f} are captured."
        )

    # The focus lines, in CSS pixels from the top of the page.
    focus_lines: list[Rect] = []
    measured: list[Rect] = []
    scroll_y = 0.0
    if span is not None:
        rects = _place_quote(page, span, viewport)
        page.wait_for_timeout(300)
        rects = _place_quote(page, span, viewport)
        _check_visible(rects, viewport)
        scroll_y = float(page.evaluate("window.scrollY"))
        measured = merge_lines([(r["x"], r["y"] + scroll_y, r["w"], r["h"]) for r in rects])
        check_focus_inside(measured, height, viewport.height, doc_height)
        focus_lines = [
            pad_inside(line, RECT_PAD_PX, RECT_PAD_PX, viewport.width, height) for line in measured
        ]
        if len(focus_lines) > MAX_RECTS:
            raise Refused(
                f"The focus runs over {len(focus_lines)} lines (the limit is {MAX_RECTS})."
            )
    _deadline_check(started)

    image = _context_screenshot(page, viewport, 0, height)
    expected = (viewport.width * viewport.device_scale, height * viewport.device_scale)
    if _png_size(image) != expected:
        raise Refused(f"The screenshot has size {_png_size(image)}, not the expected {expected}.")
    if len(image) > MAX_IMAGE_BYTES:
        raise Refused(f"The image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")

    if span is not None:
        # Scrolling can load more of the page and move the words. They must still be where
        # they were.
        page.evaluate(_JS_SCROLL_BY, scroll_y - page.evaluate("window.scrollY"))
        page.wait_for_timeout(200)
        actual = float(page.evaluate("window.scrollY"))
        after = merge_lines(
            [(r["x"], r["y"] + actual, r["w"], r["h"]) for r in _rects_of(page, span)]
        )
        if len(after) != len(measured) or any(
            abs(a[0] - b[0]) > 1 or abs(a[1] - b[1]) > 1
            for a, b in zip(after, measured, strict=True)
        ):
            raise Refused(
                "The page moved while it was captured (it loads more as it scrolls). Retry."
            )

    network.verify(page.url, response)
    names = file_names(piece_id)
    files = {names["image"]: image, names["text_copy"]: copy_text.encode("utf-8")}
    capture: dict[str, Any] = {
        "image": names["image"],
        "image_px": list(expected),
        "viewport": [viewport.width, viewport.height],
        "device_scale": viewport.device_scale,
        "text_copy": names["text_copy"],
        "focus_text": " ".join(raw_text[span[0] : span[1]].split()) if span is not None else None,
        "focus_rects": to_fractions(focus_lines, viewport.width, height),
        "sha256": {name: sha256_of(data) for name, data in files.items()},
    }
    if focus is None:
        notes.append(f"Captured the page, image {expected[0]}x{expected[1]}, no focus.")
    else:
        notes.append(
            f"Captured the page, image {expected[0]}x{expected[1]}, "
            f"{len(focus_lines)} focus line{'s' if len(focus_lines) != 1 else ''}."
        )
    entry = piece_entry(
        piece_id=piece_id,
        kind="page",
        described=described,
        url=url,
        final_url=page.url,
        title=_clean_title(page.title()),
        capture=capture,
    )
    return Captured(entry=entry, files=files, notes=notes)
