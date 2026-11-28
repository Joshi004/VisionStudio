"""A footage round on disk: the brief (read only) and the results the tool writes (§4.3, §4.5).

Every write goes through this module. It writes only inside `results/<mark_id>/` of the round,
only for a mark that is in the brief, and only under names the tool makes itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from ..rounds import (
    DATE_TEXT,
    TEXT_LIMITS,
    Refused,
    _clean,
    _unlink_own,
    _write_atomic,
    now_utc_text,
)
from . import (
    BRIEF_SCHEMA,
    BRIEF_VERSION,
    ON_SCREEN_TEXT,
    RESULT_SCHEMA,
    RESULT_VERSION,
    SAME_EVENT,
    STATUSES,
    STATUSES_WITH_PIECES,
    STILL_KINDS,
    TIERS,
    TOOL_NAME,
    TOOL_VERSION,
)

MARK_ID: Final = re.compile(r"^f\d+$")
PIECE_ID: Final = re.compile(r"^p[1-9]$")

# Longest text the tool stores for each flag (the shared limits plus the footage ones).
LIMITS: Final = {
    **TEXT_LIMITS,
    "what_it_shows": 1000,
    "licence": 200,
    "event_date": 10,
}
MAX_ATTEMPTS: Final = 40
DEFAULT_MAX_PIECES: Final = 3


def file_names(piece_id: str) -> dict[str, str]:
    """The only file names the tool makes for one piece. An image keeps its own type, so it is
    `.jpg` or `.png`; FTG-009 adds the video and its strip.
    """
    return {
        "image": f"{piece_id}.png",
        "image_jpeg": f"{piece_id}.jpg",
        "text_copy": f"{piece_id}.txt",
        "source_copy": f"{piece_id}.pdf",
    }


@dataclass(frozen=True)
class Described:
    """What the agent says about a piece. The tool only checks the values (§4.6)."""

    tier: str
    publisher: str
    what_it_shows: str
    same_event: str
    on_screen_text: str
    title: str | None = None
    published: str | None = None
    event_date: str | None = None
    licence: str | None = None
    licence_url: str | None = None
    notes: str = ""


def _clean_date(label: str, value: str | None) -> str | None:
    text = _clean(label, value, 10)
    if text is None:
        return None
    if not DATE_TEXT.match(text):
        raise Refused(f"{label} must be a date written YYYY-MM-DD.")
    try:
        date.fromisoformat(text)
    except ValueError as error:
        raise Refused(f"{label} is not a real date.") from error
    return text


def check_described(described: Described) -> Described:
    """Check the descriptive flags and return them tidied."""
    if described.tier not in TIERS:
        raise Refused(f"tier must be one of: {', '.join(TIERS)}.")
    if described.same_event not in SAME_EVENT:
        raise Refused(f"same-event must be one of: {', '.join(SAME_EVENT)}.")
    if described.on_screen_text not in ON_SCREEN_TEXT:
        raise Refused(f"on-screen-text must be one of: {', '.join(ON_SCREEN_TEXT)}.")
    licence_url = _clean("licence-url", described.licence_url, LIMITS["url"])
    if licence_url is not None and not licence_url.lower().startswith(("http://", "https://")):
        raise Refused("licence-url must start with http:// or https://.")
    notes = described.notes.strip()
    if len(notes) > LIMITS["notes"]:
        raise Refused(f"notes is too long (the limit is {LIMITS['notes']} characters).")
    return Described(
        tier=described.tier,
        publisher=_clean("publisher", described.publisher, LIMITS["publisher"], required=True)
        or "",
        what_it_shows=_clean(
            "what-it-shows", described.what_it_shows, LIMITS["what_it_shows"], required=True
        )
        or "",
        same_event=described.same_event,
        on_screen_text=described.on_screen_text,
        title=_clean("title", described.title, LIMITS["title"]),
        published=_clean_date("published", described.published),
        event_date=_clean_date("event-date", described.event_date),
        licence=_clean("licence", described.licence, LIMITS["licence"]),
        licence_url=licence_url,
        notes=notes,
    )


def piece_entry(
    *,
    piece_id: str,
    kind: str,
    described: Described,
    url: str,
    final_url: str,
    title: str | None,
    capture: dict[str, Any],
) -> dict[str, Any]:
    """One entry of `pieces` (§4.6). `capture` is the block only the tool makes."""
    return {
        "id": piece_id,
        "kind": kind,
        "tier": described.tier,
        "source": {
            "url": url,
            "final_url": final_url,
            "publisher": described.publisher,
            "title": described.title if described.title is not None else title,
            "published": described.published,
            "retrieved_at": now_utc_text(),
            "licence": described.licence,
            "licence_url": described.licence_url,
        },
        "what_it_shows": described.what_it_shows,
        "same_event": described.same_event,
        "event_date": described.event_date,
        "on_screen_text": described.on_screen_text,
        "capture": {"tool": TOOL_NAME, "tool_version": TOOL_VERSION, **capture},
        "agent_notes": described.notes,
    }


@dataclass(frozen=True)
class Captured:
    """What a capture made: the entry for `result.json`, its files, and lines to tell the agent."""

    entry: dict[str, Any]
    files: dict[str, bytes]
    notes: list[str]


class FootageRound:
    """A footage round folder. Reads the brief, never writes it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.brief = self._read_brief()

    # --- The brief -------------------------------------------------------------------------

    def _read_brief(self) -> dict[str, Any]:
        brief_dir = self.root / "brief"
        path = brief_dir / "footage.json"
        if not path.is_file() or path.is_symlink():
            if (brief_dir / "claims.json").exists():
                raise Refused(
                    f"{self.root} is an evidence round. Use visio-evidence-capture here; "
                    "visio-footage-capture is for footage rounds."
                )
            raise Refused(
                f"{self.root} is not a footage round: brief/footage.json is missing. Run the "
                "tool inside the round folder, or pass --round."
            )
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Refused(f"brief/footage.json cannot be read: {error}") from error
        if (
            not isinstance(brief, dict)
            or brief.get("schema") != BRIEF_SCHEMA
            or brief.get("version") != BRIEF_VERSION
        ):
            raise Refused("brief/footage.json is not a version 1 footage brief.")
        marks = brief.get("marks")
        project = brief.get("project")
        if (
            not isinstance(brief.get("round_id"), str)
            or not isinstance(marks, list)
            or not isinstance(project, dict)
            or project.get("orientation") not in ("landscape", "portrait")
        ):
            raise Refused("brief/footage.json is incomplete: round_id, project or marks is wrong.")
        for mark in marks:
            if not isinstance(mark, dict) or not MARK_ID.match(str(mark.get("id"))):
                raise Refused("brief/footage.json has a mark without a valid id.")
        return brief

    @property
    def round_id(self) -> str:
        return self.brief["round_id"]

    @property
    def orientation(self) -> str:
        return self.brief["project"]["orientation"]

    @property
    def max_pieces(self) -> int:
        value = (self.brief.get("rules") or {}).get("max_pieces_per_mark")
        return value if isinstance(value, int) and 1 <= value <= 9 else DEFAULT_MAX_PIECES

    @property
    def mark_ids(self) -> list[str]:
        return [mark["id"] for mark in self.brief["marks"]]

    def mark(self, mark_id: str) -> dict[str, Any]:
        if not MARK_ID.match(mark_id) or mark_id not in self.mark_ids:
            raise Refused(f"{mark_id} is not a mark of this round. Marks: {self._mark_list()}.")
        return next(item for item in self.brief["marks"] if item["id"] == mark_id)

    def _mark_list(self) -> str:
        return ", ".join(self.mark_ids) or "none"

    # --- Folders ---------------------------------------------------------------------------

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    def mark_dir(self, mark_id: str, *, create: bool) -> Path:
        """The folder of one mark. Refuses a link or anything outside the round."""
        self.mark(mark_id)
        results = self.results_dir
        if results.is_symlink() or (results.exists() and not results.is_dir()):
            raise Refused("results/ is a link or not a folder.")
        folder = results / mark_id
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise Refused(f"results/{mark_id} is a link or not a folder.")
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        if folder.exists() and not folder.resolve().is_relative_to(self.root):
            raise Refused(f"results/{mark_id} is outside the round.")
        return folder

    @staticmethod
    def check_piece_id(piece_id: str) -> None:
        if not PIECE_ID.match(piece_id):
            raise Refused("The piece id must look like p1, p2, ... (up to p9).")

    # --- Results ---------------------------------------------------------------------------

    def load_result(self, mark_id: str) -> dict[str, Any] | None:
        """The mark's `result.json`, or None when there is none yet."""
        path = self.mark_dir(mark_id, create=False) / "result.json"
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise Refused(f"results/{mark_id}/result.json is a link or not a file.")
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Refused(f"results/{mark_id}/result.json cannot be read: {error}") from error
        if not isinstance(result, dict) or result.get("mark_id") != mark_id:
            raise Refused(f"results/{mark_id}/result.json is not this mark's result.")
        if not isinstance(result.get("pieces"), list) or not isinstance(
            result.get("attempts"), list
        ):
            raise Refused(f"results/{mark_id}/result.json is damaged: delete it and start again.")
        return result

    def new_result(self, mark_id: str) -> dict[str, Any]:
        # The status stays null until `report` sets it: `validate` fails on a null status.
        return {
            "schema": RESULT_SCHEMA,
            "version": RESULT_VERSION,
            "round_id": self.round_id,
            "mark_id": mark_id,
            "status": None,
            "summary": "",
            "attempts": [],
            "pieces": [],
        }

    def result_or_new(self, mark_id: str) -> dict[str, Any]:
        return self.load_result(mark_id) or self.new_result(mark_id)

    def save_result(self, mark_id: str, result: dict[str, Any]) -> None:
        folder = self.mark_dir(mark_id, create=True)
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        _write_atomic(folder / "result.json", text.encode("utf-8"))

    def check_room(self, mark_id: str, piece_id: str) -> None:
        """Refuse early (before a capture is made) when this piece cannot be added."""
        self.check_piece_id(piece_id)
        result = self.load_result(mark_id)
        others = [
            item for item in (result["pieces"] if result else []) if item.get("id") != piece_id
        ]
        if len(others) >= self.max_pieces:
            raise Refused(
                f"Mark {mark_id} already has {len(others)} pieces, and the limit is "
                f"{self.max_pieces}. Remove one first (remove --mark {mark_id} --piece ...), or "
                "replace one by using its id."
            )

    def store_piece(
        self, mark_id: str, entry: dict[str, Any], files: dict[str, bytes]
    ) -> dict[str, Any]:
        """Write the files of a piece, then its entry. An entry with the same id is replaced, and
        files of the old one that the new one does not use are removed. Returns the saved result.
        """
        piece_id = entry["id"]
        self.check_piece_id(piece_id)
        if entry["kind"] not in STILL_KINDS:
            raise Refused(f"kind must be one of: {', '.join(STILL_KINDS)}.")
        self.check_room(mark_id, piece_id)
        result = self.result_or_new(mark_id)
        folder = self.mark_dir(mark_id, create=True)
        names = set(file_names(piece_id).values())
        if not set(files) <= names:
            raise Refused("Internal error: a file name that the tool does not make.")
        for name, data in files.items():
            _write_atomic(folder / name, data)
        for stale in names - set(files):
            _unlink_own(folder / stale)
        position = next(
            (i for i, item in enumerate(result["pieces"]) if item.get("id") == piece_id), None
        )
        if position is None:
            result["pieces"].append(entry)
        else:
            result["pieces"][position] = entry
        # A status that needs no pieces no longer fits. The agent reports it again.
        if result["status"] not in STATUSES_WITH_PIECES:
            result["status"] = None
        self.save_result(mark_id, result)
        return result

    def remove_piece(self, mark_id: str, piece_id: str) -> dict[str, Any]:
        self.check_piece_id(piece_id)
        result = self.load_result(mark_id)
        if result is None or not any(item.get("id") == piece_id for item in result["pieces"]):
            raise Refused(f"Mark {mark_id} has no piece {piece_id}.")
        result["pieces"] = [item for item in result["pieces"] if item.get("id") != piece_id]
        folder = self.mark_dir(mark_id, create=False)
        for name in file_names(piece_id).values():
            _unlink_own(folder / name)
        if not result["pieces"] and result["status"] in STATUSES_WITH_PIECES:
            result["status"] = None
        self.save_result(mark_id, result)
        return result

    def report(
        self,
        mark_id: str,
        *,
        status: str,
        summary: str,
        attempts: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """Set the mark's status and summary, and add attempts. §4.6 rules apply."""
        if status not in STATUSES:
            raise Refused(f"status must be one of: {', '.join(STATUSES)}.")
        text = _clean("summary", summary, LIMITS["summary"], required=True) or ""
        result = self.result_or_new(mark_id)
        count = len(result["pieces"])
        if status in STATUSES_WITH_PIECES and count == 0:
            raise Refused(
                f"Status {status} needs at least one piece. Capture it first, or report "
                "not_found or blocked."
            )
        if status not in STATUSES_WITH_PIECES and count > 0:
            raise Refused(
                f"Status {status} means no pieces, but the mark has {count}. Remove them first "
                "or report found."
            )
        for what, outcome in attempts:
            result["attempts"].append(
                {
                    "what": _clean("attempt", what, LIMITS["attempt"], required=True),
                    "outcome": _clean("attempt", outcome, LIMITS["attempt"], required=True),
                }
            )
        if len(result["attempts"]) > MAX_ATTEMPTS:
            raise Refused(f"A mark can list at most {MAX_ATTEMPTS} attempts.")
        if status == "not_found" and not result["attempts"]:
            raise Refused("not_found needs at least one attempt (--attempt WHAT OUTCOME).")
        result["status"] = status
        result["summary"] = text
        self.save_result(mark_id, result)
        return result
