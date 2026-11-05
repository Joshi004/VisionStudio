"""The building blocks of the Graphics lab, and the checks of a block scene (GFX-009,
`Graphics_lab_implementation_phases.md` §4.5.2).

Pure functions, no I/O.

The model designs a scene freely from ten blocks that were written once (`motion/src/blocks/`):
each element has a block, a region of a 12 x 12 grid inside the safe area, and an entrance on a
beat. `check_scene` turns the model's answer into the stored scene, or raises ValueError with a
message fit for the user and for the model's corrected retry. Long text is never cut.

**What the checks hold to.**

- At most 12 elements and 6 `text` blocks; known blocks, effects and keys; no unknown key.
- Every ref names a fact or a derived value of the brief, every beat id exists, and the beats of
  a series never go backwards. An exit comes after the entrance. An arrow or a highlight comes
  after the elements it follows.
- A region is inside the grid, and above the caption area: the last row allowed is the last whole
  row that ends above `caption_zone.top` (`grid_rows`).
- A series has one unit; bars always start at zero (the block has no axis to change).
- The number rule (G-7): a number in any text the model writes must be said in the line or be the
  on-screen text of a fact or a derived value.

**The layout check.** What the checks cannot know is how text fits and where it lands. The motion
service measures every text in the browser (`POST /layout`, `motion/src/blocks/report.ts`) at the
frames in `layout_frames`, and `layout_problems` turns that report into sentences: a text outside
the safe area, a text over the caption area, two texts of different elements that overlap, a text
smaller than 2 percent of the height, and what the service itself could not fit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Final

from app.services.callout_plan_writer import format_number
from app.services.graphics_templates import items_of, line_of_text, object_of
from app.services.number_words import numbers_in

# Stored in each scene, so a renderer can tell which library the scene was written for.
BLOCKS_VERSION: Final = 1

GRID: Final = 12
MAX_ELEMENTS: Final = 12
MAX_TEXT_BLOCKS: Final = 6
# A text smaller than this share of the height is reported by the layout check.
MIN_TEXT_SHARE: Final = 0.02
# Boxes closer than this many pixels to touching are not counted as overlapping (rounding).
EDGE_PIXELS: Final = 2
# The most problems that are kept and sent back to the model.
MAX_PROBLEMS: Final = 12

ID_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]{0,15}")
ROLES: Final = ("text", "muted", "accent", "positive", "negative", "number")
ALIGNS: Final = ("left", "center", "right")
STYLES: Final = ("title", "label", "body")
ORIENTATIONS: Final = ("vertical", "horizontal")

# The effects that change how a whole block is shown, and the ones a block draws itself.
WRAP_EFFECTS: Final = ("fade", "slide_up", "slide_left", "pop")
EFFECTS: Final = (*WRAP_EFFECTS, "grow", "draw", "count_up", "typewriter")
# The effects of an entrance, for each block. An exit takes the wrapping effects only.
ENTER_EFFECTS: Final = {
    "text": (*WRAP_EFFECTS, "typewriter"),
    "counter": (*WRAP_EFFECTS, "count_up"),
    "bar_series": (*WRAP_EFFECTS, "grow"),
    "line_series": ("draw", "fade"),
    "node": WRAP_EFFECTS,
    "arrow": (*WRAP_EFFECTS, "draw"),
    "table": WRAP_EFFECTS,
    "badge": (*WRAP_EFFECTS, "count_up"),
    "highlight": (*WRAP_EFFECTS, "draw"),
    "progress_ring": (*WRAP_EFFECTS, "grow", "draw", "count_up"),
}
BLOCKS: Final = tuple(ENTER_EFFECTS)
# The blocks that follow other elements and so have no region.
FOLLOWING: Final = ("arrow", "highlight")

TITLE_MAX_CHARS: Final = 40
LABEL_MAX_CHARS: Final = 24
BODY_MAX_CHARS: Final = 120
BAR_LABEL_MAX_CHARS: Final = 16
POINT_LABEL_MAX_CHARS: Final = 10
CELL_MAX_CHARS: Final = 20
TEXT_MAX_CHARS: Final = {"title": TITLE_MAX_CHARS, "label": LABEL_MAX_CHARS, "body": BODY_MAX_CHARS}

# The most text each limited field may have, by the name the model sees in the answer.
LIMIT_NAMES: Final = {
    "text, style title": TITLE_MAX_CHARS,
    "text, style label": LABEL_MAX_CHARS,
    "text, style body": BODY_MAX_CHARS,
    "counter.label": LABEL_MAX_CHARS,
    "bar_series.labels[]": BAR_LABEL_MAX_CHARS,
    "line_series.labels[]": POINT_LABEL_MAX_CHARS,
    "node.label": LABEL_MAX_CHARS,
    "badge.text": LABEL_MAX_CHARS,
    "table cell": CELL_MAX_CHARS,
}

# The keys of each block besides `id`, `block`, `enter`, `exit` and `region`: required, optional.
_KEYS: Final = {
    "text": (("style", "text"), ("align", "role")),
    "counter": (("value",), ("label", "align", "role")),
    "bar_series": (("values", "labels", "orientation"), ("emphasis",)),
    "line_series": (("values", "labels"), ("area",)),
    "node": (("label",), ("role",)),
    "arrow": (("from", "to"), ("role",)),
    "table": (("rows",), ("header",)),
    "badge": ((), ("value", "text", "role")),
    "highlight": (("target",), ("role",)),
    "progress_ring": (("value",), ("role",)),
}


def grid_rows(resolved: dict[str, Any]) -> int:
    """The last row of the grid that a region may reach: the last whole row that ends above the
    caption area (landscape 10, portrait 8).
    """
    area = resolved["safe_area"]
    cell = (int(area["bottom"]) - int(area["top"])) / GRID
    room = int(resolved["caption_zone"]["top"]) - int(area["top"])
    return max(0, min(GRID, int((room + 1e-6) // cell)))


class _Context:
    """What the checks of one scene read."""

    def __init__(self, line: str, resolved: dict[str, Any]) -> None:
        self.line = line
        self.rows = grid_rows(resolved)
        values = {**resolved["facts"], **resolved["derived"]}
        self.units = {key: str(item["unit"]) for key, item in values.items()}
        self.numbers = {key: Decimal(str(item["value"])) for key, item in values.items()}
        self.frames = {key: int(item["frame"]) for key, item in resolved["beats"].items()}
        allowed = numbers_in(line)
        for item in values.values():
            allowed |= numbers_in(str(item["display"]))
        self.allowed_numbers = allowed
        # The block of each element, from the first pass over the answer.
        self.blocks: dict[str, str] = {}
        # The frame at which each element first appears.
        self.first_frame: dict[str, int] = {}

    # --- ids ---

    def ref(self, value: object, name: str) -> str:
        """A fact or derived id of the brief."""
        if not isinstance(value, str) or value not in self.units:
            raise ValueError(f"The {name} {value!r} is not a fact or derived id of the brief.")
        return value

    def beat(self, value: object, name: str) -> str:
        if not isinstance(value, str) or value not in self.frames:
            raise ValueError(f"The {name} {value!r} is not a beat id of the brief.")
        return value

    def one_of(self, value: object, allowed: Sequence[str], name: str) -> str:
        if not isinstance(value, str) or value not in allowed:
            raise ValueError(f"The {name} was {value!r}; it must be one of {', '.join(allowed)}.")
        return value

    def element_id(self, value: object, name: str, *, placed: bool, by: str) -> str:
        """The id of another element of the scene. It must have a region when `placed`."""
        if not isinstance(value, str) or value not in self.blocks:
            raise ValueError(f"The {name} {value!r} is not the id of an element of the scene.")
        if value == by:
            raise ValueError(f"The {name} of {by} points at itself.")
        if placed and self.blocks[value] in FOLLOWING:
            raise ValueError(
                f"The {name} {value!r} is {self.blocks[value]}, which has no region to follow."
            )
        return value

    def same_unit(self, refs: Sequence[str], name: str) -> None:
        units = {self.units[ref] for ref in refs}
        if len(units) > 1:
            raise ValueError(
                f"The {name} mix the units {', '.join(sorted(units))}. They must all have one unit."
            )

    # --- text ---

    def words(self, value: object, name: str, max_chars: int) -> str:
        """A text the model writes: one line of at most `max_chars`, with no number the line does
        not say (G-7). It is never cut.
        """
        text = line_of_text(value, name, max_chars)
        unsaid = sorted(numbers_in(text) - self.allowed_numbers)
        if unsaid:
            raise ValueError(
                f'The {name} "{text}" shows the number {format_number(unsaid[0])}, which the '
                "line does not say. Every number on screen must come from the line."
            )
        return text

    # --- places and times ---

    def region(self, value: object, name: str) -> list[int]:
        cells = items_of(value, f"numbers in the region of {name}", 4, 4)
        if not all(isinstance(cell, int) and not isinstance(cell, bool) for cell in cells):
            raise ValueError(f"The region of {name} must be four whole numbers.")
        first_column, first_row, last_column, last_row = cells
        if not (1 <= first_column <= last_column <= GRID):
            raise ValueError(
                f"The columns of the region of {name} ({first_column} to {last_column}) must be "
                f"from 1 to {GRID}, first before last."
            )
        if not (1 <= first_row <= last_row <= self.rows):
            raise ValueError(
                f"The rows of the region of {name} ({first_row} to {last_row}) must be from 1 to "
                f"{self.rows}, first before last. The rows after row {self.rows} are the caption "
                "area."
            )
        return [first_column, first_row, last_column, last_row]

    def enter(self, value: object, name: str, block: str, parts: int | None) -> dict[str, Any]:
        """The entrance: one `beat` (`parts` None) or one beat for each of `parts` in `beats`.
        The beats of a series never go backwards.
        """
        given = object_of(value, f"entrance of {name}", ("effect",), ("beat", "beats"))
        effect = self.one_of(
            given["effect"], ENTER_EFFECTS[block], f"effect of the entrance of {name}"
        )
        if parts is None:
            if "beats" in given or "beat" not in given:
                raise ValueError(f'The entrance of {name} needs one "beat" (not "beats").')
            beat = self.beat(given["beat"], f"beat of the entrance of {name}")
            self.first_frame[name] = self.frames[beat]
            return {"beat": beat, "effect": effect}
        if "beat" in given or "beats" not in given:
            raise ValueError(
                f'The entrance of {name} needs "beats", one for each of its {parts} values.'
            )
        beats = [
            self.beat(beat, f"beat in the entrance of {name}")
            for beat in items_of(given["beats"], f"beats in the entrance of {name}", parts, parts)
        ]
        for earlier, later in zip(beats, beats[1:], strict=False):
            if self.frames[later] < self.frames[earlier]:
                raise ValueError(
                    f"The beats in the entrance of {name} go backwards: {later} comes before "
                    f"{earlier} in the line. They must follow the order of the line."
                )
        self.first_frame[name] = min(self.frames[beat] for beat in beats)
        return {"beats": beats, "effect": effect}

    def leave(self, value: object, name: str, last_enter_frame: int) -> dict[str, Any]:
        given = object_of(value, f"exit of {name}", ("beat", "effect"))
        effect = self.one_of(given["effect"], WRAP_EFFECTS, f"effect of the exit of {name}")
        beat = self.beat(given["beat"], f"beat of the exit of {name}")
        if self.frames[beat] <= last_enter_frame:
            raise ValueError(
                f"The exit of {name} (beat {beat}) must come after its entrance in the line."
            )
        return {"beat": beat, "effect": effect}


def _role(ctx: _Context, given: dict[str, Any], out: dict[str, Any], name: str) -> None:
    if "role" in given:
        out["role"] = ctx.one_of(given["role"], ROLES, f"role of {name}")


def _align(ctx: _Context, given: dict[str, Any], out: dict[str, Any], name: str) -> None:
    if "align" in given:
        out["align"] = ctx.one_of(given["align"], ALIGNS, f"align of {name}")


def _refs(ctx: _Context, value: object, name: str, least: int, most: int) -> list[str]:
    return [
        ctx.ref(ref, f"value in {name}")
        for ref in items_of(value, f"values of {name}", least, most)
    ]


def _labels(ctx: _Context, value: object, name: str, count: int, max_chars: int) -> list[str]:
    return [
        ctx.words(label, f"label {position + 1} of {name}", max_chars)
        for position, label in enumerate(items_of(value, f"labels of {name}", count, count))
    ]


# --- The blocks --------------------------------------------------------------------------------
# Each reads the keys of its block from `given` and returns them checked, plus the number of
# parts that its entrance has (None for a block that enters once).


def _text(ctx: _Context, name: str, given: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    style = ctx.one_of(given["style"], STYLES, f"style of {name}")
    out: dict[str, Any] = {
        "style": style,
        "text": ctx.words(given["text"], f"text of {name}", TEXT_MAX_CHARS[style]),
    }
    _align(ctx, given, out, name)
    _role(ctx, given, out, name)
    return out, None


def _counter(ctx: _Context, name: str, given: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    out: dict[str, Any] = {"value": ctx.ref(given["value"], f"value of {name}")}
    if "label" in given:
        out["label"] = ctx.words(given["label"], f"label of {name}", LABEL_MAX_CHARS)
    _align(ctx, given, out, name)
    _role(ctx, given, out, name)
    return out, None


def _bar_series(
    ctx: _Context, name: str, given: dict[str, Any]
) -> tuple[dict[str, Any], int | None]:
    values = _refs(ctx, given["values"], name, 2, 6)
    ctx.same_unit(values, f"values of {name}")
    out: dict[str, Any] = {
        "values": values,
        "labels": _labels(ctx, given["labels"], name, len(values), BAR_LABEL_MAX_CHARS),
        "orientation": ctx.one_of(given["orientation"], ORIENTATIONS, f"orientation of {name}"),
    }
    if "emphasis" in given:
        emphasis = [
            ctx.ref(ref, f"emphasis of {name}")
            for ref in items_of(given["emphasis"], f"emphasis of {name}", 0, len(values))
        ]
        stray = [ref for ref in emphasis if ref not in values]
        if stray:
            raise ValueError(
                f"The emphasis of {name} names {stray[0]}, which is not one of its values."
            )
        out["emphasis"] = emphasis
    return out, len(values)


def _line_series(
    ctx: _Context, name: str, given: dict[str, Any]
) -> tuple[dict[str, Any], int | None]:
    values = _refs(ctx, given["values"], name, 3, 12)
    ctx.same_unit(values, f"values of {name}")
    out: dict[str, Any] = {
        "values": values,
        "labels": _labels(ctx, given["labels"], name, len(values), POINT_LABEL_MAX_CHARS),
    }
    if "area" in given:
        if not isinstance(given["area"], bool):
            raise ValueError(f"The area of {name} must be true or false.")
        out["area"] = given["area"]
    return out, len(values)


def _node(ctx: _Context, name: str, given: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    out: dict[str, Any] = {"label": ctx.words(given["label"], f"label of {name}", LABEL_MAX_CHARS)}
    _role(ctx, given, out, name)
    return out, None


def _arrow(ctx: _Context, name: str, given: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    out: dict[str, Any] = {
        "from": ctx.element_id(given["from"], f"from of {name}", placed=True, by=name),
        "to": ctx.element_id(given["to"], f"to of {name}", placed=True, by=name),
    }
    _role(ctx, given, out, name)
    return out, None


def _cell(ctx: _Context, value: object, name: str) -> str | dict[str, str]:
    if isinstance(value, dict):
        return {"value": ctx.ref(object_of(value, name, ("value",))["value"], f"value of {name}")}
    if isinstance(value, str) and not value.strip():
        return ""
    return ctx.words(value, name, CELL_MAX_CHARS)


def _table(ctx: _Context, name: str, given: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    rows_in = items_of(given["rows"], f"rows of {name}", 1, 5)
    out: dict[str, Any] = {}
    width: int | None = None
    if "header" in given:
        header_in = items_of(given["header"], f"header of {name}", 1, 4)
        width = len(header_in)
        out["header"] = [
            ctx.words(cell, f"header cell {position + 1} of {name}", CELL_MAX_CHARS)
            for position, cell in enumerate(header_in)
        ]
    rows: list[list[Any]] = []
    for row_position, row_in in enumerate(rows_in):
        cells_in = items_of(row_in, f"cells of row {row_position + 1} of {name}", 1, 4)
        if width is None:
            width = len(cells_in)
        if len(cells_in) != width:
            raise ValueError(
                f"The rows of {name} must all have {width} cells; row {row_position + 1} has "
                f"{len(cells_in)}."
            )
        rows.append(
            [
                _cell(ctx, cell, f"cell {column + 1} of row {row_position + 1} of {name}")
                for column, cell in enumerate(cells_in)
            ]
        )
    out["rows"] = rows
    return out, None


def _badge(ctx: _Context, name: str, given: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    if ("value" in given) == ("text" in given):
        raise ValueError(f'The badge {name} needs either a "value" or a "text", not both.')
    out: dict[str, Any] = {}
    if "value" in given:
        out["value"] = ctx.ref(given["value"], f"value of {name}")
    else:
        out["text"] = ctx.words(given["text"], f"text of {name}", LABEL_MAX_CHARS)
    _role(ctx, given, out, name)
    return out, None


def _highlight(
    ctx: _Context, name: str, given: dict[str, Any]
) -> tuple[dict[str, Any], int | None]:
    out: dict[str, Any] = {
        "target": ctx.element_id(given["target"], f"target of {name}", placed=True, by=name)
    }
    _role(ctx, given, out, name)
    return out, None


def _progress_ring(
    ctx: _Context, name: str, given: dict[str, Any]
) -> tuple[dict[str, Any], int | None]:
    ref = ctx.ref(given["value"], f"value of {name}")
    if ctx.units[ref] != "percent" or not Decimal(0) <= ctx.numbers[ref] <= Decimal(100):
        raise ValueError(
            f"The ring {name} shows {ref}, which is not a percent from 0 to 100. A ring needs "
            "such a value."
        )
    out: dict[str, Any] = {"value": ref}
    _role(ctx, given, out, name)
    return out, None


_BLOCK_CHECKS: Final = {
    "text": _text,
    "counter": _counter,
    "bar_series": _bar_series,
    "line_series": _line_series,
    "node": _node,
    "arrow": _arrow,
    "table": _table,
    "badge": _badge,
    "highlight": _highlight,
    "progress_ring": _progress_ring,
}


# --- The scene ---------------------------------------------------------------------------------


def _first_pass(ctx: _Context, raw: list[Any]) -> None:
    """Reads every element's id and block, so an arrow can point at an element further on."""
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Element {position + 1} was not an object.")
        name = item.get("id")
        if not isinstance(name, str) or not ID_PATTERN.fullmatch(name):
            raise ValueError(
                f"Element {position + 1} has the id {name!r}; an id is 1 to 16 lowercase letters, "
                "digits or underscores, starting with a letter."
            )
        if name in ctx.blocks:
            raise ValueError(f"The id {name!r} is used by two elements.")
        block = item.get("block")
        if not isinstance(block, str) or block not in BLOCKS:
            raise ValueError(
                f"The block of {name} was {block!r}; it must be one of {', '.join(BLOCKS)}."
            )
        ctx.blocks[name] = block


