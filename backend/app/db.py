from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    coingecko_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_networks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    chain TEXT NOT NULL,
    contract_address TEXT,
    decimals INTEGER NOT NULL,
    is_native INTEGER NOT NULL DEFAULT 0 CHECK (is_native IN (0, 1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (token_id, chain)
);

CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_refreshed_at TEXT,
    last_refresh_error TEXT,
    last_refresh_warning TEXT,
    last_refresh_provider TEXT,
    UNIQUE (chain, address)
);

CREATE TABLE IF NOT EXISTS balances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address_id INTEGER NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    token_network_id INTEGER NOT NULL REFERENCES token_networks(id) ON DELETE CASCADE,
    raw_balance TEXT NOT NULL,
    price_usd TEXT,
    value_usd TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (address_id, token_network_id)
);

CREATE TABLE IF NOT EXISTS prices (
    token_id INTEGER PRIMARY KEY REFERENCES tokens(id) ON DELETE CASCADE,
    price_usd TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address_id INTEGER REFERENCES addresses(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'success', 'failed')),
    trigger TEXT NOT NULL DEFAULT 'manual',
    provider TEXT,
    warning TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_jobs_active
    ON refresh_jobs(address_id)
    WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS idx_refresh_jobs_created
    ON refresh_jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_balances_address
    ON balances(address_id);

CREATE INDEX IF NOT EXISTS idx_token_networks_chain
    ON token_networks(chain);

CREATE INDEX IF NOT EXISTS idx_addresses_chain
    ON addresses(chain);
"""


class Database:
    """Small sqlite3 wrapper around one shared connection.

    SQLite in WAL mode is enough for this workload: a handful of API readers and
    a single refresh worker writer. A process-wide lock serializes access. All
    writes are short, so this keeps the implementation simple and deterministic.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=30,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._conn = self._connect()
            return self._conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = self.connection
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.connection
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    def fetchone(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.connection.execute(sql, params).fetchall())

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.connection.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
