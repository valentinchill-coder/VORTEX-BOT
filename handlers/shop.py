from html import escape

import aiosqlite
from aiogram import Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from database.db import Database

router = Router()

# Prices are in V-coins. Item codes are stable identifiers used by commands.
ITEMS = {
    "rose": {"name": "🌹 Роза", "price": 100, "kind": "gift", "description": "Подарок участнику"},
    "choco": {"name": "🍫 Шоколад", "price": 250, "kind": "gift", "description": "Сладкий подарок"},
    "trophy": {"name": "🏆 Кубок", "price": 1000, "kind": "collectible", "description": "Коллекционный предмет"},
    "crown": {"name": "👑 Корона", "price": 2500, "kind": "collectible", "description": "Редкий коллекционный предмет"},
    "lucky_charm": {"name": "🍀 Талисман удачи", "price": 400, "kind": "consumable", "description": "Используй, чтобы получить +5 игровых очков"},
}


async def initialize_shop(db: Database) -> None:
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_items (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                item_code TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                PRIMARY KEY(chat_id, user_id, item_code)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                item_code TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                price_each INTEGER NOT NULL CHECK(price_each > 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_chat ON market_listings(chat_id, id)"
        )
        await conn.commit()


def _group(message: Message) -> bool:
    return message.chat.type != ChatType.PRIVATE


def _args(message: Message) -> list[str]:
    return (message.text or "").split()[1:]


async def _add_item(conn, chat_id: int, user_id: int, code: str, quantity: int) -> None:
    await conn.execute("""
        INSERT INTO user_items(chat_id,user_id,item_code,quantity) VALUES(?,?,?,?)
        ON CONFLICT(chat_id,user_id,item_code)
        DO UPDATE SET quantity=user_items.quantity+excluded.quantity
    """, (chat_id, user_id, code, quantity))


@router.message(Command("shop"))
async def shop_command(message: Message):
    if not _group(message):
        await message.answer("Магазин доступен в группе.")
        return
    lines = ["🛒 <b>Магазин VORTEX</b>", ""]
    for code, item in ITEMS.items():
        lines.append(
            f"{item['name']} — <b>{item['price']} V-coins</b>\n"
            f"<code>{code}</code> · {item['description']}"
        )
    lines.extend([
        "",
        "Покупка: <code>/buyitem rose 2</code>",
        "Инвентарь: <code>/inventory</code>",
    ])
    await message.answer("\n".join(lines))


@router.message(Command("buyitem"))
async def buy_item_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Покупки доступны в группе.")
        return
    args = _args(message)
    if not args or args[0] not in ITEMS:
        await message.answer("Укажи код предмета из /shop. Пример: /buyitem rose 2")
        return
    if len(args) > 2 or (len(args) == 2 and not args[1].isdigit()):
        await message.answer("Формат: /buyitem rose 2")
        return
    quantity = int(args[1]) if len(args) == 2 else 1
    if not 1 <= quantity <= 100:
        await message.answer("Количество должно быть от 1 до 100.")
        return
    item = ITEMS[args[0]]
    total = item["price"] * quantity
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute(
            "INSERT OR IGNORE INTO wallets(chat_id,user_id,balance) VALUES(?,?,0)",
            (message.chat.id, message.from_user.id),
        )
        cur = await conn.execute(
            "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
            (message.chat.id, message.from_user.id),
        )
        balance = int((await cur.fetchone())[0])
        if balance < total:
            await conn.rollback()
            await message.answer(f"Не хватает монет. Нужно {total}, у тебя {balance} V-coins.")
            return
        await conn.execute(
            "UPDATE wallets SET balance=balance-? WHERE chat_id=? AND user_id=?",
            (total, message.chat.id, message.from_user.id),
        )
        await _add_item(conn, message.chat.id, message.from_user.id, args[0], quantity)
        await conn.commit()
    await message.answer(
        f"✅ Куплено: {item['name']} ×{quantity}\n"
        f"Списано: {total} V-coins\nОстаток: {balance-total} V-coins"
    )


@router.message(Command("inventory"))
async def inventory_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Инвентарь доступен в группе.")
        return
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute(
            "SELECT item_code,quantity FROM user_items WHERE chat_id=? AND user_id=? AND quantity>0 ORDER BY item_code",
            (message.chat.id, message.from_user.id),
        )
        rows = await cur.fetchall()
    if not rows:
        await message.answer("🎒 Инвентарь пуст. Загляни в /shop.")
        return
    lines = ["🎒 <b>Твой инвентарь</b>", ""]
    for code, quantity in rows:
        item = ITEMS.get(code)
        label = item["name"] if item else code
        lines.append(f"{label} × <b>{quantity}</b> · <code>{code}</code>")
    lines.extend(["", "Использовать: <code>/useitem lucky_charm</code>",
                  "Подарить ответом на сообщение: <code>/giftitem rose 1</code>",
                  "Продать на рынке: <code>/sellitem rose 1 150</code>"])
    await message.answer("\n".join(lines))


@router.message(Command("giftitem"))
async def gift_item_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Передача предметов доступна в группе.")
        return
    target_message = message.reply_to_message
    if not target_message or not target_message.from_user:
        await message.answer("Ответь на сообщение получателя: /giftitem rose 1")
        return
    target = target_message.from_user
    args = _args(message)
    if len(args) not in (1, 2) or args[0] not in ITEMS:
        await message.answer("Формат: /giftitem rose 1")
        return
    quantity = int(args[1]) if len(args) == 2 and args[1].isdigit() else (1 if len(args) == 1 else 0)
    if not 1 <= quantity <= 100 or target.is_bot or target.id == message.from_user.id:
        await message.answer("Проверь количество и получателя. Себе и ботам дарить нельзя.")
        return
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT quantity FROM user_items WHERE chat_id=? AND user_id=? AND item_code=?",
            (message.chat.id, message.from_user.id, args[0]),
        )
        row = await cur.fetchone()
        if not row or int(row[0]) < quantity:
            await conn.rollback()
            await message.answer("Недостаточно предметов в инвентаре.")
            return
        await conn.execute(
            "UPDATE user_items SET quantity=quantity-? WHERE chat_id=? AND user_id=? AND item_code=?",
            (quantity, message.chat.id, message.from_user.id, args[0]),
        )
        await _add_item(conn, message.chat.id, target.id, args[0], quantity)
        await conn.commit()
    await message.answer(
        f"🎁 {escape(message.from_user.full_name)} передал(а) "
        f"{escape(target.full_name)}: {ITEMS[args[0]]['name']} ×{quantity}."
    )


