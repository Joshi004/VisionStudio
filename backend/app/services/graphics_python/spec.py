"""The template spec that GFX-006 stores, as the renderer checks it before drawing (a port of
`readSpec` in `motion/src/templates/spec.ts`). The backend has already checked the spec in depth
(`graphics_templates.check_spec`); this only makes sure it is the catalogue's version and has the
parts the drawing code reads, so a wrong input fails with a clear message.
"""

from __future__ import annotations

from typing import Any, Final

from app.services.graphics_templates import CATALOGUE_VERSION

_VARIANTS: Final = {
    "kpi_card": ("center", "split"),
    "bar_comparison": ("vertical", "horizontal"),
    "line_trend": ("line", "area"),
    "flow_diagram": ("horizontal", "vertical"),
    "bullet_build": ("list", "statement"),
}


class DrawFailed(Exception):
    """The input cannot be drawn. The message is for the owner and appears on the render's card."""


def cannot_draw(message: str) -> DrawFailed:
    """The error of a template whose parts do not fit. Use as `raise cannot_draw("...")`."""
    return DrawFailed(f"The template cannot be drawn: {message}")


def read_spec(spec: Any) -> dict[str, Any]:
    """The spec a render's `input` holds. Raises DrawFailed with what is wrong with it."""
    if not isinstance(spec, dict):
        raise DrawFailed("The template spec is missing from the render's input.")
    template = spec.get("template")
    if template is None:
        raise DrawFailed("The spec says no template fits, so there is nothing to draw.")
    if template not in _VARIANTS:
        raise DrawFailed(f"The template {template!r} is not in the catalogue.")
    if spec.get("catalogue_version") != CATALOGUE_VERSION:
        raise DrawFailed(
            f"The spec was written for catalogue version {spec.get('catalogue_version')}; "
            f"this renderer draws version {CATALOGUE_VERSION}."
        )
    if spec.get("variant") not in _VARIANTS[template]:
        raise DrawFailed(f"The variant {spec.get('variant')!r} of {template} is unknown.")
    for key in ("fields", "beats", "text"):
        if not isinstance(spec.get(key), dict):
            raise DrawFailed(f'The spec has no "{key}".')
    return spec
