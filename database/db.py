import aiosqlite
from datetime import datetime, timezone


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
            await db.commit()

    async def add_warning(self, chat_id: int, user_id: int, admin_id: int, reason: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO warnings(chat_id,user_id,admin_id,reason,created_at) VALUES(?,?,?,?,?)",
                (chat_id, user_id, admin_id, reason, datetime.now(timezone.utc).isoformat()),
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
                (chat_id, event_type, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def event_count(self, chat_id: int, event_type: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM events WHERE chat_id=? AND event_type=?",
                (chat_id, event_type),
            )
            return int((await cursor.fetchone())[0])
