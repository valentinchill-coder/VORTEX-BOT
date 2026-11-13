import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str) -> frozenset[int]:
    result: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            try:
                result.add(int(item))
            except ValueError as exc:
                raise ValueError(f"Invalid numeric Telegram ID in OWNER_IDS: {item}") from exc
    return frozenset(result)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_ids: frozenset[int]
    database_path: str


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("Set BOT_TOKEN in your .env file or hosting environment.")
    return Settings(
        bot_token=token,
        owner_ids=_parse_ids(os.getenv("OWNER_IDS", "")),
        database_path=os.getenv("DATABASE_PATH", "vortex.db"),
    )
