from datetime import datetime, timezone
from functools import wraps
from typing import Callable

from pgvector.psycopg import register_vector
import psycopg
from psycopg.rows import dict_row

from second_brain_service.common.config import DATABASE_URL


def get_connection() -> psycopg.Connection:
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    register_vector(conn)
    return conn


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_to_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def with_connection(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with get_connection() as conn:
            with conn.cursor() as cur:
                return fn(cur, *args, **kwargs)

    return wrapper
