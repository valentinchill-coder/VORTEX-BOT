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
                CREATE TABLE IF NOT EXISTS moderation_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    actor_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_moderation_audit_chat_id ON moderation_audit(chat_id, id DESC)"
            )
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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS moderation_ranks (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 5),
                    assigned_by INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS game_stats (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    points INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    played INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    messages INTEGER NOT NULL DEFAULT 0,
                    games INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(chat_id,user_id,day)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_quest_claims (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    quest_id TEXT NOT NULL,
                    reward INTEGER NOT NULL,
                    PRIMARY KEY(chat_id,user_id,day,quest_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_game_points ON game_stats(chat_id, points DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_activity ON users(chat_id, message_count DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rep_target ON reputation(chat_id, target_user_id)"
            )
            await db.commit()

    async def backup_to(self, destination: str) -> None:
        """Create a consistent SQLite snapshot, including committed WAL data."""
        async with aiosqlite.connect(self.path) as source:
            async with aiosqlite.connect(destination) as target:
                await source.backup(target)

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

    async def recent_warnings(self, chat_id: int, user_id: int, limit: int = 5) -> list[dict]:
        limit = max(1, min(int(limit), 20))
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT admin_id,reason,created_at FROM warnings
                   WHERE chat_id=? AND user_id=?
                   ORDER BY id DESC LIMIT ?""",
                (chat_id, user_id, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

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

    async def log_moderation_action(
        self, chat_id: int, actor_id: int, target_id: int, action: str, details: str = ""
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO moderation_audit(
                    chat_id,actor_id,target_id,action,details,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (chat_id, actor_id, target_id, action, details[:500], _now()),
            )
            await db.commit()

    async def recent_moderation_actions(
        self, chat_id: int, limit: int = 10
    ) -> list[dict]:
        limit = max(1, min(int(limit), 50))
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT actor_id,target_id,action,details,created_at
                   FROM moderation_audit WHERE chat_id=?
                   ORDER BY id DESC LIMIT ?""",
                (chat_id, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

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
            await db.execute("""
                INSERT INTO daily_activity(chat_id,user_id,day,messages)
                VALUES(?,?,?,1)
                ON CONFLICT(chat_id,user_id,day) DO UPDATE SET
                    messages=daily_activity.messages+1
            """, (chat_id, user_id, now[:10]))
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

    async def achievement_stats(self, chat_id: int, user_id: int) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT message_count FROM users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            user_row = await cursor.fetchone()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM reputation WHERE chat_id=? AND target_user_id=?",
                (chat_id, user_id),
            )
            reputation = int((await cursor.fetchone())[0])
            cursor = await db.execute(
                "SELECT wins,played FROM game_stats WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            game_row = await cursor.fetchone() or (0, 0)
            cursor = await db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM user_items WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            items = int((await cursor.fetchone())[0])
            cursor = await db.execute(
                "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            wallet_row = await cursor.fetchone()
            return {
                "messages": int(user_row[0]) if user_row else 0,
                "reputation": reputation,
                "wins": int(game_row[0]),
                "played": int(game_row[1]),
                "items": items,
                "balance": int(wallet_row[0]) if wallet_row else 0,
            }

    async def give_reputation(self, chat_id: int, target_user_id: int, giver_user_id: int) -> bool:
        if target_user_id == giver_user_id:
            return False
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
        if reward <= 0:
            raise ValueError("Daily reward must be positive.")
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
        if amount <= 0 or sender_id == recipient_id:
            return False, await self.get_balance(chat_id, sender_id)
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


    async def add_game_result(
        self, chat_id: int, user_id: int, points: int, won: bool
    ) -> tuple[int, int, int]:
        if points < 0:
            raise ValueError("Game points cannot be negative.")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO game_stats(chat_id,user_id,points,wins,played)
                VALUES(?,?,?,?,1)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    points=game_stats.points+excluded.points,
                    wins=game_stats.wins+excluded.wins,
                    played=game_stats.played+1
            """, (chat_id, user_id, points, int(won)))
            await db.execute("""
                INSERT INTO daily_activity(chat_id,user_id,day,games,wins)
                VALUES(?,?,?,1,?)
                ON CONFLICT(chat_id,user_id,day) DO UPDATE SET
                    games=daily_activity.games+1,
                    wins=daily_activity.wins+excluded.wins
            """, (chat_id, user_id, _now()[:10], int(won)))
            cursor = await db.execute(
                "SELECT points,wins,played FROM game_stats WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            row = await cursor.fetchone()
            await db.commit()
            return int(row[0]), int(row[1]), int(row[2])

    async def exchange_game_points(
        self, chat_id: int, user_id: int, points_to_exchange: int, rate: int = 10
    ) -> tuple[bool, int, int, int]:
        """Atomically convert game points to V-coins (rate game points per coin)."""
        if points_to_exchange <= 0 or rate <= 0 or points_to_exchange % rate != 0:
            return False, 0, 0, 0
        coins = points_to_exchange // rate
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT points FROM game_stats WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            row = await cursor.fetchone()
            current_points = int(row[0]) if row else 0
            if current_points < points_to_exchange:
                balance_cursor = await db.execute(
                    "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id),
                )
                balance_row = await balance_cursor.fetchone()
                balance = int(balance_row[0]) if balance_row else 0
                await db.commit()
                return False, current_points, balance, 0

            await db.execute(
                "UPDATE game_stats SET points=points-? WHERE chat_id=? AND user_id=?",
                (points_to_exchange, chat_id, user_id),
            )
            await db.execute("""
                INSERT INTO wallets(chat_id,user_id,balance)
                VALUES(?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    balance=wallets.balance+excluded.balance
            """, (chat_id, user_id, coins))
            balance_cursor = await db.execute(
                "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            balance = int((await balance_cursor.fetchone())[0])
            await db.commit()
            return True, current_points - points_to_exchange, balance, coins

    async def top_games(self, chat_id: int, limit: int = 10) -> list[tuple[int, int, int, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT user_id,points,wins,played FROM game_stats
                WHERE chat_id=?
                ORDER BY points DESC,wins DESC,played ASC,user_id ASC LIMIT ?
            """, (chat_id, limit))
            return [
                (int(row[0]), int(row[1]), int(row[2]), int(row[3]))
                for row in await cursor.fetchall()
            ]


    async def daily_quest_progress(self, chat_id: int, user_id: int) -> dict[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT messages,games,wins FROM daily_activity WHERE chat_id=? AND user_id=? AND day=?",
                (chat_id, user_id, today),
            )
            row = await cursor.fetchone() or (0, 0, 0)
            return {"messages": int(row[0]), "games": int(row[1]), "wins": int(row[2])}

    async def claimed_daily_quests(self, chat_id: int, user_id: int) -> set[str]:
        today = datetime.now(timezone.utc).date().isoformat()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT quest_id FROM daily_quest_claims WHERE chat_id=? AND user_id=? AND day=?",
                (chat_id, user_id, today),
            )
            return {str(row[0]) for row in await cursor.fetchall()}

    async def claim_daily_quest_rewards(
        self, chat_id: int, user_id: int, quests: list[tuple[str, str, int, int]]
    ) -> tuple[list[str], int]:
        today = datetime.now(timezone.utc).date().isoformat()
        claimed: list[str] = []
        total_reward = 0
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT messages,games,wins FROM daily_activity WHERE chat_id=? AND user_id=? AND day=?",
                (chat_id, user_id, today),
            )
            row = await cursor.fetchone() or (0, 0, 0)
            progress = {"messages": int(row[0]), "games": int(row[1]), "wins": int(row[2])}
            for quest_id, metric, target, reward in quests:
                if reward <= 0 or target <= 0 or progress.get(metric, 0) < target:
                    continue
                cursor = await db.execute(
                    """INSERT OR IGNORE INTO daily_quest_claims(chat_id,user_id,day,quest_id,reward)
                       VALUES(?,?,?,?,?)""",
                    (chat_id, user_id, today, quest_id, reward),
                )
                if cursor.rowcount == 1:
                    claimed.append(quest_id)
                    total_reward += reward
            if total_reward:
                await db.execute("""
                    INSERT INTO wallets(chat_id,user_id,balance) VALUES(?,?,?)
                    ON CONFLICT(chat_id,user_id) DO UPDATE SET
                        balance=wallets.balance+excluded.balance
                """, (chat_id, user_id, total_reward))
            cursor = await db.execute(
                "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            balance_row = await cursor.fetchone()
            balance = int(balance_row[0]) if balance_row else 0
            await db.commit()
        return claimed, balance

    async def get_moderation_rank(self, chat_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT rank FROM moderation_ranks WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def set_moderation_rank(
        self, chat_id: int, user_id: int, rank: int, assigned_by: int
    ) -> None:
        if rank == 0:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "DELETE FROM moderation_ranks WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id),
                )
                await db.commit()
            return
        if not 1 <= rank <= 5:
            raise ValueError("Moderation rank must be between 1 and 5.")
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO moderation_ranks(chat_id,user_id,rank,assigned_by,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    rank=excluded.rank, assigned_by=excluded.assigned_by,
                    updated_at=excluded.updated_at
            """, (chat_id, user_id, rank, assigned_by, _now()))
            await db.commit()
