"""Pure functions for the recorded GPU API (ANALYSIS.md Section 6.5).

No network and no database here: fingerprints, the list of operations by tag
and the difference between two versions of a document. `providers/contract_guard.py`
fetches and stores; this module only looks at JSON that is already in memory.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

HASH_PREFIX = "sha256:"
MAX_DIFF_ENTRIES = 200
MAX_VALUE_CHARS = 300
MAX_TEXT_DIFF_LINES = 40

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NO_TAG = "Other"


# --- Fingerprint -----------------------------------------------------------------


def canonical_json(body: dict[str, Any]) -> bytes:
    """Keys sorted, no extra spacing, and without the top-level `servers` entry.

    `servers` holds the address the document was fetched through, so it must
    not make the same API look different after a new tunnel address.
    """
    without_servers = {key: value for key, value in body.items() if key != "servers"}
    text = json.dumps(without_servers, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def fingerprint(body: dict[str, Any]) -> tuple[str, str | None]:
    """Returns `(fingerprint, server_content_hash)`.

    The document's own top-level `content_hash` is the fingerprint when it is a
    non-empty string, because the server's hash ignores things like generation
    timestamps. Otherwise it is the SHA-256 of the canonical JSON.
    """
    content_hash = body.get("content_hash")
    if isinstance(content_hash, str) and content_hash.strip():
        value = content_hash.strip()
        return value, value
    return HASH_PREFIX + hashlib.sha256(canonical_json(body)).hexdigest(), None


def api_version(body: dict[str, Any]) -> str | None:
    """The guide's `api_version`, or else the OpenAPI document's `info.version`."""
    version = body.get("api_version")
    if isinstance(version, str) and version:
        return version
    info = body.get("info")
    if isinstance(info, dict):
        version = info.get("version")
        if isinstance(version, str) and version:
            return version
    return None


# --- Operations ------------------------------------------------------------------


def is_openapi(body: dict[str, Any]) -> bool:
    has_version = isinstance(body.get("openapi"), str) or isinstance(body.get("swagger"), str)
    return has_version and isinstance(body.get("paths"), dict)


@dataclass(frozen=True)
class Operation:
    method: str  # upper case, for example "POST"
    path: str
    summary: str | None


@dataclass(frozen=True)
class TagGroup:
    tag: str
    operations: tuple[Operation, ...]


def _iter_operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every `(method, path, operation object)` in the spec's paths, in document order."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return found
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            operation = item.get(method)
            if isinstance(operation, dict):
                found.append((method.upper(), str(path), operation))
    return found


def operation_count(spec: dict[str, Any]) -> int:
    return len(_iter_operations(spec))


def operations_by_tag(spec: dict[str, Any]) -> list[TagGroup]:
    """Operations grouped by tag: the spec's own tag order, then any others, "Other" last.

    An operation with several tags is listed under each of them.
    """
    grouped: dict[str, list[Operation]] = {}
    for method, path, operation in _iter_operations(spec):
        summary = operation.get("summary")
        item = Operation(
            method=method, path=path, summary=summary if isinstance(summary, str) else None
        )
        tags = operation.get("tags")
        names = [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
        for name in names or [_NO_TAG]:
            grouped.setdefault(name, []).append(item)

    declared: list[str] = []
    for tag in spec.get("tags", []) if isinstance(spec.get("tags"), list) else []:
        name = tag.get("name") if isinstance(tag, dict) else None
        if isinstance(name, str) and name in grouped and name not in declared:
            declared.append(name)
    others = [name for name in grouped if name not in declared and name != _NO_TAG]
    order = [*declared, *others, *([_NO_TAG] if _NO_TAG in grouped else [])]
    return [TagGroup(tag=name, operations=tuple(grouped[name])) for name in order]


# --- Difference ------------------------------------------------------------------


@dataclass(frozen=True)
class DiffEntry:
    path: str
    kind: Literal["added", "removed", "changed"]
    before: str | None
    after: str | None
    # A line diff, only when both sides are multi-line text (the guide's markdown).
    text_diff: tuple[str, ...] | None


@dataclass(frozen=True)
class OpenApiChanges:
    operations_added: tuple[str, ...]
    operations_removed: tuple[str, ...]
    operations_changed: tuple[str, ...]
    schemas_added: tuple[str, ...]
    schemas_removed: tuple[str, ...]
    schemas_changed: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.operations_added,
                self.operations_removed,
                self.operations_changed,
                self.schemas_added,
                self.schemas_removed,
                self.schemas_changed,
            )
        )


@dataclass(frozen=True)
class ContractDiff:
    entries: tuple[DiffEntry, ...]
    truncated: bool
    openapi: OpenApiChanges | None


@dataclass(frozen=True)
class _RawChange:
    path: str
    kind: Literal["added", "removed", "changed"]
    before: Any
    after: Any


def diff_documents(old: dict[str, Any], new: dict[str, Any]) -> ContractDiff:
    """What differs between two versions of a document, path by path.

    The top-level `servers` entry is ignored. At most `MAX_DIFF_ENTRIES` entries
    are returned, and `truncated` says whether there were more.
    """
    old_body = {key: value for key, value in old.items() if key != "servers"}
    new_body = {key: value for key, value in new.items() if key != "servers"}

    changes: list[_RawChange] = []
    _walk("", old_body, new_body, changes)

    shown = changes[:MAX_DIFF_ENTRIES]
    entries = tuple(_to_entry(change) for change in shown)
    openapi = (
        _openapi_changes(old_body, new_body)
        if is_openapi(old_body) and is_openapi(new_body)
        else None
    )
    return ContractDiff(entries=entries, truncated=len(changes) > MAX_DIFF_ENTRIES, openapi=openapi)


def _join_path(parent: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if _IDENTIFIER.fullmatch(key):
        return f"{parent}.{key}" if parent else key
    return f"{parent}[{json.dumps(key, ensure_ascii=False)}]"


def _walk(path: str, old: Any, new: Any, changes: list[_RawChange]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key, old_value in old.items():
            child = _join_path(path, key)
            if key not in new:
                changes.append(_RawChange(child, "removed", old_value, None))
            else:
                _walk(child, old_value, new[key], changes)
        for key, new_value in new.items():
            if key not in old:
                changes.append(_RawChange(_join_path(path, key), "added", None, new_value))
    elif isinstance(old, list) and isinstance(new, list):
        for index in range(min(len(old), len(new))):
            _walk(_join_path(path, index), old[index], new[index], changes)
        for index in range(len(new), len(old)):
            changes.append(_RawChange(_join_path(path, index), "removed", old[index], None))
        for index in range(len(old), len(new)):
            changes.append(_RawChange(_join_path(path, index), "added", None, new[index]))
    elif type(old) is not type(new) or old != new:
        changes.append(_RawChange(path, "changed", old, new))


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > MAX_VALUE_CHARS:
        return text[:MAX_VALUE_CHARS] + "…"
    return text


def _text_diff(old: Any, new: Any) -> tuple[str, ...] | None:
    if not (isinstance(old, str) and isinstance(new, str)):
        return None
    if "\n" not in old and "\n" not in new:
        return None
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=1))[
        2:
    ]  # the first two lines are the "---" and "+++" file headers
    shown = [
        line if len(line) <= MAX_VALUE_CHARS else line[:MAX_VALUE_CHARS] + "…"
        for line in lines[:MAX_TEXT_DIFF_LINES]
    ]
    if len(lines) > MAX_TEXT_DIFF_LINES:
        shown.append(f"… {len(lines) - MAX_TEXT_DIFF_LINES} more lines not shown")
    return tuple(shown)


def _to_entry(change: _RawChange) -> DiffEntry:
    return DiffEntry(
        path=change.path,
        kind=change.kind,
        before=None if change.kind == "added" else _short(change.before),
        after=None if change.kind == "removed" else _short(change.after),
        text_diff=_text_diff(change.before, change.after) if change.kind == "changed" else None,
    )


def _same(a: Any, b: Any) -> bool:
    """Equal as JSON: key order does not matter, and 1 is not 1.0 or true."""
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
        b, sort_keys=True, ensure_ascii=False
    )


def _compare_named(
    old: dict[str, Any], new: dict[str, Any]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """`(added, removed, changed)` names between two dicts of named objects."""
    added = tuple(sorted(name for name in new if name not in old))
    removed = tuple(sorted(name for name in old if name not in new))
    changed = tuple(sorted(name for name in old if name in new and not _same(old[name], new[name])))
    return added, removed, changed


def _operations_by_key(spec: dict[str, Any]) -> dict[str, Any]:
    return {f"{method} {path}": operation for method, path, operation in _iter_operations(spec)}


def _schemas(spec: dict[str, Any]) -> dict[str, Any]:
    components = spec.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    return schemas if isinstance(schemas, dict) else {}


def _openapi_changes(old: dict[str, Any], new: dict[str, Any]) -> OpenApiChanges:
    op_added, op_removed, op_changed = _compare_named(
        _operations_by_key(old), _operations_by_key(new)
    )
    schema_added, schema_removed, schema_changed = _compare_named(_schemas(old), _schemas(new))
    return OpenApiChanges(
        operations_added=op_added,
        operations_removed=op_removed,
        operations_changed=op_changed,
        schemas_added=schema_added,
        schemas_removed=schema_removed,
        schemas_changed=schema_changed,
    )
