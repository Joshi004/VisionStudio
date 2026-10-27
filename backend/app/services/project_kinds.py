"""The kinds of project (EXPLAINER-002). No imports, so any module may use it.

- `story`: a written story turned into a film (what every project was until now).
- `explainer`: a script spoken by one presenter chosen from the Character Lab, shown on camera
  in some passages and as a voice-over over B-roll in the others.

The kind is chosen when the project is created and never changed afterwards, like the
orientation and the speech mode.
"""

from __future__ import annotations

from typing import Final

KIND_STORY: Final = "story"
KIND_EXPLAINER: Final = "explainer"
KINDS: Final = (KIND_STORY, KIND_EXPLAINER)