@router.message(Command("useitem"))
async def use_item_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Использовать предметы можно в группе.")
        return
    args = _args(message)
    if len(args) != 1 or args[0] not in ITEMS:
        await message.answer("Формат: /useitem lucky_charm. Список предметов: /shop")
        return
    code = args[0]
    item = ITEMS[code]
    if item["kind"] != "consumable":
        await message.answer("Этот предмет нельзя использовать. Его можно хранить, дарить или продавать.")
        return
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT quantity FROM user_items WHERE chat_id=? AND user_id=? AND item_code=?",
            (message.chat.id, message.from_user.id, code),
        )
        row = await cur.fetchone()
        if not row or int(row[0]) < 1:
            await conn.rollback()
            await message.answer("У тебя нет такого предмета. Купить: /buyitem lucky_charm")
            return
        await conn.execute(
            "UPDATE user_items SET quantity=quantity-1 WHERE chat_id=? AND user_id=? AND item_code=?",
            (message.chat.id, message.from_user.id, code),
        )
        await conn.execute("""
            INSERT INTO game_stats(chat_id,user_id,points,wins,played) VALUES(?,?,5,0,0)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET points=game_stats.points+5
        """, (message.chat.id, message.from_user.id))
        await conn.commit()
    await message.answer("🍀 Талисман использован! Начислено +5 игровых очков.")


