"""PostgreSQL sink: one connection per source database, COPY for bulk loads, batched DML."""
from __future__ import annotations

import contextlib
from typing import Iterable

import psycopg
from psycopg import sql

from ..schema import Schema


class PgSink:
    def __init__(self, schema: Schema, urls: dict[str, str]) -> None:
        self.s = schema
        self.urls = urls
        self.conns: dict[str, psycopg.Connection] = {}

    def conn(self, db: str) -> psycopg.Connection:
        c = self.conns.get(db)
        if c is None or c.closed:
            c = psycopg.connect(self.urls[db], autocommit=False, application_name="advsim")
            self.conns[db] = c
        return c

    def close(self) -> None:
        for c in self.conns.values():
            with contextlib.suppress(Exception):
                c.close()
        self.conns.clear()

    def ping(self) -> dict[str, str]:
        """db -> 'ok' or the connection error."""
        out = {}
        for db, url in self.urls.items():
            try:
                with psycopg.connect(url, connect_timeout=3) as c:
                    c.execute("SELECT 1")
                out[db] = "ok"
            except Exception as e:  # noqa: BLE001 - report any failure
                out[db] = str(e).strip().splitlines()[0]
        return out

    # ------------------------------------------------------------ writes
    def copy(self, table: str, columns: list[str], rows: Iterable[tuple], db: str | None = None) -> int:
        t = self.s.table(table)
        db = db or self.s.db_of[table]
        stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
            sql.Identifier(t.schema, t.name), sql.SQL(", ").join(map(sql.Identifier, columns)))
        n = 0
        with self.conn(db).cursor() as cur, cur.copy(stmt) as cp:
            for r in rows:
                cp.write_row(r)
                n += 1
        return n

    def copy_dicts(self, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        cols = [c.name for c in self.s.table(table).columns]
        return self.copy(table, cols, (tuple(r.get(c) for c in cols) for r in rows))

    def execute(self, db: str, query, params=None) -> None:
        self.conn(db).execute(query, params)

    def commit(self, db: str | None = None) -> None:
        for name, c in self.conns.items():
            if db is None or name == db:
                c.commit()

    def rollback(self) -> None:
        for c in self.conns.values():
            with contextlib.suppress(Exception):
                c.rollback()

    # ------------------------------------------------------------ admin
    def data_tables(self, db: str) -> list[tuple[str, str]]:
        return [(t.schema, t.name) for t in self.s.systems[db].tables]

    def reset(self, dbs: list[str] | None = None) -> None:
        """TRUNCATE every non-ref table (code sets stay seeded)."""
        for db in dbs or list(self.urls):
            names = sql.SQL(", ").join(sql.Identifier(s, n) for s, n in self.data_tables(db))
            c = self.conn(db)
            c.execute(sql.SQL("TRUNCATE {} CASCADE").format(names))
            c.commit()

    def counts(self, db: str) -> dict[str, int]:
        c = self.conn(db)
        out = {}
        for s, n in self.data_tables(db):
            out[f"{s}.{n}"] = c.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(s, n))).fetchone()[0]
        c.rollback()
        return out

    def fetch(self, db: str, query, params=None) -> list[tuple]:
        c = self.conn(db)
        rows = c.execute(query, params).fetchall()
        c.rollback()
        return rows
