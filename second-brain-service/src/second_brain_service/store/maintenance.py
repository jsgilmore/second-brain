from pathlib import Path
from typing import Any, Optional

from psycopg.types.json import Jsonb

from second_brain_service.store.connection import with_connection


@with_connection
def get_sync_state(cur, key: str) -> Optional[dict[str, Any]]:
    cur.execute("SELECT state FROM sync_state WHERE key = %s", (key,))
    row = cur.fetchone()
    return row["state"] if row else None


@with_connection
def set_sync_state(cur, key: str, state: dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO sync_state (key, state)
        VALUES (%s, %s)
        ON CONFLICT (key)
        DO UPDATE SET
          state = EXCLUDED.state,
          updated_at = NOW()
        """,
        (key, Jsonb(state)),
    )


@with_connection
def delete_sync_state(cur, key: str) -> None:
    cur.execute("DELETE FROM sync_state WHERE key = %s", (key,))


@with_connection
def apply_schema_scripts(cur) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[4]
    init_dir = repo_root / "docker" / "postgres" / "init"
    applied = []
    for sql_file in sorted(init_dir.glob("*.sql")):
        cur.execute(sql_file.read_text())
        applied.append(sql_file.name)
    return {"status": "ok", "applied_files": applied}
