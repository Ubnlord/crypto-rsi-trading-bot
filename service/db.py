"""Small synchronous PostgreSQL boundary with transaction-local identity.

The configured database role must be a restricted runtime role, never a
superuser/table owner. RLS uses request.jwt.claim.sub and is set locally inside
each transaction to prevent pooled-connection identity leakage.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException


@contextmanager
def tenant_db(user_id: str) -> Iterator[psycopg.Connection]:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise HTTPException(status_code=503, detail="Database is not configured")
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
            yield conn
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Database request failed") from exc
