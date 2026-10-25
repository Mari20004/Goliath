import os
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,       -- tg username в нижнем регистре, без @
    phone TEXT,                          -- только цифры, формат 7XXXXXXXXXX
    tg_id INTEGER,
    verified INTEGER NOT NULL DEFAULT 0,
    sub_id TEXT,                         -- subId клиента в 3x-ui
    expires_at INTEGER NOT NULL DEFAULT 0,
    notified TEXT NOT NULL DEFAULT '',
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    tg_id INTEGER,
    confirmed INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    months INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | review | paid | rejected
    created INTEGER NOT NULL
);
"""


def init() -> None:
    global _conn
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(SCHEMA)
    _conn.commit()


def q(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return _conn.execute(sql, args).fetchall()


def one(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args: tuple = ()) -> int:
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


def now() -> int:
    return int(time.time())


def norm_phone(raw: str) -> str:
    d = "".join(c for c in (raw or "") if c.isdigit())
    if len(d) == 11 and d[0] == "8":
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d
