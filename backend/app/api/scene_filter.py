"""What the shot-stage lists share: which scenes send their shots, and a summary of every scene.

A project can hold hundreds of shots. The pages that list them show one scene at a time, so
each list can be asked for the shots of one scene (`?scene_id=`), or for no shots at all
(`?shots=false`). Every scene is still listed, with a `summary` that counts all of its shots,
so a collapsed scene can show where it stands without its shots being sent.

With neither parameter every scene sends its shots, as before.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from app.jobs import store

# The id of a scene, as the lists give it. The limit only keeps a request from being huge.
SceneIdQuery = Annotated[
    str | None,
    Query(
        max_length=200,
        description="Send the shots of this scene only. The other scenes are listed without shots.",
    ),
]
ShotsQuery = Annotated[
    bool,
    Query(description="False: list the scenes without any shots (their summaries only)."),
]


class SceneShotsSummaryOut(BaseModel):
    """How the shots of one scene stand. It counts every shot, whether or not they are sent."""

    total: int
    # The number of shots in each status the stage has.
    by_status: dict[str, int]
    # Shots whose job is waiting or running.
    active: int
    # Shots the scene's button would start now.
    todo: int


class DefinitionsSummaryOut(SceneShotsSummaryOut):
    """The summary of the shot definitions, which also names the shots the user wrote."""

    # Shots whose newest definition was written by the user: they are only defined again by
    # their own button.
    manual_shot_ids: list[str]


def includes_shots(entry_id: str, scene_id: str | None, shots: bool) -> bool:
    """True when the scene with this id sends its shots."""
    if scene_id is not None:
        return entry_id == scene_id
    return shots


def is_active(job: object | None) -> bool:
    """True when the job (any row with a `status`) is waiting or running."""
    return job is not None and getattr(job, "status", None) in store.ACTIVE_STATUSES


def summarize[T](
    shots: Iterable[T],
    *,
    status: Callable[[T], str],
    active: Callable[[T], bool],
    todo: Callable[[T], bool],
) -> SceneShotsSummaryOut:
    """Counts the shots of one scene."""
    items = list(shots)
    return SceneShotsSummaryOut(
        total=len(items),
        by_status=dict(Counter(status(item) for item in items)),
        active=sum(1 for item in items if active(item)),
        todo=sum(1 for item in items if todo(item)),
    )
