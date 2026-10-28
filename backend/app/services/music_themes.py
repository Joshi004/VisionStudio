"""The recordings of a story's music themes (MUSIC-007, `Music_implementation_phases.md` Section
4.2, MD-6, MD-10).

The Music Bible names the themes. For each one this module makes a canonical recording and one
recording per emotion the Bible lists for it:

1. `write_music_theme_prompt` (`requested: "theme"`) asks the language model for the ACE-Step
   fields of the theme (`services/music_theme_writer`). When it finishes, `save_theme` adds a
   `music_theme` row with those fields and starts the candidates in the same transaction: the
   fields are sent again with different seeds, one `lab_music` run each (`music_lab.add_run`, so
   the audio, its status and its measurements are the Music lab's own).
2. When a candidate's audio is stored (`on_audio_stored`, called by the `lab_music` job), it is
   measured and checked (`check_recording`). In an automatic run the first candidate that passes
   becomes the canonical recording (`chosen_by` is `auto`, MD-10). The owner can choose another
   one at any time (`choose`, `chosen_by` is `owner`), and an automatic choice never replaces
   that.
3. `write_music_theme_prompt` (`requested: "versions"`) asks the model for one caption per
   emotion, from the canonical fields. `save_versions` adds one `music_theme_version` row and
   one run for each. A version is fresh text-to-music, not a conversion of the recording (MD-6,
   changed 2026-10-25): the same instrument, tempo, key and time signature, the tune described
   in the caption, and the canonical candidate's seed.

Nothing here is stored about being out of date. A theme is out of date when the part of the
Music Bible it was made from has changed (`theme_digest`); a version is out of date when it was
made from another candidate than the one that is canonical now. Both are worked out when read.
This module creates rows and jobs and never calls the GPU server or the language model itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Final, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_service
from app.db.models import (
    Job,
    LabMusicRun,
    MusicBible,
    MusicTheme,
    MusicThemeCandidate,
    MusicThemeVersion,
    Project,
)
from app.db.session import SessionLocal
from app.db.state_memo import memoized_state
from app.jobs import store
from app.providers import music_generator
from app.services import (
    audio_measurements,
    music_bible,
    music_lab,
    music_models,
    story_bible,
)
from app.services import music_theme_writer as writer
from app.services.storage import StorageError, get_storage

_logger = logging.getLogger(__name__)

JOB_TYPE: Final = "write_music_theme_prompt"
REQUESTED_THEME: Final = "theme"
REQUESTED_VERSIONS: Final = "versions"
MODEL: Final = writer.MODEL
# Theme recordings are stems: one instrument alone (the lab's kind for it).
KIND: Final = "stem"
METHOD_TEXT: Final = "text"
CHOSEN_AUTO: Final = "auto"
CHOSEN_OWNER: Final = "owner"

# The technical check (MUSIC-007, Planning decides). Module constants; MUSIC-010 can turn them
# into settings when more recordings need them.
MIN_LENGTH_FRACTION: Final = 0.9
MAX_LEADING_SILENCE_S: Final = 1.0
MAX_INNER_SILENCE_S: Final = 3.0

MUSIC_OFF_MESSAGE: Final = music_bible.MUSIC_OFF_MESSAGE
NO_BIBLE_MESSAGE: Final = "Write the Music Bible first: the themes come from it."
REPLACE_MESSAGE: Final = (
    "You chose the canonical recording of a theme that is out of date. Recording the theme "
    "again makes new candidates, so it has to be confirmed."
)
BUSY_MESSAGE: Final = "The theme's prompts are being written. Wait for them to finish first."


class MusicThemeError(ValueError):
    """A request that cannot be done. The message is meant to be shown to the user."""


# --- What a theme is made from -------------------------------------------------------------


def theme_entries(bible: MusicBible) -> list[dict[str, Any]]:
    """The themes of a Bible version, the main theme first (the order the Bible stores)."""
    themes = bible.content.get("themes") if isinstance(bible.content, dict) else None
    return (
        [theme for theme in themes if isinstance(theme, dict)] if isinstance(themes, list) else []
    )


def theme_digest(bible: MusicBible, theme: dict[str, Any]) -> str:
    """A hash of what a theme's recording is made from: the theme's name, what it stands for and
    its instrument, and the Bible's concept, sound world and musical feel. The emotions are left
    out on purpose (an emotion added to the Bible is only a missing version), and so is which
    theme is the main one.
    """
    content = bible.content if isinstance(bible.content, dict) else {}
    material = {
        "concept": content.get("concept"),
        "sound_world": content.get("sound_world"),
        "musical_feel": content.get("musical_feel"),
        "theme": {
            "name": theme.get("name"),
            "stands_for": theme.get("stands_for"),
            "signature_instrument": theme.get("signature_instrument"),
        },
    }
    text = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _emotions(theme: dict[str, Any]) -> list[str]:
    emotions = theme.get("emotions")
    return (
        [e for e in emotions if isinstance(e, str) and e.strip()]
        if isinstance(emotions, list)
        else []
    )


def build_context(
    story: dict[str, Any] | None, bible: MusicBible, theme: dict[str, Any]
) -> dict[str, Any]:
    """What the model reads: the story's genre and tone, the Bible's concept, sound world and
    musical feel, and the theme. Nothing here needs timings (MD-3).
    """
    content = bible.content if isinstance(bible.content, dict) else {}
    story_part: dict[str, Any] = {}
    if story is not None:
        for key in ("title", "genre", "tone", "time_period"):
            if story.get(key):
                story_part[key] = story[key]
    return {
        "story": story_part,
        "music_bible": {
            "concept": content.get("concept"),
            "sound_world": content.get("sound_world"),
            "musical_feel": content.get("musical_feel"),
        },
        "theme": {
            "name": theme.get("name"),
            "main": theme.get("main"),
            "stands_for": theme.get("stands_for"),
            "signature_instrument": theme.get("signature_instrument"),
            "emotions": _emotions(theme),
        },
    }


# --- The technical check -------------------------------------------------------------------


def check_recording(measurement: dict[str, Any], *, requested_s: float) -> dict[str, Any]:
    """Whether a recording passes the technical check, from its MUSIC-003 measurement. Pure.

    It passes when it is at least `MIN_LENGTH_FRACTION` of the length asked for, starts within
    `MAX_LEADING_SILENCE_S` of silence, does not clip and has no silence inside it longer than
    `MAX_INNER_SILENCE_S`. Returns `{passed, problems, duration_s, leading_silence_s}`.
    """
    problems: list[str] = []
    duration = float(measurement.get("duration_s") or 0.0)
    if duration < requested_s * MIN_LENGTH_FRACTION:
        problems.append(f"It is {duration:.1f} s long, and {requested_s:g} s were asked for.")
    leading = float(measurement.get("leading_silence_s") or 0.0)
    if leading > MAX_LEADING_SILENCE_S:
        problems.append(f"It starts with {leading:.1f} s of silence.")
    loudness = measurement.get("loudness")
    if isinstance(loudness, dict) and loudness.get("clipping"):
        problems.append("It clips (the sound reaches full scale).")
    longest = 0.0
    for silence in measurement.get("silences") or []:
        longest = max(longest, float(silence["end_s"]) - float(silence["start_s"]))
    if longest > MAX_INNER_SILENCE_S:
        problems.append(f"It has a silence of {longest:.1f} s inside it.")
    return {
        "passed": not problems,
        "problems": problems,
        "duration_s": round(duration, 2),
        "leading_silence_s": round(leading, 2),
    }


def _failed_check(message: str) -> dict[str, Any]:
    return {"passed": False, "problems": [message], "duration_s": None, "leading_silence_s": None}


def _passed(check: object) -> bool | None:
    """True or False for a stored check, None when the audio has not been checked yet."""
    if isinstance(check, dict) and isinstance(check.get("passed"), bool):
        return bool(check["passed"])
    return None


# --- Reading the state ---------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateView:
    row: MusicThemeCandidate
    run: music_lab.RunRow | None

    @property
    def passed(self) -> bool | None:
        return _passed(self.row.check_result)


@dataclass(frozen=True)
class VersionView:
    row: MusicThemeVersion
    run: music_lab.RunRow | None
    # Made from the candidate that is canonical now.
    current: bool

    @property
    def passed(self) -> bool | None:
        return _passed(self.row.check_result)


@dataclass(frozen=True)
class ThemeView:
    """One theme of the Bible with where its recordings stand."""

    # The theme as the newest Bible has it.
    theme: dict[str, Any]
    row: MusicTheme | None
    candidates: list[CandidateView]
    # The current version of each emotion, or the newest out-of-date one when there is no current.
    versions: list[VersionView]
    # The newest `write_music_theme_prompt` job of this theme, whatever its status.
    job: Job | None
    reasons: list[str]
    # Recording it again would replace a canonical recording the owner chose.
    needs_confirmation: bool
    done: bool
    active: bool
    # What a run starts next: `theme` (write the fields, make candidates), `candidates` (more
    # candidates of the same fields), `versions` (captions and recordings of the missing
    # emotions), or None when nothing is missing.
    action: str | None
    # Emotions that need a caption written and a recording made.
    to_write: list[str]

    @property
    def out_of_date(self) -> bool:
        return bool(self.reasons)

    @property
    def chosen(self) -> CandidateView | None:
        if self.row is None or self.row.chosen_candidate_id is None:
            return None
        return next((c for c in self.candidates if c.row.id == self.row.chosen_candidate_id), None)


@dataclass(frozen=True)
class MusicThemesState:
    """What the story workspace shows."""

    bible: MusicBible | None
    themes: list[ThemeView]
    music_enabled: bool
    # Why no theme can be recorded yet, or None.
    blocked_reason: str | None
    candidates_per_theme: int
    duration_s: int


def _active(job: Job | None) -> bool:
    return job is not None and job.status in store.ACTIVE_STATUSES


def _usable(run: music_lab.RunRow | None) -> bool:
    """A run that has made its audio."""
    return run is not None and run.run.path is not None


def _run_active(run: music_lab.RunRow | None) -> bool:
    return run is not None and _active(run.job)


async def _newest_rows(session: AsyncSession, project_id: int) -> dict[str, MusicTheme]:
    statement = (
        select(MusicTheme)
        .where(MusicTheme.project_id == project_id)
        .order_by(MusicTheme.version.asc())
        .execution_options(populate_existing=True)
    )
    rows = (await session.execute(statement)).scalars().all()
    return {row.theme_id: row for row in rows}  # the newest version of a theme comes last


async def _prompt_jobs(session: AsyncSession, project_id: int) -> dict[str, Job]:
    """The newest prompt job of each theme, by the Bible's theme id."""
    statement = (
        select(Job)
        .where(Job.project_id == project_id, Job.type == JOB_TYPE)
        .order_by(Job.id.asc())
        .execution_options(populate_existing=True)
    )
    found: dict[str, Job] = {}
    for job in (await session.execute(statement)).scalars():
        theme_id = job.input.get("theme_id") if isinstance(job.input, dict) else None
        if isinstance(theme_id, str):
            found[theme_id] = job
    return found


