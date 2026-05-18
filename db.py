import sqlite3
import os
import time
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "data/bot.db")


@contextmanager
def _db():
    dirpath = os.path.dirname(DB_PATH)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        yield con
    finally:
        con.close()


def init_db():
    with _db() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                created_at INTEGER NOT NULL,
                trial_used INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS vpn_clients (
                user_id      INTEGER PRIMARY KEY REFERENCES users(user_id),
                client_uuid  TEXT NOT NULL,
                email        TEXT NOT NULL UNIQUE,
                sub_id       TEXT NOT NULL UNIQUE,
                password     TEXT NOT NULL,
                inbound_id   INTEGER NOT NULL,
                expires_at   INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                yoo_id     TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                plan       TEXT NOT NULL,
                amount     REAL NOT NULL,
                created_at INTEGER NOT NULL,
                confirmed  INTEGER NOT NULL DEFAULT 0
            );
        """)
        con.commit()


def get_or_create_user(user_id: int, username) -> sqlite3.Row:
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            con.execute(
                "INSERT INTO users(user_id, username, created_at) VALUES(?,?,?)",
                (user_id, username, int(time.time()))
            )
            con.commit()
        elif username and row["username"] != username:
            con.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
            con.commit()
        # Always re-fetch to return consistent state
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def mark_trial_used(user_id: int):
    with _db() as con:
        con.execute("UPDATE users SET trial_used=1 WHERE user_id=?", (user_id,))
        con.commit()


def get_vpn_client(user_id: int):
    with _db() as con:
        return con.execute(
            "SELECT * FROM vpn_clients WHERE user_id=?", (user_id,)
        ).fetchone()


def upsert_vpn_client(user_id: int, client_uuid: str, email: str, sub_id: str,
                      password: str, inbound_id: int, expires_at: int):
    with _db() as con:
        con.execute("""
            INSERT INTO vpn_clients(user_id, client_uuid, email, sub_id, password, inbound_id, expires_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                client_uuid = excluded.client_uuid,
                email       = excluded.email,
                sub_id      = excluded.sub_id,
                password    = excluded.password,
                inbound_id  = excluded.inbound_id,
                expires_at  = excluded.expires_at
        """, (user_id, client_uuid, email, sub_id, password, inbound_id, expires_at))
        con.commit()


def set_vpn_expiry(user_id: int, expires_at: int):
    with _db() as con:
        con.execute(
            "UPDATE vpn_clients SET expires_at=? WHERE user_id=?",
            (expires_at, user_id)
        )
        con.commit()


def save_payment(yoo_id: str, user_id: int, plan: str, amount: float):
    with _db() as con:
        con.execute(
            "INSERT OR IGNORE INTO payments(yoo_id, user_id, plan, amount, created_at) "
            "VALUES(?,?,?,?,?)",
            (yoo_id, user_id, plan, amount, int(time.time()))
        )
        con.commit()


def confirm_payment(yoo_id: str):
    """
    Idempotent: atomically marks the payment confirmed and returns (user_id, plan).
    Returns None if already confirmed or not found.
    Uses rowcount to detect the winner in concurrent calls.
    """
    with _db() as con:
        cur = con.execute(
            "UPDATE payments SET confirmed=1 WHERE yoo_id=? AND confirmed=0",
            (yoo_id,)
        )
        con.commit()
        if cur.rowcount == 0:
            return None
        row = con.execute(
            "SELECT user_id, plan FROM payments WHERE yoo_id=?", (yoo_id,)
        ).fetchone()
        return (row["user_id"], row["plan"]) if row else None
