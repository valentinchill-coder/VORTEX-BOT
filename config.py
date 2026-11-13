import os
import secrets
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
    mode: str
    public_url: str
    webhook_secret: str
    port: int


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "PASTE_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("Set BOT_TOKEN in your .env file or hosting environment.")

    raw_url = (
        os.getenv("PUBLIC_URL", "").strip()
        or os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    ).rstrip("/")
    if raw_url and not raw_url.startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"

    default_mode = "webhook" if raw_url else "polling"
    mode = os.getenv("BOT_MODE", default_mode).strip().lower()
    if mode not in {"polling", "webhook"}:
        raise ValueError("BOT_MODE must be either 'polling' or 'webhook'.")

    return Settings(
        bot_token=token,
        owner_ids=_parse_ids(os.getenv("OWNER_IDS", "")),
        database_path=os.getenv("DATABASE_PATH", "vortex.db"),
        mode=mode,
        public_url=raw_url,
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip() or secrets.token_urlsafe(32),
        port=int(os.getenv("PORT", "10000")),
    )