async def _blocked_reason(session: AsyncSession, project: Project) -> str | None:
    if not project.music_enabled:
        return MUSIC_OFF_MESSAGE
    if await music_bible.latest(session, project.id) is None:
        return NO_BIBLE_MESSAGE
    return None


def _view(
    theme: dict[str, Any],
    bible: MusicBible,
    row: MusicTheme | None,
    candidates: list[MusicThemeCandidate],
    versions: list[MusicThemeVersion],
    runs: dict[int, music_lab.RunRow],
    job: Job | None,
) -> ThemeView:
    candidate_views = [
        CandidateView(c, runs.get(c.lab_run_id) if c.lab_run_id is not None else None)
        for c in sorted(candidates, key=lambda c: c.position)
    ]
    reasons: list[str] = []
    if row is not None and row.inputs.get("theme_sha256") != theme_digest(bible, theme):
        reasons.append(
            f"The theme '{theme.get('name')}' or the Music Bible's sound world has changed "
            "since this theme was recorded."
        )
    emotions = _emotions(theme)
    chosen_id = row.chosen_candidate_id if row is not None else None

    version_views: list[VersionView] = []
    to_write: list[str] = []
    for emotion in emotions:
        mine = sorted(
            (v for v in versions if v.emotion == emotion), key=lambda v: v.id, reverse=True
        )
        current = next(
            (v for v in mine if chosen_id is not None and v.candidate_id == chosen_id), None
        )
        shown = current or (mine[0] if mine else None)
        if shown is not None:
            run = runs.get(shown.lab_run_id) if shown.lab_run_id is not None else None
            version_views.append(VersionView(shown, run, current=current is not None))
        made = False
        if current is not None:
            run = runs.get(current.lab_run_id) if current.lab_run_id is not None else None
            made = _usable(run) or _run_active(run)
        if chosen_id is not None and not made:
            to_write.append(emotion)

    chosen_view = next((c for c in candidate_views if c.row.id == chosen_id), None)
    versions_ready = chosen_id is not None and all(
        any(v.current and v.row.emotion == e and _usable(v.run) for v in version_views)
        for e in emotions
    )
    done = row is not None and not reasons and chosen_view is not None and versions_ready

    prompt_active = _active(job)
    candidates_active = chosen_id is None and any(_run_active(c.run) for c in candidate_views)
    versions_active = any(v.current and _run_active(v.run) for v in version_views)
    active = prompt_active or candidates_active or versions_active

    action: str | None
    if row is None or reasons:
        action = REQUESTED_THEME
    elif chosen_id is None:
        action = "candidates"
    elif to_write:
        action = REQUESTED_VERSIONS
    else:
        action = None

    return ThemeView(
        theme=theme,
        row=row,
        candidates=candidate_views,
        versions=version_views,
        job=job,
        reasons=reasons,
        needs_confirmation=bool(reasons) and row is not None and row.chosen_by == CHOSEN_OWNER,
        done=done,
        active=active,
        action=action if not done else None,
        to_write=to_write,
    )


