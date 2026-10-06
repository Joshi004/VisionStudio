"""Logging setup. Everything goes to stdout (Section 3.1 of ANALYSIS.md);
Docker captures it from there. Logs never carry a secret (Section 4.1 of
ITERATION_1_PHASES.md) — later phases that log request details must keep
to that rule.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str) -> None:
    """Configures the root logger to write to stdout at the given level."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )
