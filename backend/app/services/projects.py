"""Projects: creating them, editing them and the rules their values must follow.

ANALYSIS.md Section 4.4 gives the defaults an orientation fills in, and
Sections 3.7 and 5.3 give the rules (generation sizes are multiples of 64, output
sizes are even because H.264 needs it). All the rules live in `validate_project`,
so creating and editing share them. The messages are written for the user and are
returned as-is in the API's `{"detail": ...}` answers.

The orientation is fixed once a project exists. The sizes stay editable, but
both sizes must keep the orientation's shape (ITERATION_1_PHASES.md Phase 3).

A project keeps only its name, orientation, sizes, frame rate and story text (the
`script_text` column, shown as "Story"). The narration pipeline's other settings were
retired in PHASE-046.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.services import review_points

LANDSCAPE = "landscape"
PORTRAIT = "portrait"

DEFAULT_FPS: Final = 24

# How a project's story is spoken. Chosen when the project is created and never changed.
SPEECH_BOTH: Final = "both"
SPEECH_NO_DIALOGUE: Final = "no_dialogue"
SPEECH_NO_NARRATION: Final = "no_narration"
SPEECH_MODES: Final = (SPEECH_BOTH, SPEECH_NO_DIALOGUE, SPEECH_NO_NARRATION)

NAME_MAX_CHARS: Final = 200
SCRIPT_MAX_CHARS: Final = 100_000

SIZE_MIN: Final = 256
SIZE_MAX: Final = 3840
GENERATION_SIZE_MULTIPLE: Final = 64
FPS_MIN: Final = 12
FPS_MAX: Final = 60


@dataclass(frozen=True)
class OrientationDefaults:
    gen_width: int
    gen_height: int
    out_width: int
    out_height: int


# LTX's own presets, and the same size cropped by 8 px to a standard video size
# (ANALYSIS.md Section 4.4).
ORIENTATION_DEFAULTS: Final[Mapping[str, OrientationDefaults]] = {
    LANDSCAPE: OrientationDefaults(
        gen_width=1920, gen_height=1088, out_width=1920, out_height=1080
    ),
    PORTRAIT: OrientationDefaults(gen_width=1088, gen_height=1920, out_width=1080, out_height=1920),
}

# What a PATCH may change. The orientation, the speech mode and the id are not here. The review
# points (PHASE-041) are a list, checked by `_prepare_review_points`. The music switch
# (MUSIC-006) can be changed at any time.
_FIELD_LABELS: Final[Mapping[str, str]] = {
    "name": "Name",
    "gen_width": "Generation width",
    "gen_height": "Generation height",
    "out_width": "Output width",
    "out_height": "Output height",
    "fps": "Frame rate",
    "script_text": "Story",
    "review_points": "Review points",
    "music_enabled": "Music",
}
_NULLABLE_FIELDS: Final = frozenset(("script_text",))


class ProjectValidationError(ValueError):
    """A project value that breaks a rule. The message is meant to be shown to the user."""


def _check_whole_range(label: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise ProjectValidationError(f"{label} must be from {low} to {high}.")


def _check_orientation_shape(orientation: str, what: str, width: int, height: int) -> None:
    if orientation == LANDSCAPE and width <= height:
        raise ProjectValidationError(
            f"{what} must be wider than tall for a landscape project (now {width} x {height})."
        )
    if orientation == PORTRAIT and height <= width:
        raise ProjectValidationError(
            f"{what} must be taller than wide for a portrait project (now {width} x {height})."
        )


def validate_project(project: Project) -> None:
    """Checks every rule on the project's current values. Raises ProjectValidationError."""
    name = project.name
    if not 1 <= len(name) <= NAME_MAX_CHARS:
        raise ProjectValidationError(f"Name must be 1 to {NAME_MAX_CHARS} characters.")

    if project.orientation not in ORIENTATION_DEFAULTS:
        raise ProjectValidationError("Orientation must be landscape or portrait.")

    for field in ("gen_width", "gen_height"):
        value = getattr(project, field)
        label = _FIELD_LABELS[field]
        _check_whole_range(label, value, SIZE_MIN, SIZE_MAX)
        if value % GENERATION_SIZE_MULTIPLE != 0:
            raise ProjectValidationError(
                f"{label} must be a multiple of {GENERATION_SIZE_MULTIPLE}."
            )
    for field in ("out_width", "out_height"):
        value = getattr(project, field)
        label = _FIELD_LABELS[field]
        _check_whole_range(label, value, SIZE_MIN, SIZE_MAX)
        if value % 2 != 0:
            raise ProjectValidationError(f"{label} must be an even number.")
    _check_orientation_shape(
        project.orientation, "Generation size", project.gen_width, project.gen_height
    )
    _check_orientation_shape(
        project.orientation, "Output size", project.out_width, project.out_height
    )

    if not FPS_MIN <= project.fps <= FPS_MAX:
        raise ProjectValidationError(
            f"{_FIELD_LABELS['fps']} must be a whole number from {FPS_MIN} to {FPS_MAX}."
        )

    if project.script_text is not None and len(project.script_text) > SCRIPT_MAX_CHARS:
        raise ProjectValidationError(f"The story must be at most {SCRIPT_MAX_CHARS:,} characters.")