@memoized_state
async def state(session: AsyncSession, project: Project) -> MusicThemesState:
    """The project's themes with where their recordings stand. Worked out on every read."""
    bible = await music_bible.latest(session, project.id)
    candidates_per_theme = await settings_service.get_int(
        session, settings_service.MUSIC_THEME_CANDIDATES_KEY
    )
    duration_s = await settings_service.get_int(session, settings_service.MUSIC_THEME_DURATION_KEY)
    blocked = await _blocked_reason(session, project)
    if bible is None:
        return MusicThemesState(
            None, [], project.music_enabled, blocked, candidates_per_theme, duration_s
        )

    rows = await _newest_rows(session, project.id)
    row_ids = [row.id for row in rows.values()]
    candidates: list[MusicThemeCandidate] = []
    versions: list[MusicThemeVersion] = []
    if row_ids:
        candidates = list(
            (
                await session.execute(
                    select(MusicThemeCandidate).where(MusicThemeCandidate.theme_row_id.in_(row_ids))
                )
            ).scalars()
        )
        versions = list(
            (
                await session.execute(
                    select(MusicThemeVersion).where(MusicThemeVersion.theme_row_id.in_(row_ids))
                )
            ).scalars()
        )
    run_ids = {c.lab_run_id for c in candidates if c.lab_run_id is not None}
    run_ids |= {v.lab_run_id for v in versions if v.lab_run_id is not None}
    runs = await music_lab.get_runs(session, run_ids)
    jobs = await _prompt_jobs(session, project.id)

    views: list[ThemeView] = []
    for theme in theme_entries(bible):
        row = rows.get(theme["id"])
        views.append(
            _view(
                theme,
                bible,
                row,
                [c for c in candidates if row is not None and c.theme_row_id == row.id],
                [v for v in versions if row is not None and v.theme_row_id == row.id],
                runs,
                jobs.get(theme["id"]),
            )
        )
    return MusicThemesState(
        bible, views, project.music_enabled, blocked, candidates_per_theme, duration_s
    )


