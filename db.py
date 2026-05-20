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
    except Exception:
        con.rollback()
        raise
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
                yoo_id      TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                plan        TEXT NOT NULL,
                amount      REAL NOT NULL,
                created_at  INTEGER NOT NULL,
                confirmed   INTEGER NOT NULL DEFAULT 0,
                provisioned INTEGER NOT NULL DEFAULT 0
            );
        """)
        con.commit()
        try:
            con.execute("ALTER TABLE payments ADD COLUMN provisioned INTEGER NOT NULL DEFAULT 0")
            con.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def get_or_create_user(user_id: int, username) -> sqlite3.Row:
    with _db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(user_id, username, created_at) VALUES(?,?,?)",
            (user_id, username, int(time.time()))
        )
        con.commit()
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if username and row["username"] != username:
            con.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
            con.commit()
            return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row


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


def count_active_clients() -> int:
    with _db() as con:
        row = con.execute(
            "SELECT COUNT(*) FROM vpn_clients WHERE expires_at > ?",
            (int(time.time()),)
        ).fetchone()
        return row[0]


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
    Marks payment confirmed. Returns (user_id, plan) only if THIS call was the
    first to flip confirmed=0→1 (rowcount check), preventing double-provisioning
    when YooKassa retries send two webhooks simultaneously.
    Returns None if already confirmed by another webhook or payment not found.
    """
    with _db() as con:
        cur = con.execute(
            "UPDATE payments SET confirmed=1 WHERE yoo_id=? AND confirmed=0",
            (yoo_id,)
        )
        if cur.rowcount == 0:
            con.commit()
            return None
        row = con.execute(
            "SELECT user_id, plan FROM payments WHERE yoo_id=?",
            (yoo_id,)
        ).fetchone()
        con.commit()
        return (row["user_id"], row["plan"]) if row else None


def mark_payment_provisioned(yoo_id: str):
    with _db() as con:
        con.execute("UPDATE payments SET provisioned=1 WHERE yoo_id=?", (yoo_id,))
        con.commit()


def has_provisioned_payment(user_id: int) -> bool:
    with _db() as con:
        row = con.execute(
            "SELECT 1 FROM payments WHERE user_id=? AND provisioned=1 LIMIT 1",
            (user_id,)
        ).fetchone()
        return row is not None


def get_all_vpn_clients() -> list:
    with _db() as con:
        return con.execute("SELECT * FROM vpn_clients").fetchall()