@router.message(Command("sellitem"))
async def sell_item_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Рынок доступен в группе.")
        return
    args = _args(message)
    if len(args) != 3 or args[0] not in ITEMS or not args[1].isdigit() or not args[2].isdigit():
        await message.answer("Формат: /sellitem rose 2 150 (предмет, количество, цена за штуку)")
        return
    code, quantity, price = args[0], int(args[1]), int(args[2])
    if not 1 <= quantity <= 100 or not 1 <= price <= 1_000_000:
        await message.answer("Количество: 1–100, цена за штуку: 1–1 000 000.")
        return
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT quantity FROM user_items WHERE chat_id=? AND user_id=? AND item_code=?",
            (message.chat.id, message.from_user.id, code),
        )
        row = await cur.fetchone()
        if not row or int(row[0]) < quantity:
            await conn.rollback()
            await message.answer("Недостаточно предметов для выставления.")
            return
        await conn.execute(
            "UPDATE user_items SET quantity=quantity-? WHERE chat_id=? AND user_id=? AND item_code=?",
            (quantity, message.chat.id, message.from_user.id, code),
        )
        await conn.execute(
            "INSERT INTO market_listings(chat_id,seller_id,item_code,quantity,price_each) VALUES(?,?,?,?,?)",
            (message.chat.id, message.from_user.id, code, quantity, price),
        )
        await conn.commit()
    await message.answer(
        f"🏪 Выставлено на рынок: {ITEMS[code]['name']} ×{quantity}\n"
        f"Цена: {price} V-coins за штуку. Предметы зарезервированы до продажи."
    )


@router.message(Command("market"))
async def market_command(message: Message, db: Database):
    if not _group(message):
        await message.answer("Рынок доступен в группе.")
        return
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute(
            "SELECT id,seller_id,item_code,quantity,price_each FROM market_listings WHERE chat_id=? ORDER BY id DESC LIMIT 20",
            (message.chat.id,),
        )
        rows = await cur.fetchall()
    if not rows:
        await message.answer("🏪 Рынок пока пуст. Выставить предмет: /sellitem rose 1 150")
        return
    lines = ["🏪 <b>Рынок VORTEX</b>", ""]
    for listing_id, seller_id, code, quantity, price in rows:
        item = ITEMS.get(code)
        name = item["name"] if item else code
        lines.append(
            f"№<b>{listing_id}</b> · {name} ×{quantity} · "
            f"<b>{price}</b> за шт. · продавец ID <code>{seller_id}</code>\n"
            f"Купить: <code>/buylisting {listing_id}</code>"
        )
    lines.append("\nКомиссия рынка — 5% с продавца.")
    await message.answer("\n".join(lines))


@router.message(Command("buylisting"))
async def buy_listing_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Покупки на рынке доступны в группе.")
        return
    args = _args(message)
    if len(args) != 1 or not args[0].isdigit():
        await message.answer("Формат: /buylisting 12. Список: /market")
        return
    listing_id = int(args[0])
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT seller_id,item_code,quantity,price_each FROM market_listings WHERE id=? AND chat_id=?",
            (listing_id, message.chat.id),
        )
        row = await cur.fetchone()
        if not row:
            await conn.rollback()
            await message.answer("Объявление уже продано или не найдено.")
            return
        seller_id, code, quantity, price = int(row[0]), row[1], int(row[2]), int(row[3])
        if seller_id == message.from_user.id:
            await conn.rollback()
            await message.answer("Нельзя покупать собственное объявление.")
            return
        total = quantity * price
        await conn.execute(
            "INSERT OR IGNORE INTO wallets(chat_id,user_id,balance) VALUES(?,?,0)",
            (message.chat.id, message.from_user.id),
        )
        cur = await conn.execute(
            "SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
            (message.chat.id, message.from_user.id),
        )
        balance = int((await cur.fetchone())[0])
        if balance < total:
            await conn.rollback()
            await message.answer(f"Не хватает монет. Нужно {total}, у тебя {balance}.")
            return
        await conn.execute(
            "UPDATE wallets SET balance=balance-? WHERE chat_id=? AND user_id=?",
            (total, message.chat.id, message.from_user.id),
        )
        seller_credit = total * 95 // 100
        await conn.execute("""
            INSERT INTO wallets(chat_id,user_id,balance) VALUES(?,?,?)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET balance=wallets.balance+excluded.balance
        """, (message.chat.id, seller_id, seller_credit))
        await _add_item(conn, message.chat.id, message.from_user.id, code, quantity)
        await conn.execute("DELETE FROM market_listings WHERE id=?", (listing_id,))
        await conn.commit()
    await message.answer(
        f"✅ Покупка завершена: {ITEMS[code]['name']} ×{quantity}.\n"
        f"Списано: {total} V-coins. Продавец получил {seller_credit} (комиссия 5%)."
    )