# --- Starting runs -------------------------------------------------------------------------


def _theme_brief(description: str, duration_s: float) -> dict[str, Any]:
    return music_lab.clean_brief(KIND, {"description": description, "duration_s": duration_s})


def _seeds(count: int) -> list[int]:
    base = secrets.randbelow(music_models.SEED_MAX + 1)
    return [(base + offset) % (music_models.SEED_MAX + 1) for offset in range(count)]


async def _partition(session: AsyncSession) -> str:
    try:
        return await music_lab.generation_partition(session, MODEL)
    except music_lab.MusicLabInputError as exc:
        raise MusicThemeError(str(exc)) from exc


async def _add_candidates(
    session: AsyncSession,
    *,
    project_id: int,
    row: MusicTheme,
    theme_name: str,
    seeds: list[int],
    first_position: int,
    partition: str,
) -> list[int]:
    """Adds one candidate and its run for each seed, and flushes. Returns the ids of the GPU
    jobs. Does not commit.
    """
    duration = float(row.fields["duration"])
    brief = _theme_brief(f"Candidate recording of the music theme '{theme_name}'.", duration)
    job_ids: list[int] = []
    for offset, seed in enumerate(seeds):
        body = music_generator.build_body(MODEL, row.fields, seed=seed, partition=partition)
        made = await music_lab.add_run(
            session,
            model=MODEL,
            kind=KIND,
            brief=brief,
            fields=row.fields,
            seed=seed,
            body=body,
            group_key=f"theme:{row.id}",
            project_id=project_id,
        )
        session.add(
            MusicThemeCandidate(
                theme_row_id=row.id,
                position=first_position + offset,
                lab_run_id=made.run.id,
                seed=seed,
            )
        )
        if made.job is not None:
            job_ids.append(made.job.id)
    await session.flush()
    return job_ids


