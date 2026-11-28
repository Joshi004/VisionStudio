"""A research round on disk: the brief (read only) and the results the tool writes.

Every write goes through this module. It writes only inside `results/<claim_id>/` of the round,
only for a claim that is in the brief, and only under names the tool makes itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from . import (
    BRIEF_SCHEMA,
    BRIEF_VERSIONS,
    KINDS,
    RELATIONS,
    RESULT_SCHEMA,
    RESULT_VERSION,
    STATUSES,
    STATUSES_WITH_EVIDENCE,
    TIERS,
    TOOL_NAME,
    TOOL_VERSION,
)

CLAIM_ID: Final = re.compile(r"^c\d+$")
EVIDENCE_ID: Final = re.compile(r"^e\d{1,2}$")
DATE_TEXT: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Longest text the tool stores for each flag.
TEXT_LIMITS: Final = {
    "publisher": 200,
    "title": 300,
    "author": 200,
    "what_it_says": 1000,
    "notes": 2000,
    "summary": 1500,
    "attempt": 500,
    "url": 2000,
}
MAX_ATTEMPTS: Final = 40


class Refused(Exception):
    """The tool will not do this. The message is for the agent and says what to change."""


def file_names(evidence_id: str) -> dict[str, str]:
    """The only file names the tool makes for one piece of evidence."""
    return {
        "image": f"{evidence_id}.png",
        "context_image": f"{evidence_id}-context.png",
        "text_copy": f"{evidence_id}.txt",
        "source_copy": f"{evidence_id}.pdf",
        "media": f"{evidence_id}.mp4",
        "captions": f"{evidence_id}-captions.json",
    }


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_utc_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Described:
    """What the agent says about a piece of evidence. The tool only checks the values."""

    relation: str
    tier: str
    publisher: str
    what_it_says: str
    title: str | None = None
    author: str | None = None
    published: str | None = None
    archive_url: str | None = None
    notes: str = ""


def _clean(label: str, value: str | None, limit: int, *, required: bool = False) -> str | None:
    if value is None or not value.strip():
        if required:
            raise Refused(f"{label} is required.")
        return None
    text = " ".join(value.split())
    if len(text) > limit:
        raise Refused(f"{label} is too long ({len(text)} characters, the limit is {limit}).")
    return text


def check_described(described: Described) -> Described:
    """Check the descriptive flags and return them tidied."""
    if described.relation not in RELATIONS:
        raise Refused(f"relation must be one of: {', '.join(RELATIONS)}.")
    if described.tier not in TIERS:
        raise Refused(f"tier must be one of: {', '.join(TIERS)}.")
    published = _clean("published", described.published, 10)
    if published is not None:
        if not DATE_TEXT.match(published):
            raise Refused("published must be a date written YYYY-MM-DD.")
        try:
            date.fromisoformat(published)
        except ValueError as error:
            raise Refused("published is not a real date.") from error
    archive_url = _clean("archive_url", described.archive_url, TEXT_LIMITS["url"])
    if archive_url is not None and not archive_url.lower().startswith(("http://", "https://")):
        raise Refused("archive_url must start with http:// or https://.")
    notes = described.notes.strip()
    if len(notes) > TEXT_LIMITS["notes"]:
        raise Refused(f"notes is too long (the limit is {TEXT_LIMITS['notes']} characters).")
    return Described(
        relation=described.relation,
        tier=described.tier,
        publisher=_clean("publisher", described.publisher, TEXT_LIMITS["publisher"], required=True)
        or "",
        what_it_says=_clean(
            "what-it-says", described.what_it_says, TEXT_LIMITS["what_it_says"], required=True
        )
        or "",
        title=_clean("title", described.title, TEXT_LIMITS["title"]),
        author=_clean("author", described.author, TEXT_LIMITS["author"]),
        published=published,
        archive_url=archive_url,
        notes=notes,
    )


def evidence_entry(
    *,
    evidence_id: str,
    kind: str,
    described: Described,
    url: str,
    final_url: str,
    title: str | None,
    quote: str,
    capture: dict[str, Any],
) -> dict[str, Any]:
    """One entry of `evidence` (§4.5). `capture` is the block only the tool makes (EV-5)."""
    return {
        "id": evidence_id,
        "kind": kind,
        "relation": described.relation,
        "source_tier": described.tier,
        "source": {
            "url": url,
            "final_url": final_url,
            "publisher": described.publisher,
            "title": described.title if described.title is not None else title,
            "author": described.author,
            "published": described.published,
            "retrieved_at": now_utc_text(),
            "archive_url": described.archive_url,
        },
        "quote": quote,
        "what_it_says": described.what_it_says,
        "capture": {"tool": TOOL_NAME, "tool_version": TOOL_VERSION, **capture},
        "agent_notes": described.notes,
    }


@dataclass(frozen=True)
class Captured:
    """What a capture made: the entry for `result.json`, its files, and a line to tell the agent."""

    entry: dict[str, Any]
    files: dict[str, bytes]
    notes: list[str]


class Round:
    """A research round folder. Reads the brief, never writes it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.brief = self._read_brief()

    # --- The brief -------------------------------------------------------------------------

    def _read_brief(self) -> dict[str, Any]:
        path = self.root / "brief" / "claims.json"
        if not path.is_file() or path.is_symlink():
            if (self.root / "brief" / "footage.json").exists():
                raise Refused(
                    f"{self.root} is a footage round. Use visio-footage-capture here; "
                    "visio-evidence-capture is for evidence rounds."
                )
            raise Refused(
                f"{self.root} is not a research round: brief/claims.json is missing. Run the "
                "tool inside the round folder, or pass --round."
            )
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Refused(f"brief/claims.json cannot be read: {error}") from error
        if (
            not isinstance(brief, dict)
            or brief.get("schema") != BRIEF_SCHEMA
            or brief.get("version") not in BRIEF_VERSIONS
        ):
            raise Refused("brief/claims.json is not a version 1 or 2 evidence brief.")
        claims = brief.get("claims")
        project = brief.get("project")
        if (
            not isinstance(brief.get("round_id"), str)
            or not isinstance(claims, list)
            or not isinstance(project, dict)
            or project.get("orientation") not in ("landscape", "portrait")
        ):
            raise Refused("brief/claims.json is incomplete: round_id, project or claims is wrong.")
        for claim in claims:
            if not isinstance(claim, dict) or not CLAIM_ID.match(str(claim.get("id"))):
                raise Refused("brief/claims.json has a claim without a valid id.")
        return brief

    @property
    def round_id(self) -> str:
        return self.brief["round_id"]

    @property
    def orientation(self) -> str:
        return self.brief["project"]["orientation"]

    @property
    def max_evidence(self) -> int:
        value = (self.brief.get("rules") or {}).get("max_evidence_per_claim")
        return value if isinstance(value, int) and 1 <= value <= 20 else 3

    @property
    def claim_ids(self) -> list[str]:
        return [claim["id"] for claim in self.brief["claims"]]

    def claim(self, claim_id: str) -> dict[str, Any]:
        if not CLAIM_ID.match(claim_id) or claim_id not in self.claim_ids:
            raise Refused(f"{claim_id} is not a claim of this round. Claims: {self._claim_list()}.")
        return next(item for item in self.brief["claims"] if item["id"] == claim_id)

    def _claim_list(self) -> str:
        return ", ".join(self.claim_ids) or "none"

    # --- Folders ---------------------------------------------------------------------------

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    def claim_dir(self, claim_id: str, *, create: bool) -> Path:
        """The folder of one claim. Refuses a link or anything outside the round."""
        self.claim(claim_id)
        results = self.results_dir
        if results.is_symlink() or (results.exists() and not results.is_dir()):
            raise Refused("results/ is a link or not a folder.")
        folder = results / claim_id
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise Refused(f"results/{claim_id} is a link or not a folder.")
        if create:
            folder.mkdir(parents=True, exist_ok=True)
        if folder.exists() and not folder.resolve().is_relative_to(self.root):
            raise Refused(f"results/{claim_id} is outside the round.")
        return folder

    def _check_evidence_id(self, evidence_id: str) -> None:
        if not EVIDENCE_ID.match(evidence_id):
            raise Refused("The evidence id must look like e1, e2, ... (up to e99).")

    # --- Results ---------------------------------------------------------------------------

    def load_result(self, claim_id: str) -> dict[str, Any] | None:
        """The claim's `result.json`, or None when there is none yet."""
        path = self.claim_dir(claim_id, create=False) / "result.json"
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise Refused(f"results/{claim_id}/result.json is a link or not a file.")
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Refused(f"results/{claim_id}/result.json cannot be read: {error}") from error
        if not isinstance(result, dict) or result.get("claim_id") != claim_id:
            raise Refused(f"results/{claim_id}/result.json is not this claim's result.")
        if not isinstance(result.get("evidence"), list) or not isinstance(
            result.get("attempts"), list
        ):
            raise Refused(f"results/{claim_id}/result.json is damaged: delete it and start again.")
        return result

    def new_result(self, claim_id: str) -> dict[str, Any]:
        # The status stays null until `report` sets it: `validate` fails on a null status.
        return {
            "schema": RESULT_SCHEMA,
            "version": RESULT_VERSION,
            "round_id": self.round_id,
            "claim_id": claim_id,
            "status": None,
            "summary": "",
            "attempts": [],
            "evidence": [],
        }

    def result_or_new(self, claim_id: str) -> dict[str, Any]:
        return self.load_result(claim_id) or self.new_result(claim_id)

    def save_result(self, claim_id: str, result: dict[str, Any]) -> None:
        folder = self.claim_dir(claim_id, create=True)
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        _write_atomic(folder / "result.json", text.encode("utf-8"))

    def check_room(self, claim_id: str, evidence_id: str) -> None:
        """Refuse early (before a capture is made) when this piece of evidence cannot be added."""
        self._check_evidence_id(evidence_id)
        result = self.load_result(claim_id)
        others = [
            item for item in (result["evidence"] if result else []) if item.get("id") != evidence_id
        ]
        if len(others) >= self.max_evidence:
            raise Refused(
                f"Claim {claim_id} already has {len(others)} pieces of evidence, and the limit is "
                f"{self.max_evidence}. Remove one first (remove --claim {claim_id} "
                "--evidence ...), or replace one by using its id."
            )

    def store_evidence(
        self,
        claim_id: str,
        entry: dict[str, Any],
        files: dict[str, bytes],
    ) -> dict[str, Any]:
        """Write the files of a piece of evidence, then its entry. An entry with the same id is
        replaced, and files of the old one that the new one does not use are removed. Returns
        the saved result.
        """
        evidence_id = entry["id"]
        self._check_evidence_id(evidence_id)
        if entry["kind"] not in KINDS:
            raise Refused(f"kind must be one of: {', '.join(KINDS)}.")
        self.check_room(claim_id, evidence_id)
        result = self.result_or_new(claim_id)
        folder = self.claim_dir(claim_id, create=True)
        names = set(file_names(evidence_id).values())
        if not set(files) <= names:
            raise Refused("Internal error: a file name that the tool does not make.")
        for name, data in files.items():
            _write_atomic(folder / name, data)
        for stale in names - set(files):
            _unlink_own(folder / stale)
        position = next(
            (i for i, item in enumerate(result["evidence"]) if item.get("id") == evidence_id),
            None,
        )
        if position is None:
            result["evidence"].append(entry)
        else:
            result["evidence"][position] = entry
        # A status that needs no evidence no longer fits. The agent reports it again.
        if result["status"] not in STATUSES_WITH_EVIDENCE:
            result["status"] = None
        self.save_result(claim_id, result)
        return result

    def remove_evidence(self, claim_id: str, evidence_id: str) -> dict[str, Any]:
        self._check_evidence_id(evidence_id)
        result = self.load_result(claim_id)
        if result is None or not any(item.get("id") == evidence_id for item in result["evidence"]):
            raise Refused(f"Claim {claim_id} has no evidence {evidence_id}.")
        result["evidence"] = [item for item in result["evidence"] if item.get("id") != evidence_id]
        folder = self.claim_dir(claim_id, create=False)
        for name in file_names(evidence_id).values():
            _unlink_own(folder / name)
        if not result["evidence"] and result["status"] in STATUSES_WITH_EVIDENCE:
            result["status"] = None
        self.save_result(claim_id, result)
        return result

    def report(
        self,
        claim_id: str,
        *,
        status: str,
        summary: str,
        attempts: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """Set the claim's status and summary, and add attempts. §4.5 rules apply."""
        if status not in STATUSES:
            raise Refused(f"status must be one of: {', '.join(STATUSES)}.")
        text = _clean("summary", summary, TEXT_LIMITS["summary"], required=True) or ""
        result = self.result_or_new(claim_id)
        count = len(result["evidence"])
        if status in STATUSES_WITH_EVIDENCE and count == 0:
            raise Refused(
                f"Status {status} needs at least one piece of evidence. Capture it first, or "
                "report not_found or blocked."
            )
        if status not in STATUSES_WITH_EVIDENCE and count > 0:
            raise Refused(
                f"Status {status} means no evidence, but the claim has {count}. Remove it first "
                "or pick a status that fits."
            )
        for what, outcome in attempts:
            result["attempts"].append(
                {
                    "what": _clean("attempt", what, TEXT_LIMITS["attempt"], required=True),
                    "outcome": _clean("attempt", outcome, TEXT_LIMITS["attempt"], required=True),
                }
            )
        if len(result["attempts"]) > MAX_ATTEMPTS:
            raise Refused(f"A claim can list at most {MAX_ATTEMPTS} attempts.")
        if status == "not_found" and not result["attempts"]:
            raise Refused("not_found needs at least one attempt (--attempt WHAT OUTCOME).")
        result["status"] = status
        result["summary"] = text
        self.save_result(claim_id, result)
        return result


def _write_atomic(path: Path, data: bytes) -> None:
    """Write to a partial name, then move into place. Refuses to write over a link."""
    if path.is_symlink():
        raise Refused(f"{path.name} is a link, so it is not written over.")
    partial = path.with_name(f".{path.name}.partial")
    if partial.is_symlink():
        partial.unlink()
    partial.write_bytes(data)
    os.replace(partial, path)


def _unlink_own(path: Path) -> None:
    """Remove a file the tool made (a link is removed, never followed)."""
    if path.is_symlink() or path.is_file():
        path.unlink()
