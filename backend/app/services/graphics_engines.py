"""The engine registry of the Graphics lab (GFX-002).

The lab makes the same graphic with four engines and compares the four videos. Each engine has
one entry here: its key, its label, and a `start` function. `start` is None until the phase that
builds the engine fills it in, and an engine without one is "not built yet" (the run page says
so, and **Make all** of GFX-003 skips it).

Each engine phase changes only its own entry, so phases that run at the same time meet in one
line each and never in the same code:

| engine                | phase                                    |
|-----------------------|------------------------------------------|
| `remotion_templates`  | GFX-007 (the spec is written by GFX-006) |
| `python_templates`    | GFX-008 (the spec is written by GFX-006) |
| `remotion_blocks`     | GFX-009                                  |
| `generated_component` | GFX-010                                  |

`start(session, run)` is what Make all calls for a run whose brief is ready. It starts the
engine for the run (the model call that writes the engine's input, which then leads to the
render) and returns the first job it made. It follows the other starters of the labs
(`services/music_lab.add_run`): it adds rows and jobs and leaves the commit to its caller.

**Two flags.** `built` (`start` is set) means the engine can be started, which is what Make all
looks at. `renderer_built` means its renderer exists, so a saved input is rendered at once. The
two template engines (GFX-006) can be started, because their spec is written by one shared call
(`services/graphics_template_engine.py`), before their renderers exist: GFX-007 and GFX-008 each
only set `renderer_built=True`, and the spec job then queues their render.

This module imports nothing that calls a model, a renderer or the GPU server.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, LabGraphicRun
from app.services import graphics_template_engine

EngineKey = Literal[
    "remotion_templates", "python_templates", "remotion_blocks", "generated_component"
]

StartFn = Callable[[AsyncSession, LabGraphicRun], Awaitable[Job]]


@dataclass(frozen=True)
class Engine:
    key: EngineKey
    label: str
    # Filled in by the engine's own phase. None means the engine is not built yet.
    start: StartFn | None = None
    # Set by the engine's renderer phase: a saved input of this engine is rendered.
    renderer_built: bool = False

    @property
    def built(self) -> bool:
        return self.start is not None


# In the order of the design (§4.5): the two template engines render the same template spec, so
# they come first and side by side.
ENGINES: Final[dict[EngineKey, Engine]] = {
    "remotion_templates": Engine(
        key="remotion_templates",
        label="Remotion templates",
        start=graphics_template_engine.start,
        renderer_built=True,
    ),
    "python_templates": Engine(
        key="python_templates",
        label="Python templates",
        start=graphics_template_engine.start,
        renderer_built=True,
    ),
    "remotion_blocks": Engine(key="remotion_blocks", label="Remotion building blocks"),
    "generated_component": Engine(key="generated_component", label="Generated component"),
}
