from __future__ import annotations
import time
import aiosqlite
from typing import Optional

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER UNIQUE NOT NULL,
    username    TEXT,
    full_name   TEXT,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    sub_id       TEXT UNIQUE NOT NULL,
    email        TEXT UNIQUE NOT NULL,
    plan         TEXT NOT NULL,
    expires_at   INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    vpn_password TEXT,
    created_at   INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    yookassa_id  TEXT UNIQUE NOT NULL,
    amount       INTEGER NOT NULL,
    plan         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    sub_id       TEXT,
    created_at   INTEGER NOT NULL DEFAULT (unixepoch())
);
"""


async def init_db(path: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.executescript(DDL)
        # Migrations for existing databases
        try:
            await db.execute("ALTER TABLE subscriptions ADD COLUMN vpn_password TEXT")
            await db.commit()
        except Exception:
            pass  # Column already exists



# ─── Users ────────────────────────────────────────────────────────────────────

async def upsert_user(path: str, tg_id: int, username: Optional[str], full_name: str) -> int:
    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,)) as cur:
            row = await cur.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET username=?, full_name=? WHERE tg_id=?",
                (username, full_name, tg_id),
            )
            await db.commit()
            return row[0]
        async with db.execute(
            "INSERT INTO users (tg_id, username, full_name) VALUES (?,?,?) RETURNING id",
            (tg_id, username, full_name),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
        return row[0]


async def get_user_by_tg(path: str, tg_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)) as cur:
            return await cur.fetchone()


# ─── Subscriptions ────────────────────────────────────────────────────────────

async def get_active_sub(path: str, user_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND status='active' "
            "ORDER BY expires_at DESC LIMIT 1",
            (user_id,),
        ) as cur:
            return await cur.fetchone()


async def create_sub(
    path: str,
    user_id: int,
    sub_id: str,
    email: str,
    plan: str,
    expires_at: int,
    vpn_password: str | None = None,
) -> bool:
    """Insert subscription. Returns False if email already exists (duplicate trial guard)."""
    import aiosqlite as _aiosqlite
    async with aiosqlite.connect(path) as db:
        try:
            await db.execute(
                "INSERT INTO subscriptions (user_id, sub_id, email, plan, expires_at, vpn_password) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, sub_id, email, plan, expires_at, vpn_password),
            )
            await db.commit()
            return True
        except _aiosqlite.IntegrityError:
            return False


async def reactivate_sub(
    path: str,
    email: str,
    sub_id: str,
    plan: str,
    expires_at: int,
    vpn_password: str | None = None,
) -> None:
    """Reactivate a previous expired/cancelled subscription (same email, new sub_id).
    Called when user buys a new plan after their trial/old sub was already expired+cleaned up."""
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "UPDATE subscriptions SET sub_id=?, plan=?, expires_at=?, status='active', vpn_password=? "
            "WHERE email=?",
            (sub_id, plan, expires_at, vpn_password, email),
        )
        await db.commit()


async def extend_sub(path: str, sub_id: str, new_expires_at: int, plan: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "UPDATE subscriptions SET expires_at=?, plan=? WHERE sub_id=?",
            (new_expires_at, plan, sub_id),
        )
        await db.commit()


async def set_sub_status(path: str, sub_id: str, status: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "UPDATE subscriptions SET status=? WHERE sub_id=?", (status, sub_id)
        )
        await db.commit()


async def count_active_subs(path: str) -> int:
    """Total number of currently active subscriptions (all users)."""
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
        ) as cur:
            return (await cur.fetchone())[0]


async def has_any_sub(path: str, user_id: int) -> bool:
    """True if user has EVER had a subscription (active, expired, cancelled)."""
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (user_id,)
        ) as cur:
            return (await cur.fetchone())[0] > 0


async def get_expired_subs(path: str) -> list:
    """Active subscriptions past their expiry date."""
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        now = int(time.time())
        async with db.execute(
            "SELECT s.*, u.tg_id FROM subscriptions s "
            "JOIN users u ON s.user_id=u.id "
            "WHERE s.status='active' AND s.expires_at < ?",
            (now,),
        ) as cur:
            return await cur.fetchall()


# ─── Payments ─────────────────────────────────────────────────────────────────

async def create_payment(
    path: str, user_id: int, yookassa_id: str, amount: int, plan: str
) -> None:
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO payments (user_id, yookassa_id, amount, plan) VALUES (?,?,?,?)",
            (user_id, yookassa_id, amount, plan),
        )
        await db.commit()


async def get_payment(path: str, yookassa_id: str) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT p.*, u.tg_id FROM payments p "
            "JOIN users u ON p.user_id=u.id WHERE p.yookassa_id=?",
            (yookassa_id,),
        ) as cur:
            return await cur.fetchone()


async def set_payment_status(
    path: str, yookassa_id: str, status: str, sub_id: Optional[str] = None
) -> None:
    async with aiosqlite.connect(path) as db:
        if sub_id:
            await db.execute(
                "UPDATE payments SET status=?, sub_id=? WHERE yookassa_id=?",
                (status, sub_id, yookassa_id),
            )
        else:
            await db.execute(
                "UPDATE payments SET status=? WHERE yookassa_id=?",
                (status, yookassa_id),
            )
        await db.commit()


async def claim_payment(path: str, yookassa_id: str) -> bool:
    """Atomically flip payment status pending→processing.
    Returns True only for the first caller; subsequent calls return False.
    Prevents double-provisioning on YooKassa webhook re-delivery."""
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "UPDATE payments SET status='processing' WHERE yookassa_id=? AND status='pending'",
            (yookassa_id,),
        ) as cur:
            changed = cur.rowcount
        await db.commit()
        return changed > 0


async def get_pending_payment(path: str, user_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM payments WHERE user_id=? AND status='pending' "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ) as cur:
            return await cur.fetchone()


# ─── Admin stats ──────────────────────────────────────────────────────────────

async def get_stats(path: str) -> dict:
    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            users = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status='active'"
        ) as cur:
            active = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='succeeded'"
        ) as cur:
            revenue = (await cur.fetchone())[0]
    return {"users": users, "active_subs": active, "revenue": revenue}


async def get_all_users_with_subs(path: str) -> list:
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT u.tg_id, u.username, u.full_name, "
            "s.plan, s.expires_at, s.status AS sub_status, s.sub_id "
            "FROM users u "
            "LEFT JOIN subscriptions s ON s.user_id=u.id AND s.status='active' "
            "ORDER BY u.created_at DESC LIMIT 50"
        ) as cur:
            return await cur.fetchall()
