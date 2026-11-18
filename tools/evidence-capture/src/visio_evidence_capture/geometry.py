"""Rectangles. Coordinates go down from the top left, as in an image."""

from __future__ import annotations

from collections.abc import Sequence

# (x, y, width, height)
Rect = tuple[float, float, float, float]


def merge_lines(rects: Sequence[Rect]) -> list[Rect]:
    """One rectangle per line of text: pieces that overlap vertically by at least half of the
    smaller piece are joined into their bounding box. Sorted from the top.
    """
    lines: list[list[float]] = []  # left, top, right, bottom
    for x, y, w, h in sorted(rects, key=lambda r: (r[1], r[0])):
        right, bottom = x + w, y + h
        for line in lines:
            overlap = min(line[3], bottom) - max(line[1], y)
            if overlap >= 0.5 * min(line[3] - line[1], h):
                line[0] = min(line[0], x)
                line[1] = min(line[1], y)
                line[2] = max(line[2], right)
                line[3] = max(line[3], bottom)
                break
        else:
            lines.append([x, y, right, bottom])
    lines.sort(key=lambda line: (line[1], line[0]))
    return [(left, top, right - left, bottom - top) for left, top, right, bottom in lines]


def pad_inside(rect: Rect, pad_x: float, pad_y: float, width: float, height: float) -> Rect:
    """Grow a rectangle a little on every side, without leaving `width` x `height`."""
    x, y, w, h = rect
    left = max(0.0, x - pad_x)
    top = max(0.0, y - pad_y)
    right = min(width, x + w + pad_x)
    bottom = min(height, y + h + pad_y)
    return (left, top, right - left, bottom - top)


def to_fractions(rects: Sequence[Rect], width: float, height: float) -> list[list[float]]:
    """Rectangles as fractions of an image `width` x `height`, rounded to six places."""
    return [
        [round(x / width, 6), round(y / height, 6), round(w / width, 6), round(h / height, 6)]
        for x, y, w, h in rects
    ]
