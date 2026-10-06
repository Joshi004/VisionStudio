"""Declarative base and the metadata naming convention every model shares.

Every constraint and index gets a predictable name (Phase 1 decision,
approved). This matters once a later migration needs SQLite's "batch"
mode (create a new table, copy rows, drop the old one, per
ITERATION_1_PHASES.md Section 4.3's migration convention) and must refer
to an existing constraint by name.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import REAL, MetaData, Text
from sqlalchemy.orm import DeclarativeBase

from app.db.types import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base for all seven tables (DATABASE_STRUCTURE.md Section 4).

    `type_annotation_map` fixes the SQL type SQLAlchemy infers from a bare
    Python type hint, so every model can write `Mapped[str]`, `Mapped[float]`
    and `Mapped[datetime]` without repeating the SQL type on each column:
    `str` always means `TEXT` (DATABASE_STRUCTURE.md uses TEXT everywhere,
    never a length-limited VARCHAR), `float` always means SQLite's `REAL`,
    and `datetime` always means naive-UTC-in, aware-UTC-out (see
    `app/db/types.py`).
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        str: Text,
        float: REAL,
        datetime: UTCDateTime,
    }