async def _add_version(
    session: AsyncSession,
    *,
    project_id: int,
    row: MusicTheme,
    theme_name: str,
    candidate_id: int,
    emotion: str,
    fields: dict[str, Any],
    seed: int,
    prompt_job_id: int | None,
    partition: str,
) -> int | None:
    """Adds one version of an emotion and its run, and flushes. Returns the id of the GPU job.
    Does not commit.
    """
    brief = _theme_brief(
        f"Version of the music theme '{theme_name}' for the emotion '{emotion}'.",
        float(fields["duration"]),
    )
    body = music_generator.build_body(MODEL, fields, seed=seed, partition=partition)
    made = await music_lab.add_run(
        session,
        model=MODEL,
        kind=KIND,
        brief=brief,
        fields=fields,
        seed=seed,
        body=body,
        group_key=f"theme:{row.id}",
        project_id=project_id,
    )
    session.add(
        MusicThemeVersion(
            theme_row_id=row.id,
            candidate_id=candidate_id,
            emotion=emotion,
            method=METHOD_TEXT,
            prompt_job_id=prompt_job_id,
            fields=fields,
            lab_run_id=made.run.id,
            seed=seed,
        )
    )
    await session.flush()
    return made.job.id if made.job is not None else None


async def _queue_theme_job(
    session: AsyncSession, project: Project, bible: MusicBible, theme: dict[str, Any]
) -> tuple[int, ...]:
    story = await story_bible.latest(session, project.id)
    job_input = {
        "requested": REQUESTED_THEME,
        "theme_id": theme["id"],
        "theme_name": theme["name"],
        "context": build_context(story.content if story is not None else None, bible, theme),
        "bible": {"id": bible.id, "version": bible.version},
        "theme_sha256": theme_digest(bible, theme),
        "candidates": await settings_service.get_int(
            session, settings_service.MUSIC_THEME_CANDIDATES_KEY
        ),
        "duration_s": await settings_service.get_int(
            session, settings_service.MUSIC_THEME_DURATION_KEY
        ),
        "partition": await _partition(session),
        "seeds": _seeds(4),
    }
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=job_input,
        dedupe_key="theme_id",
    )
    return (job.id,)