def _element(ctx: _Context, item: dict[str, Any]) -> dict[str, Any]:
    name = str(item["id"])
    block = ctx.blocks[name]
    required, optional = _KEYS[block]
    placed = block not in FOLLOWING
    given = object_of(
        item,
        f"element {name}",
        ("id", "block", "enter", *(("region",) if placed else ()), *required),
        ("exit", *optional),
    )
    out: dict[str, Any] = {"id": name, "block": block}
    if placed:
        out["region"] = ctx.region(given["region"], name)
    fields, parts = _BLOCK_CHECKS[block](ctx, name, given)
    out.update(fields)
    out["enter"] = ctx.enter(given["enter"], name, block, parts)
    if block == "badge" and out["enter"]["effect"] == "count_up" and "value" not in out:
        raise ValueError(f"The badge {name} has a text, which cannot count up. Use another effect.")
    if "exit" in given:
        enter = out["enter"]
        beats = enter["beats"] if "beats" in enter else [enter["beat"]]
        out["exit"] = ctx.leave(given["exit"], name, max(ctx.frames[beat] for beat in beats))
    return out


def _check_following(ctx: _Context, elements: list[dict[str, Any]]) -> None:
    """An arrow or a highlight appears no earlier than the elements it follows."""
    for element in elements:
        if element["block"] == "arrow":
            targets = [element["from"], element["to"]]
        elif element["block"] == "highlight":
            targets = [element["target"]]
        else:
            continue
        frame = ctx.first_frame[element["id"]]
        for target in targets:
            if frame < ctx.first_frame[target]:
                raise ValueError(
                    f"The {element['block']} {element['id']} appears before {target}, which it "
                    "follows. Give it the same beat as that element or a later one."
                )


