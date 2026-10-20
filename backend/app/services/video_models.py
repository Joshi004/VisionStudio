"""Which video model makes a clip (LTX-2.3, LTX-2.5 or MiniMax H3). Pure functions, no I/O.

The ids here are what the database and the API store, so adding a model means adding it to
`VideoModel` and `LABELS` and giving it endpoints in `providers/video_generator.py`.

MiniMax H3 is a `VideoModel` like the two LTX models, and it is the Video lab's default. It
differs from LTX in its sizes (1344 x 768), its fixed 24 fps, its `17n + 5` frame grid, its
prompt format and the 4 or 8 GPUs the server gives it, so the code that makes a clip works
those out per model. Some code only works with LTX (the lip-sync endpoints, which MiniMax H3
does not have): it uses `LtxModel` and `is_ltx_model`.
"""

from __future__ import annotations

from typing import Final, Literal, TypeGuard, get_args

VideoModel = Literal["ltx-2.3", "ltx-2.5", "minimax-h3"]
# The two LTX models, for code that has no MiniMax H3 equivalent (lip sync).
LtxModel = Literal["ltx-2.3", "ltx-2.5"]
# The models the Video lab can make a clip with. It is the same list as `VideoModel` now (the lab
# was the only place that could use MiniMax H3 before), and the name stays for the lab's code.
LabVideoModel = VideoModel
# How a clip is made: from its first frame alone, or from both a first and a last frame.
ClipMode = Literal["first_frame", "first_and_last"]

MODEL_IDS: Final[tuple[VideoModel, ...]] = get_args(VideoModel)
LTX_MODEL_IDS: Final[tuple[LtxModel, ...]] = get_args(LtxModel)
LAB_MODEL_IDS: Final[tuple[LabVideoModel, ...]] = MODEL_IDS
LABELS: Final[dict[VideoModel, str]] = {
    "ltx-2.3": "LTX-2.3",
    "ltx-2.5": "LTX-2.5",
    "minimax-h3": "MiniMax H3",
}
LAB_LABELS: Final[dict[LabVideoModel, str]] = LABELS
H3_MODEL: Final[VideoModel] = "minimax-h3"
# The model the Video lab starts with.
DEFAULT_MODEL: Final[VideoModel] = H3_MODEL
# What LTX-only code (a lip-synced clip) uses when it is not told which LTX model.
DEFAULT_LTX_MODEL: Final[LtxModel] = "ltx-2.5"
# The same ids as a regular expression, for the global setting and the database CHECKs.
MODEL_PATTERN: Final = "ltx-2\\.3|ltx-2\\.5|minimax-h3"


def is_video_model(value: object) -> TypeGuard[VideoModel]:
    return isinstance(value, str) and value in MODEL_IDS


def is_lab_video_model(value: object) -> TypeGuard[LabVideoModel]:
    """True for every model the Video lab knows (the same models as `is_video_model`)."""
    return isinstance(value, str) and value in LAB_MODEL_IDS


def is_ltx_model(value: object) -> TypeGuard[LtxModel]:
    """True for LTX-2.3 and LTX-2.5, false for MiniMax H3."""
    return isinstance(value, str) and value in LTX_MODEL_IDS


def label(model: object) -> str:
    """The name to show for a model id. An unknown value is shown as it is."""
    return LABELS[model] if is_video_model(model) else str(model)