async def _queue_versions_job(
    session: AsyncSession, project: Project, bible: MusicBible, view: ThemeView
) -> tuple[int, ...]:
    assert view.row is not None and view.chosen is not None
    story = await story_bible.latest(session, project.id)
    job_input = {
        "requested": REQUESTED_VERSIONS,
        "theme_id": view.theme["id"],
        "theme_name": view.theme["name"],
        "theme_row_id": view.row.id,
        "candidate_id": view.chosen.row.id,
        "seed": view.chosen.row.seed,
        "context": build_context(story.content if story is not None else None, bible, view.theme),
        "canonical": view.row.fields,
        "emotions": view.to_write,
        "partition": await _partition(session),
    }
    job, _created = await store.create_job(
        session,
        project_id=project.id,
        type=JOB_TYPE,
        provider="llm",
        input=job_input,
        dedupe_key="theme_id",
    )
    return (job.id,)


async def _more_candidates(
    session: AsyncSession, project: Project, view: ThemeView
) -> tuple[int, ...]:
    """New candidates of the same fields, for a theme none of whose candidates could be chosen
    (every one failed its check, or its run failed). No model call: the fields are kept.
    """
    assert view.row is not None
    count = await settings_service.get_int(session, settings_service.MUSIC_THEME_CANDIDATES_KEY)
    partition = await _partition(session)
    first = max((c.row.position for c in view.candidates), default=0) + 1
    job_ids = await _add_candidates(
        session,
        project_id=project.id,
        row=view.row,
        theme_name=str(view.theme["name"]),
        seeds=_seeds(count),
        first_position=first,
        partition=partition,
    )
    await session.commit()
    return tuple(job_ids)


async def _require_ready(session: AsyncSession, project: Project) -> MusicBible:
    blocked = await _blocked_reason(session, project)
    if blocked is not None:
        raise MusicThemeError(blocked)
    bible = await music_bible.latest(session, project.id)
    assert bible is not None
    return bible


async def start_run(
    session: AsyncSession,
    project: Project,
    *,
    theme_id: str | None = None,
    confirm_replace_owner: bool = False,
) -> tuple[int, ...]:
    """Starts whatever is missing or out of date for every theme of the Bible, or for the one
    `theme_id`, and commits. Returns the ids of the jobs it queued (none when everything is done
    or already being made). A theme whose canonical recording the owner chose is only made again
    when `confirm_replace_owner` is true. Raises MusicThemeError.
    """
    bible = await _require_ready(session, project)
    current = await state(session, project)
    views = [v for v in current.themes if theme_id is None or v.theme["id"] == theme_id]
    if theme_id is not None and not views:
        raise MusicThemeError(f"The Music Bible has no theme '{theme_id}'.")
    todo = [v for v in views if v.action is not None and not v.active]
    if any(v.needs_confirmation for v in todo) and not confirm_replace_owner:
        raise MusicThemeError(REPLACE_MESSAGE)

    job_ids: list[int] = []
    for view in todo:
        if view.action == REQUESTED_THEME:
            job_ids.extend(await _queue_theme_job(session, project, bible, view.theme))
        elif view.action == "candidates":
            job_ids.extend(await _more_candidates(session, project, view))
        elif view.action == REQUESTED_VERSIONS:
            job_ids.extend(await _queue_versions_job(session, project, bible, view))
    return tuple(job_ids)