def _normalise_name(value: str) -> str:
    return value.strip()


def _normalise_script(value: str | None) -> str | None:
    """Keeps the story exactly as pasted: no trimming, no line-ending changes.

    Only a story that is nothing but whitespace is stored as NULL.
    """
    if value is None or not value.strip():
        return None
    return value


async def create_project(
    session: AsyncSession, name: str, orientation: str, speech_mode: str = SPEECH_BOTH
) -> Project:
    """Creates a project with the orientation's defaults (ANALYSIS.md Section 4.4) and commits.
    The speech mode is set here and never changed afterwards.
    """
    if orientation not in ORIENTATION_DEFAULTS:
        raise ProjectValidationError("Orientation must be landscape or portrait.")
    if speech_mode not in SPEECH_MODES:
        raise ProjectValidationError("Speech mode must be both, no_dialogue or no_narration.")
    sizes = ORIENTATION_DEFAULTS[orientation]

    # Every default is set here, rather than left to the column defaults, because the
    # column defaults only apply at INSERT time and validation runs before that.
    project = Project(
        name=_normalise_name(name),
        orientation=orientation,
        gen_width=sizes.gen_width,
        gen_height=sizes.gen_height,
        out_width=sizes.out_width,
        out_height=sizes.out_height,
        fps=DEFAULT_FPS,
        speech_mode=speech_mode,
        review_points=[],
        music_enabled=True,
    )
    validate_project(project)
    session.add(project)
    await session.commit()
    return project


async def get_project(session: AsyncSession, project_id: int) -> Project | None:
    return await session.get(Project, project_id)


async def list_projects(session: AsyncSession) -> list[Project]:
    """All projects, newest first."""
    statement = select(Project).order_by(Project.created_at.desc(), Project.id.desc())
    return list((await session.execute(statement)).scalars())


async def update_project(
    session: AsyncSession, project: Project, changes: Mapping[str, object]
) -> Project:
    """Applies the changes, validates the merged result and commits.

    If any rule fails, nothing is saved and ProjectValidationError is raised.
    The project instance must not be used after a failure.
    """
    unknown = [field for field in changes if field not in _FIELD_LABELS]
    if unknown:
        raise ProjectValidationError(f"{unknown[0]} cannot be changed.")

    try:
        for field, value in changes.items():
            setattr(project, field, _prepare_value(field, value))
        validate_project(project)
    except ProjectValidationError:
        # Nothing has been flushed yet, so this discards the in-memory changes.
        await session.rollback()
        raise
    await session.commit()
    return project


def _prepare_value(field: str, value: object) -> object:
    """Checks a changed value for emptiness and applies the field's text normalisation."""
    if value is None and field not in _NULLABLE_FIELDS:
        raise ProjectValidationError(f"{_FIELD_LABELS[field]} cannot be empty.")
    if field == "name":
        return _normalise_name(str(value))
    if field == "script_text":
        return _normalise_script(value if isinstance(value, str) else None)
    if field == "review_points":
        return _prepare_review_points(value)
    if field == "music_enabled" and not isinstance(value, bool):
        raise ProjectValidationError("Music must be on or off.")
    return value


def _prepare_review_points(value: object) -> list[str]:
    """The review points to store: known keys, in the order of the pipeline, without repeats."""
    if not isinstance(value, list) or not all(isinstance(key, str) for key in value):
        raise ProjectValidationError("Review points must be a list of names.")
    unknown = review_points.unknown_keys(value)
    if unknown:
        raise ProjectValidationError(f"There is no review point {unknown[0]!r}.")
    return review_points.normalize(value)
