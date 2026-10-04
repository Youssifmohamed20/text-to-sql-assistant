from __future__ import annotations

import sqlite3
import shutil
import time
from contextlib import closing
import urllib.error
import urllib.request
import tempfile
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "Chinook_Sqlite.sqlite"
CHINOOK_DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/lerocha/chinook-database/master/"
    "ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"
)


def download_database_if_missing() -> Path:
    """Download the Chinook SQLite database when it is not already present."""
    if DB_PATH.exists():
        return DB_PATH

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=BASE_DIR, suffix=".sqlite", delete=False) as temp:
            temporary_path = Path(temp.name)
            with urllib.request.urlopen(CHINOOK_DOWNLOAD_URL, timeout=30) as response:
                shutil.copyfileobj(response, temp)
        with closing(sqlite3.connect(temporary_path.as_uri() + "?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Downloaded database failed integrity check.")
        temporary_path.replace(DB_PATH)
    except (urllib.error.URLError, OSError, sqlite3.Error) as exc:
        raise FileNotFoundError(
            f"Database file not found: {DB_PATH}. "
            "Automatic download failed. Download Chinook_Sqlite.sqlite from "
            f"{CHINOOK_DOWNLOAD_URL} and place it in the project root."
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return DB_PATH


def check_database_exists() -> Path:
    """Return the Chinook database path, downloading it first when needed."""
    return download_database_if_missing()


def get_connection() -> sqlite3.Connection:
    check_database_exists()
    return sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)


def _format_column(column: tuple) -> str:
    cid, name, col_type, not_null, default_value, pk = column
    parts = [name]
    if col_type:
        parts.append(col_type)
    if pk:
        parts.append("PK")
    if not_null:
        parts.append("NOT NULL")
    if default_value is not None:
        parts.append(f"DEFAULT {default_value}")
    return " ".join(parts)


def get_table_names() -> list[str]:
    with closing(get_connection()) as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    return [row[0] for row in rows]


def get_schema_map() -> dict[str, set[str]]:
    """Return a table-to-columns map extracted from SQLite metadata."""
    with closing(get_connection()) as conn:
        table_names = get_table_names()
        schema_map: dict[str, set[str]] = {}
        for table_name in table_names:
            columns = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            schema_map[table_name] = {column[1] for column in columns}
    return schema_map


def get_foreign_key_map() -> list[dict[str, str]]:
    """Return foreign-key relationships extracted from SQLite metadata."""
    with closing(get_connection()) as conn:
        relationships: list[dict[str, str]] = []
        for table_name in get_table_names():
            foreign_keys = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
            for fk in foreign_keys:
                _, _, ref_table, from_col, to_col, *_ = fk
                relationships.append(
                    {
                        "from_table": table_name,
                        "from_column": from_col,
                        "to_table": ref_table,
                        "to_column": to_col,
                    }
                )
    return relationships


def build_schema_context() -> str:
    """Extract a compact schema summary for the LLM prompt."""
    with closing(get_connection()) as conn:
        table_names = get_table_names()
        sections: list[str] = ["SQLite database: Chinook Music Store", "Tables:"]

        for table_name in table_names:
            columns = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            formatted_columns = ", ".join(_format_column(column) for column in columns)
            sections.append(f"- {table_name}({formatted_columns})")

        relationship_lines: list[str] = []
        for table_name in table_names:
            foreign_keys = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
            for fk in foreign_keys:
                _, _, ref_table, from_col, to_col, *_ = fk
                relationship_lines.append(
                    f"- {table_name}.{from_col} -> {ref_table}.{to_col}"
                )

        if relationship_lines:
            sections.append("Relationships:")
            sections.extend(sorted(relationship_lines))

    return "\n".join(sections)


def execute_sql(sql: str) -> pd.DataFrame:
    """Execute a read-only SQL query and return a pandas DataFrame."""
    with closing(get_connection()) as conn:
        conn.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + 15
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        return pd.read_sql_query(sql, conn)


if __name__ == "__main__":
    print(build_schema_context())
