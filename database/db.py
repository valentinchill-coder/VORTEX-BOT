import aiosqlite
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path

    async def connect(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    admin_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    balance INTEGER NOT NULL DEFAULT 0,
                    last_daily TEXT,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reputation (
                    chat_id INTEGER NOT NULL,
                    target_user_id INTEGER NOT NULL,
                    giver_user_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, target_user_id, giver_user_id, day)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_activity ON users(chat_id, message_count DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rep_target ON reputation(chat_id, target_user_id)"
            )
            await db.commit()

    async def add_warning(self, chat_id: int, user_id: int, admin_id: int, reason: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO warnings(chat_id,user_id,admin_id,reason,created_at) VALUES(?,?,?,?,?)",
                (chat_id, user_id, admin_id, reason, _now()),
            )
            cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            count = (await cursor.fetchone())[0]
            await db.commit()
            return int(count)

    async def warning_count(self, chat_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            return int((await cursor.fetchone())[0])

    async def clear_warnings(self, chat_id: int, user_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
            await db.commit()

    async def log_event(self, chat_id: int, event_type: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO events(chat_id,event_type,created_at) VALUES(?,?,?)",
                (chat_id, event_type, _now()),
            )
            await db.commit()

    async def event_count(self, chat_id: int, event_type: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM events WHERE chat_id=? AND event_type=?",
                (chat_id, event_type),
            )
            return int((await cursor.fetchone())[0])

    async def register_message(self, chat_id: int, user_id: int, username: str | None, full_name: str) -> None:
        now = _now()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO users(chat_id,user_id,username,full_name,message_count,first_seen,last_seen)
                VALUES(?,?,?,?,1,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    username=excluded.username,
                    full_name=excluded.full_name,
                    message_count=users.message_count+1,
                    last_seen=excluded.last_seen
            """, (chat_id, user_id, username, full_name, now, now))
            await db.commit()

    async def get_profile(self, chat_id: int, user_id: int) -> dict:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            user = await cursor.fetchone()
            rep_cursor = await db.execute(
                "SELECT COUNT(*) FROM reputation WHERE chat_id=? AND target_user_id=?",
                (chat_id, user_id),
            )
            rep = (await rep_cursor.fetchone())[0]
            warn_cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            warns = (await warn_cursor.fetchone())[0]
            return {
                "user": dict(user) if user else None,
                "reputation": int(rep),
                "warnings": int(warns),
            }

    async def give_reputation(self, chat_id: int, target_user_id: int, giver_user_id: int) -> bool:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                INSERT OR IGNORE INTO reputation(chat_id,target_user_id,giver_user_id,day,created_at)
                VALUES(?,?,?,?,?)
            """, (chat_id, target_user_id, giver_user_id, now.date().isoformat(), now.isoformat()))
            await db.commit()
            return cursor.rowcount == 1

    async def top_reputation(self, chat_id: int, limit: int = 10) -> list[tuple[int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT target_user_id, COUNT(*) AS score
                FROM reputation WHERE chat_id=?
                GROUP BY target_user_id
                ORDER BY score DESC, target_user_id ASC
                LIMIT ?
            """, (chat_id, limit))
            return [(int(row[0]), int(row[1])) for row in await cursor.fetchall()]

    async def chat_stats(self, chat_id: int) -> dict:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(message_count),0) FROM users WHERE chat_id=?",
                (chat_id,),
            )
            users, messages = await cursor.fetchone()
            warnings = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE chat_id=?", (chat_id,)
            )
            warning_count = (await warnings.fetchone())[0]
            flood = await db.execute(
                "SELECT COUNT(*) FROM events WHERE chat_id=? AND event_type='antiflood'",
                (chat_id,),
            )
            flood_count = (await flood.fetchone())[0]
            return {
                "users": int(users),
                "messages": int(messages),
                "warnings": int(warning_count),
                "antiflood": int(flood_count),
            }

    async def get_balance(self, chat_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def claim_daily(self, chat_id: int, user_id: int, reward: int = 100) -> tuple[bool, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT balance,last_daily FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            row = await cursor.fetchone()
            if row and row[1] == today:
                await db.commit()
                return False, int(row[0])
            await db.execute("""
                INSERT INTO wallets(chat_id,user_id,balance,last_daily)
                VALUES(?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    balance=wallets.balance+excluded.balance,
                    last_daily=excluded.last_daily
            """, (chat_id, user_id, reward, today))
            cursor = await db.execute(
                "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            balance = int((await cursor.fetchone())[0])
            await db.commit()
            return True, balance

    async def transfer(self, chat_id: int, sender_id: int, recipient_id: int, amount: int) -> tuple[bool, int]:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "INSERT OR IGNORE INTO wallets(chat_id,user_id,balance) VALUES(?,?,0)",
                (chat_id, sender_id),
            )
            await db.execute(
                "INSERT OR IGNORE INTO wallets(chat_id,user_id,balance) VALUES(?,?,0)",
                (chat_id, recipient_id),
            )
            cursor = await db.execute(
                "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, sender_id),
            )
            balance = int((await cursor.fetchone())[0])
            if balance < amount:
                await db.commit()
                return False, balance
            await db.execute(
                "UPDATE wallets SET balance=balance-? WHERE chat_id=? AND user_id=?",
                (amount, chat_id, sender_id),
            )
            await db.execute(
                "UPDATE wallets SET balance=balance+? WHERE chat_id=? AND user_id=?",
                (amount, chat_id, recipient_id),
            )
            await db.commit()
            return True, balance - amount

    async def top_balances(self, chat_id: int, limit: int = 10) -> list[tuple[int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT user_id,balance FROM wallets
                WHERE chat_id=? AND balance>0
                ORDER BY balance DESC,user_id ASC LIMIT ?
            """, (chat_id, limit))
            return [(int(row[0]), int(row[1])) for row in await cursor.fetchall()]


    async def top_activity(self, chat_id: int, limit: int = 10) -> list[tuple[int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT user_id,message_count FROM users
                WHERE chat_id=?
                ORDER BY message_count DESC,user_id ASC LIMIT ?
            """, (chat_id, limit))
            return [(int(row[0]), int(row[1])) for row in await cursor.fetchall()]
