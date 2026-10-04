from __future__ import annotations

import sqlite3
from contextlib import closing

from db_setup import get_connection
from safety import validate_sql


def validate_schema_references(sql: str) -> tuple[bool, str]:
    """Let SQLite resolve identifiers and scopes without executing the query."""
    is_safe, message = validate_sql(sql)
    if not is_safe:
        return False, message
    try:
        with closing(get_connection()) as conn:
            conn.execute("EXPLAIN " + sql)
    except sqlite3.Error as exc:
        return False, str(exc)
    return True, "Schema references and SQLite syntax are valid."