def check_scene(answer: dict[str, Any], line: str, resolved: dict[str, Any]) -> dict[str, Any]:
    """The model's answer as the stored input of `remotion_blocks` (§4.5.2): the library's version
    and the checked elements. Raises ValueError with a message fit for the user and for the
    model's corrected retry.
    """
    if not isinstance(answer, dict):
        raise ValueError("The answer was not a JSON object.")
    unknown = [key for key in answer if key != "elements"]
    if unknown:
        raise ValueError(f'The answer has "{unknown[0]}", which is not allowed there.')
    raw = items_of(answer.get("elements"), "elements", 1, MAX_ELEMENTS)
    ctx = _Context(line, resolved)
    _first_pass(ctx, raw)
    texts = sum(1 for block in ctx.blocks.values() if block == "text")
    if texts > MAX_TEXT_BLOCKS:
        raise ValueError(
            f"There were {texts} text elements; the most allowed is {MAX_TEXT_BLOCKS}."
        )
    elements = [_element(ctx, item) for item in raw]
    _check_following(ctx, elements)
    return {"blocks_version": BLOCKS_VERSION, "elements": elements}


# --- The layout check --------------------------------------------------------------------------


def layout_frames(scene: dict[str, Any], resolved: dict[str, Any]) -> list[int]:
    """The frames the layout is measured at: every beat the scene enters or leaves on, and the
    last frame (§4.5.2). Sorted, without repeats.
    """
    frames = {int(resolved["frames"]) - 1}
    for element in scene["elements"]:
        enter = element["enter"]
        beats = enter["beats"] if "beats" in enter else [enter["beat"]]
        if "exit" in element:
            beats = [*beats, element["exit"]["beat"]]
        frames.update(int(resolved["beats"][beat]["frame"]) for beat in beats)
    return sorted(frames)


