"""Text search over columns, treating what people type as plain text.

In a LIKE pattern `%` matches anything and `_` any one character, so a search for "50%" or
"q3_report" would match far more than was typed, and a lone "%" would match everything. These
characters, and the escape character itself, are escaped before the pattern is built.
"""

from typing import Any

from sqlalchemy import ColumnElement

ESCAPE = "\\"


def escape_like(text: str) -> str:
    return text.replace(ESCAPE, ESCAPE * 2).replace("%", ESCAPE + "%").replace("_", ESCAPE + "_")


def contains(column: Any, text: str) -> ColumnElement[bool]:
    """The column (a model field or an SQL expression) contains this text, ignoring case."""
    return column.ilike(  # type: ignore[no-any-return]
        f"%{escape_like(text.strip())}%", escape=ESCAPE
    )
