"""The prompt sent to the video model (ANALYSIS.md Section 5.4). Pure functions, no I/O.

    Style: <style_prefix>. <description> <prompt_suffix>

The page shows this for every scene (the prompt preview), and Phase 9 sends the same text,
so there is exactly one place that builds it.
"""

from __future__ import annotations


def _collapse(text: str | None) -> str:
    """Trims the text and turns every run of whitespace, line breaks included, into one space."""
    return " ".join((text or "").split())


def assemble_prompt(
    style_prefix: str | None, description: str | None, prompt_suffix: str | None
) -> str | None:
    """`Style: <style_prefix>.` + the description + the suffix, joined by single spaces.

    None while the description is blank: there is nothing to send yet. A blank style prefix
    leaves the style part out. A full stop is not doubled when the prefix already ends with
    one, and one is added after the description (when it has no `.`, `!` or `?`) only if a
    suffix follows it.
    """
    body = _collapse(description)
    if not body:
        return None

    parts: list[str] = []
    style = _collapse(style_prefix)
    if style:
        parts.append(f"Style: {style}" if style.endswith(".") else f"Style: {style}.")

    suffix = _collapse(prompt_suffix)
    if suffix and body[-1] not in ".!?":
        body += "."
    parts.append(body)
    if suffix:
        parts.append(suffix)
    return " ".join(parts)
