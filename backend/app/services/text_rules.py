"""A check on the wording of a prompt that an AI wrote. Pure data, no I/O.

Used by the prompt profiles (`lab_prompt_profiles`, `image_prompt_profiles`), which list the
wordings their prompts must not contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TextRule:
    """A wording the prompt must not contain. Breaking it is a warning, never an error."""

    pattern: re.Pattern[str]
    message: str