def _overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    across = min(first["right"], second["right"]) - max(first["left"], second["left"])
    down = min(first["bottom"], second["bottom"]) - max(first["top"], second["top"])
    return across > EDGE_PIXELS and down > EDGE_PIXELS


def _quoted(item: dict[str, Any]) -> str:
    text = str(item["text"])
    shown = text if len(text) <= 30 else text[:29].rstrip() + "..."
    return f'"{shown}" ({item["element"]})'


def layout_problems(report: dict[str, Any], resolved: dict[str, Any]) -> list[str]:
    """The sentences that say what is wrong with the layout, from the motion service's report:
    a text outside the safe area, over the caption area, overlapping a text of another element,
    or smaller than 2 percent of the height; and what the service could not fit. Each problem is
    named once, at the first frame it is seen. At most `MAX_PROBLEMS`.
    """
    fps = int(resolved["fps"])
    area = resolved["safe_area"]
    caption = resolved["caption_zone"]
    least = MIN_TEXT_SHARE * int(resolved["height"])
    problems: list[str] = []
    seen: set[tuple[str, ...]] = set()

    def add(key: tuple[str, ...], sentence: str) -> None:
        if key not in seen:
            seen.add(key)
            problems.append(sentence)

    for issue in report.get("issues", []):
        add(("issue", str(issue["element"]), str(issue["message"])), str(issue["message"]))
    for entry in report.get("frames", []):
        at = f"at {int(entry['frame']) / fps:.1f} s"
        texts = entry["texts"]
        for item in texts:
            box = item["box"]
            element, part = str(item["element"]), str(item["part"])
            if item["size"] < least:
                add(
                    ("small", element, part),
                    f"The text {_quoted(item)} is only {item['size']} px high; it must be at "
                    f"least {least:.0f} px. Give it a larger region or fewer words.",
                )
            if (
                box["left"] < area["left"] - 1
                or box["right"] > area["right"] + 1
                or box["top"] < area["top"] - 1
                or box["bottom"] > area["bottom"] + 1
            ):
                add(
                    ("outside", element, part),
                    f"The text {_quoted(item)} is outside the safe area.",
                )
            if box["bottom"] > caption["top"] and box["top"] < caption["bottom"]:
                add(
                    ("caption", element, part),
                    f"The text {_quoted(item)} is over the caption area. Keep it higher.",
                )
        for position, first in enumerate(texts):
            for second in texts[position + 1 :]:
                if first["element"] != second["element"] and _overlap(first["box"], second["box"]):
                    pair = tuple(sorted((str(first["element"]), str(second["element"]))))
                    add(
                        ("overlap", *pair),
                        f"The text {_quoted(first)} overlaps the text {_quoted(second)} {at}. "
                        "Move one to another region or give them different beats.",
                    )
    return problems[:MAX_PROBLEMS]
