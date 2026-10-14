"""Which video model makes a clip (LTX-2.3 or LTX-2.5). Pure functions, no I/O.

The choice can be made at four levels. The most specific one that is set wins:

1. the Regenerate picker (one take only),
2. the scene (`scene.video_model`),
3. the project (`project.video_model`),
4. the app's default (the global setting `default_video_model`).

A scene or a project that has no choice of its own stores NULL, which means "inherit".
The ids here are what the database, the API and the settings store, so adding a model
means adding it to `VideoModel` and `LABELS` and giving it endpoints in
`providers/video_generator.py`.

MiniMax H3 is deliberately not a `VideoModel`. It can only be chosen in the Video lab and for a
video take of the Character lab, so it lives in `LabVideoModel` (a `VideoModel` plus
`minimax-h3`). Projects, scenes, the Regenerate picker and the global default keep using
`VideoModel`, which never holds an H3 id.
"""

from __future__ import annotations

from typing import Final, Literal, TypeGuard, get_args

VideoModel = Literal["ltx-2.3", "ltx-2.5"]
# The models the Video lab can make a clip with: the two above and MiniMax H3.
LabVideoModel = Literal["ltx-2.3", "ltx-2.5", "minimax-h3"]
# Where the model in force came from, most specific first.
ModelSource = Literal["regenerate", "scene", "project", "global"]

MODEL_IDS: Final[tuple[VideoModel, ...]] = get_args(VideoModel)
LAB_MODEL_IDS: Final[tuple[LabVideoModel, ...]] = get_args(LabVideoModel)
LABELS: Final[dict[VideoModel, str]] = {"ltx-2.3": "LTX-2.3", "ltx-2.5": "LTX-2.5"}
LAB_LABELS: Final[dict[LabVideoModel, str]] = {**LABELS, "minimax-h3": "MiniMax H3"}
# Used when the saved global setting is somehow not a known model.
DEFAULT_MODEL: Final[VideoModel] = "ltx-2.5"
# The same ids as a regular expression, for the global setting and the database CHECKs.
MODEL_PATTERN: Final = "ltx-2\\.3|ltx-2\\.5"

H3_MODEL: Final[LabVideoModel] = "minimax-h3"


def is_video_model(value: object) -> TypeGuard[VideoModel]:
    return isinstance(value, str) and value in MODEL_IDS


def is_lab_video_model(value: object) -> TypeGuard[LabVideoModel]:
    """True for every model the Video lab knows, MiniMax H3 included."""
    return isinstance(value, str) and value in LAB_MODEL_IDS


def label(model: object) -> str:
    """The name to show for a model id (MiniMax H3 included). An unknown value is shown as it is."""
    return LAB_LABELS[model] if is_lab_video_model(model) else str(model)


def resolve(
    override: object,
    scene_model: object,
    project_model: object,
    global_model: object,
) -> tuple[VideoModel, ModelSource]:
    """The model to use and the level that chose it. A value that is not a known model (NULL,
    or an id this version does not know) counts as "not set" and the next level decides.
    """
    if is_video_model(override):
        return override, "regenerate"
    if is_video_model(scene_model):
        return scene_model, "scene"
    if is_video_model(project_model):
        return project_model, "project"
    if is_video_model(global_model):
        return global_model, "global"
    return DEFAULT_MODEL, "global"
