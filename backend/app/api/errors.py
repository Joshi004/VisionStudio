"""The shape of an error answer, used to document 404 and 422 in OpenAPI.

Errors follow FastAPI's `{"detail": ...}` with a readable message
(ITERATION_1_PHASES.md Section 4.3).
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
