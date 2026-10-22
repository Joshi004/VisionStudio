"""Reading the provenance of story artifacts (D-3, PHASE-039).

Every stage row records, in `inputs.artifacts`, the upstream rows it was built from. Out of date
is worked out on every read by comparing that record with the newest upstream row.

"Accept as is" (PHASE-039) adds a new version of an artifact that has the same content as the
one it replaces, with `inputs` rebuilt from what is current. It records `inputs.accepted`:

    {"from_id": 12, "from_version": 2, "stands_for": [12, 9]}

`stands_for` lists the ids of the earlier rows whose content this row repeats exactly (it is
empty when the content changed while accepting). Whatever was built from one of those rows
is still built from this content, so `same_row` treats them as the same row. Nothing is
stored beyond that record.
"""

from __future__ import annotations

from typing import Any, Final, Protocol

ACCEPTED_KEY: Final = "accepted"


class _Row(Protocol):
    id: int
    version: int
    inputs: Any
    content: Any
    source: str


def stands_for(row: _Row) -> set[int]:
    """The ids of the earlier rows whose content `row` repeats exactly, because the user
    accepted them as they were. Empty for a row that was not accepted.
    """
    inputs = row.inputs
    accepted = inputs.get(ACCEPTED_KEY) if isinstance(inputs, dict) else None
    ids = accepted.get("stands_for") if isinstance(accepted, dict) else None
    if not isinstance(ids, list):
        return set()
    return {value for value in ids if isinstance(value, int) and not isinstance(value, bool)}


def same_row(recorded: dict[str, Any] | None, newest: _Row | None) -> bool:
    """Whether an artifact record (`{"kind", "id", "version"}`) says that `newest`, or a row
    `newest` stands for, is what something was built from. A record with no id (a row made
    before ids were recorded) is compared by version.
    """
    if recorded is None or newest is None:
        return False
    recorded_id = recorded.get("id")
    if isinstance(recorded_id, int) and not isinstance(recorded_id, bool):
        return recorded_id == newest.id or recorded_id in stands_for(newest)
    return recorded.get("version") == newest.version


def same_id(recorded_id: Any, newest: _Row | None) -> bool:
    """`same_row` for a bare row id (a foreign key column, such as `shot_prompt_id`)."""
    if newest is None or not isinstance(recorded_id, int) or isinstance(recorded_id, bool):
        return False
    return recorded_id == newest.id or recorded_id in stands_for(newest)


def accepted_inputs(inputs: dict[str, Any], previous: _Row, content: Any) -> dict[str, Any]:
    """`inputs` for a row that accepts `previous` as it is: the rebuilt `inputs` plus the
    record of what was accepted. `stands_for` is filled only when `content` is the content of
    `previous`.
    """
    same = content == previous.content
    ids = [previous.id, *sorted(stands_for(previous))] if same else []
    return {
        **inputs,
        ACCEPTED_KEY: {
            "from_id": previous.id,
            "from_version": previous.version,
            "stands_for": ids,
        },
    }