async def _newest_row(session: AsyncSession, project_id: int, theme_id: str) -> MusicTheme | None:
    statement = (
        select(MusicTheme)
        .where(MusicTheme.project_id == project_id, MusicTheme.theme_id == theme_id)
        .order_by(MusicTheme.version.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(statement)).scalars().first()


async def choose(
    session: AsyncSession, project: Project, theme_id: str, candidate_id: int
) -> tuple[int, ...]:
    """The owner chooses a candidate as the theme's canonical recording, and the emotional
    versions are made again from it. Commits. Returns the ids of the jobs it queued. Raises
    MusicThemeError.
    """
    bible = await _require_ready(session, project)
    row = await _newest_row(session, project.id, theme_id)
    if row is None:
        raise MusicThemeError("This theme has no candidates yet.")
    candidate = await session.get(MusicThemeCandidate, candidate_id)
    if candidate is None or candidate.theme_row_id != row.id:
        raise MusicThemeError("That is not a candidate of this theme.")
    run = (
        await music_lab.get_run(session, candidate.lab_run_id)
        if candidate.lab_run_id is not None
        else None
    )
    if not _usable(run):
        raise MusicThemeError("That candidate has no recording yet.")
    jobs = await _prompt_jobs(session, project.id)
    if _active(jobs.get(theme_id)):
        raise MusicThemeError(BUSY_MESSAGE)

    row.chosen_candidate_id = candidate.id
    row.chosen_by = CHOSEN_OWNER
    await session.commit()

    current = await state(session, project)
    view = next((v for v in current.themes if v.theme["id"] == theme_id), None)
    if view is None or view.row is None or view.row.id != row.id or not view.to_write:
        return ()
    return await _queue_versions_job(session, project, bible, view)


async def regenerate_version(
    session: AsyncSession, project: Project, theme_id: str, emotion: str
) -> tuple[int, ...]:
    """Makes one emotional version again: a new recording of the same fields with a new seed. No
    model call. Commits. Returns the ids of the jobs it queued. Raises MusicThemeError.
    """
    await _require_ready(session, project)
    current = await state(session, project)
    view = next((v for v in current.themes if v.theme["id"] == theme_id), None)
    if view is None or view.row is None or view.chosen is None:
        raise MusicThemeError("This theme has no canonical recording yet.")
    shown = next((v for v in view.versions if v.row.emotion == emotion and v.current), None)
    if shown is None:
        raise MusicThemeError(f"The theme has no version for '{emotion}' to make again.")
    if _run_active(shown.run):
        raise MusicThemeError("That version is still being made.")
    partition = await _partition(session)
    job_id = await _add_version(
        session,
        project_id=project.id,
        row=view.row,
        theme_name=str(view.theme["name"]),
        candidate_id=view.chosen.row.id,
        emotion=emotion,
        fields=shown.row.fields,
        seed=_seeds(1)[0],
        prompt_job_id=None,
        partition=partition,
    )
    await session.commit()
    return (job_id,) if job_id is not None else ()


# --- Saving what the prompt jobs wrote -----------------------------------------------------


async def save_theme(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    theme_id: str,
    theme_name: str,
    fields: dict[str, Any],
    bible: dict[str, int],
    theme_sha256: str,
    candidates: int,
    seeds: list[int],
    partition: str,
) -> MusicTheme:
    """Adds the next `music_theme` row for a theme, with its candidates and their runs. Flushes
    but does not commit: the job commits it together with finishing itself, so a job is never
    "succeeded" without its result.
    """
    highest = (
        await session.execute(
            select(func.max(MusicTheme.version)).where(
                MusicTheme.project_id == project_id, MusicTheme.theme_id == theme_id
            )
        )
    ).scalar_one_or_none()
    row = MusicTheme(
        project_id=project_id,
        bible_id=bible["id"],
        theme_id=theme_id,
        version=(highest or 0) + 1,
        prompt_job_id=job_id,
        fields=fields,
        inputs={
            "artifacts": [{"kind": "music_bible", "id": bible["id"], "version": bible["version"]}],
            "theme_sha256": theme_sha256,
        },
    )
    session.add(row)
    await session.flush()
    await _add_candidates(
        session,
        project_id=project_id,
        row=row,
        theme_name=theme_name,
        seeds=seeds[:candidates],
        first_position=1,
        partition=partition,
    )
    return row


async def save_versions(
    session: AsyncSession,
    *,
    project_id: int,
    job_id: int,
    theme_row_id: int,
    candidate_id: int,
    theme_name: str,
    seed: int,
    versions: dict[str, dict[str, Any]],
    partition: str,
) -> list[MusicThemeVersion]:
    """Adds one version and its run for each emotion, from the candidate that was canonical when
    the job was queued. Flushes but does not commit (see `save_theme`). Raises MusicThemeError
    when the owner has chosen another candidate in the meantime, since these captions were
    written for the old one.
    """
    row = await session.get(MusicTheme, theme_row_id)
    if row is None:
        raise MusicThemeError("The theme was replaced while its versions were being written.")
    if row.chosen_candidate_id != candidate_id:
        raise MusicThemeError("Another candidate was chosen while the versions were being written.")
    made: list[MusicThemeVersion] = []
    for emotion, fields in versions.items():
        await _add_version(
            session,
            project_id=project_id,
            row=row,
            theme_name=theme_name,
            candidate_id=candidate_id,
            emotion=emotion,
            fields=fields,
            seed=seed,
            prompt_job_id=job_id,
            partition=partition,
        )
    found = await session.execute(
        select(MusicThemeVersion).where(
            MusicThemeVersion.theme_row_id == theme_row_id,
            MusicThemeVersion.candidate_id == candidate_id,
            MusicThemeVersion.prompt_job_id == job_id,
        )
    )
    made.extend(found.scalars())
    return made


# --- When a recording is stored ------------------------------------------------------------


async def _check_run(session: AsyncSession, run: LabMusicRun, requested_s: float) -> dict[str, Any]:
    if run.path is None or run.sha256 is None:
        return _failed_check("The run made no recording.")
    try:
        path = get_storage().get_path(run.path)
        measurement = await audio_measurements.measure(session, path, run.sha256)
    except (StorageError, audio_measurements.MeasurementError) as exc:
        return _failed_check(str(exc))
    return check_recording(measurement, requested_s=requested_s)


async def _claim_choice(
    session: AsyncSession, theme_row_id: int, candidate_id: int, chosen_by: str
) -> bool:
    """Makes the candidate canonical only while the theme has none: two candidates stored at the
    same moment cannot both win, and an owner's choice is never replaced.
    """
    statement = (
        update(MusicTheme)
        .where(MusicTheme.id == theme_row_id, MusicTheme.chosen_candidate_id.is_(None))
        .values(chosen_candidate_id=candidate_id, chosen_by=chosen_by)
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(statement))
    await session.commit()
    return result.rowcount == 1


async def on_audio_stored(run_id: int) -> bool:
    """Called (best effort) once a `lab_music` job has stored its audio. When the run is a
    candidate or a version of a theme, measures it and stores the check. When it is a candidate
    of the newest recording of a theme that has no canonical recording yet, and it passed, it
    becomes the canonical recording (D-5, MD-10) and the emotional versions are queued. Returns
    True when it queued jobs. Does nothing (False) for a run that belongs to no theme.
    """
    async with SessionLocal() as session:
        candidate = (
            (
                await session.execute(
                    select(MusicThemeCandidate).where(MusicThemeCandidate.lab_run_id == run_id)
                )
            )
            .scalars()
            .first()
        )
        version = None
        if candidate is None:
            version = (
                (
                    await session.execute(
                        select(MusicThemeVersion).where(MusicThemeVersion.lab_run_id == run_id)
                    )
                )
                .scalars()
                .first()
            )
        member = candidate or version
        run = await session.get(LabMusicRun, run_id)
        if member is None or run is None:
            await session.commit()
            return False
        theme = await session.get(MusicTheme, member.theme_row_id)
        if theme is None:
            await session.commit()
            return False
        member.check_result = await _check_run(session, run, float(theme.fields["duration"]))
        passed = _passed(member.check_result)
        theme_row_id, project_id, theme_id = theme.id, theme.project_id, theme.theme_id
        candidate_id = candidate.id if candidate is not None else None
        await session.commit()

    if candidate_id is None or not passed:
        return False
    async with SessionLocal() as session:
        newest = await _newest_row(session, project_id, theme_id)
        if newest is None or newest.id != theme_row_id:
            return False  # a newer recording of the theme has replaced this one
        if not await _claim_choice(session, theme_row_id, candidate_id, CHOSEN_AUTO):
            return False
        _logger.info(
            "theme %s of project %d: candidate %d chosen", theme_id, project_id, candidate_id
        )
        project = await session.get(Project, project_id)
        if project is None or not project.music_enabled:
            return False
        try:
            current = await state(session, project)
            view = next((v for v in current.themes if v.theme["id"] == theme_id), None)
            bible = current.bible
            if view is None or bible is None or view.reasons or not view.to_write:
                return False
            return bool(await _queue_versions_job(session, project, bible, view))
        except MusicThemeError:
            _logger.exception("theme %s: the versions could not be started", theme_id)
            return False
