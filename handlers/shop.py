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
    "rose": {"name": "🌹 Роза", "price": 100, "kind": "consumable", "points": 2, "description": "При использовании даёт +2 игровых очка"},
    "choco": {"name": "🍫 Шоколад", "price": 250, "kind": "consumable", "points": 5, "description": "При использовании даёт +5 игровых очков"},
    "trophy": {"name": "🏆 Кубок", "price": 1000, "kind": "consumable", "points": 15, "description": "При использовании даёт +15 игровых очков"},
    "crown": {"name": "👑 Корона", "price": 2500, "kind": "consumable", "points": 40, "description": "При использовании даёт +40 игровых очков"},
    "lucky_charm": {"name": "🍀 Талисман удачи", "price": 400, "kind": "consumable", "points": 5, "description": "При использовании даёт +5 игровых очков"},
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
        points = int(item["points"])
        await conn.execute("""
            INSERT INTO game_stats(chat_id,user_id,points,wins,played) VALUES(?,?,?,0,0)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET points=game_stats.points+excluded.points
        """, (message.chat.id, message.from_user.id, points))
        await conn.commit()
    await message.answer(f"{item['name']} использован! Начислено +{points} игровых очков.")


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
        if code not in ITEMS:
            await conn.rollback()
            await message.answer("Этот предмет больше не поддерживается. Объявление нельзя купить.")
            return
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
        commission = total * 5 // 100
        seller_credit = total - commission
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


@router.message(Command("cancel_listing"))
async def cancel_listing_command(message: Message, db: Database):
    if not _group(message) or not message.from_user:
        await message.answer("Управление объявлениями доступно в группе.")
        return
    args = _args(message)
    if len(args) != 1 or not args[0].isdigit() or int(args[0]) <= 0:
        await message.answer("Формат: /cancel_listing 12. Снять можно только собственное объявление.")
        return
    listing_id = int(args[0])
    async with aiosqlite.connect(db.path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT item_code,quantity FROM market_listings "
            "WHERE id=? AND chat_id=? AND seller_id=?",
            (listing_id, message.chat.id, message.from_user.id),
        )
        row = await cur.fetchone()
        if not row:
            await conn.rollback()
            await message.answer("Собственное объявление не найдено.")
            return
        code, quantity = row[0], int(row[1])
        await conn.execute(
            "DELETE FROM market_listings WHERE id=? AND chat_id=? AND seller_id=?",
            (listing_id, message.chat.id, message.from_user.id),
        )
        await _add_item(conn, message.chat.id, message.from_user.id, code, quantity)
        await conn.commit()
    item_name = ITEMS.get(code, {}).get("name", code)
    await message.answer(f"↩️ Объявление №{listing_id} снято. Возвращено в инвентарь: {item_name} ×{quantity}.")


# Button-driven shop UI. Users can browse, buy, use and purchase market listings
# without typing bot commands.
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

def _shop_home_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Каталог", callback_data="shopui:catalog")
    kb.button(text="🎒 Инвентарь", callback_data="shopui:inventory")
    kb.button(text="🏪 Рынок", callback_data="shopui:market")
    kb.button(text="⬅️ Главное меню", callback_data="vortex:home")
    kb.adjust(1)
    return kb.as_markup()

def _catalog_keyboard():
    kb = InlineKeyboardBuilder()
    for code, item in ITEMS.items():
        kb.button(text=f"Купить {item['name']} · {item['price']} 🪙", callback_data=f"shopui:buy:{code}")
    kb.button(text="🎒 Мой инвентарь", callback_data="shopui:inventory")
    kb.button(text="⬅️ Назад", callback_data="shopui:home")
    kb.adjust(1)
    return kb.as_markup()

async def _render_inventory(message, db, user_id):
    async with aiosqlite.connect(db.path) as conn:
        cur = await conn.execute(
            "SELECT item_code,quantity FROM user_items WHERE chat_id=? AND user_id=? AND quantity>0 ORDER BY item_code",
            (message.chat.id, user_id),
        )
        rows = await cur.fetchall()
    kb = InlineKeyboardBuilder()
    lines = ["🎒 <b>Твой инвентарь</b>", ""]
    if not rows:
        lines.append("Пока пусто. Загляни в каталог!")
    for code, qty in rows:
        item = ITEMS.get(code)
        if not item:
            continue
        lines.append(f"{item['name']} × <b>{qty}</b>")
        if item["kind"] == "consumable":
            kb.button(text=f"🍀 Использовать {item['name']}", callback_data=f"shopui:use:{code}")
        kb.button(text=f"🎁 Подарить {item['name']}", callback_data=f"shopui:gift:{code}")
        kb.button(text=f"🏷 Продать {item['name']}", callback_data=f"shopui:sell:{code}")
    kb.button(text="🛍 Каталог", callback_data="shopui:catalog")
    kb.button(text="🏪 Рынок", callback_data="shopui:market")
    kb.button(text="⬅️ Назад", callback_data="shopui:home")
    kb.adjust(1)
    await message.answer("\n".join(lines), reply_markup=kb.as_markup())

@router.callback_query(lambda q: q.data and q.data.startswith("shopui:") and not q.data.startswith(("shopui:gift:", "shopui:sell:")))
async def shop_ui_callback(query: CallbackQuery, db: Database):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await query.answer("Открой магазин в группе.", show_alert=True)
        return
    parts = query.data.split(":")
    action = parts[1]
    if action == "home":
        await query.message.answer("🛒 <b>Предметы и рынок VORTEX</b>", reply_markup=_shop_home_keyboard())
    elif action == "catalog":
        lines = ["🛍 <b>Каталог магазина</b>", ""]
        for item in ITEMS.values():
            lines.append(f"{item['name']} — <b>{item['price']} V-coins</b>\n{item['description']}")
        await query.message.answer("\n".join(lines), reply_markup=_catalog_keyboard())
    elif action == "buy" and len(parts) == 3 and parts[2] in ITEMS:
        code = parts[2]
        item = ITEMS[code]
        async with aiosqlite.connect(db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute("INSERT OR IGNORE INTO wallets(chat_id,user_id,balance) VALUES(?,?,0)",
                               (query.message.chat.id, query.from_user.id))
            cur = await conn.execute("SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                                     (query.message.chat.id, query.from_user.id))
            balance = int((await cur.fetchone())[0])
            if balance < item["price"]:
                await conn.rollback()
                await query.answer(f"Не хватает монет: нужно {item['price']}, у тебя {balance}.", show_alert=True)
                return
            await conn.execute("UPDATE wallets SET balance=balance-? WHERE chat_id=? AND user_id=?",
                               (item["price"], query.message.chat.id, query.from_user.id))
            await _add_item(conn, query.message.chat.id, query.from_user.id, code, 1)
            await conn.commit()
        await query.message.answer(f"✅ Куплено: {item['name']}\nСписано {item['price']} V-coins.")
        await query.answer("Покупка выполнена!")
        return
    elif action == "inventory":
        await _render_inventory(query.message, db, query.from_user.id)
    elif action == "use" and len(parts) == 3 and parts[2] in ITEMS:
        code = parts[2]
        item = ITEMS[code]
        if item["kind"] != "consumable":
            await query.answer("Этот предмет нельзя использовать.", show_alert=True)
            return
        async with aiosqlite.connect(db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute("SELECT quantity FROM user_items WHERE chat_id=? AND user_id=? AND item_code=?",
                                     (query.message.chat.id, query.from_user.id, code))
            row = await cur.fetchone()
            if not row or int(row[0]) < 1:
                await conn.rollback()
                await query.answer("Предмета нет в инвентаре.", show_alert=True)
                return
            await conn.execute("UPDATE user_items SET quantity=quantity-1 WHERE chat_id=? AND user_id=? AND item_code=?",
                               (query.message.chat.id, query.from_user.id, code))
            points = int(item["points"])
            await conn.execute("""
                INSERT INTO game_stats(chat_id,user_id,points,wins,played) VALUES(?,?,?,0,0)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET points=game_stats.points+excluded.points
            """, (query.message.chat.id, query.from_user.id, points))
            await conn.commit()
        await query.message.answer(f"{item['name']} использован! Начислено +{points} игровых очков.")
    elif action == "market":
        async with aiosqlite.connect(db.path) as conn:
            cur = await conn.execute(
                "SELECT id,seller_id,item_code,quantity,price_each FROM market_listings WHERE chat_id=? ORDER BY id DESC LIMIT 15",
                (query.message.chat.id,),
            )
            rows = await cur.fetchall()
        kb = InlineKeyboardBuilder()
        lines = ["🏪 <b>Рынок VORTEX</b>", ""]
        if not rows:
            lines.append("Пока нет объявлений.")
        for listing_id, seller_id, code, qty, price in rows:
            label = ITEMS.get(code, {}).get("name", code)
            lines.append(f"№{listing_id} · {label} ×{qty} · {price} за шт.")
            if seller_id != query.from_user.id:
                kb.button(text=f"Купить лот №{listing_id}", callback_data=f"shopui:listing:{listing_id}")
            else:
                kb.button(text=f"↩️ Снять свой лот №{listing_id}", callback_data=f"shopui:cancel:{listing_id}")
        kb.button(text="🛍 Каталог", callback_data="shopui:catalog")
        kb.button(text="⬅️ Назад", callback_data="shopui:home")
        kb.adjust(1)
        await query.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    elif action == "cancel" and len(parts) == 3 and parts[2].isdigit():
        listing_id = int(parts[2])
        async with aiosqlite.connect(db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT item_code,quantity FROM market_listings "
                "WHERE id=? AND chat_id=? AND seller_id=?",
                (listing_id, query.message.chat.id, query.from_user.id),
            )
            row = await cur.fetchone()
            if not row:
                await conn.rollback()
                await query.answer("Собственное объявление не найдено.", show_alert=True)
                return
            code, qty = row[0], int(row[1])
            await conn.execute(
                "DELETE FROM market_listings WHERE id=? AND chat_id=? AND seller_id=?",
                (listing_id, query.message.chat.id, query.from_user.id),
            )
            await _add_item(conn, query.message.chat.id, query.from_user.id, code, qty)
            await conn.commit()
        item_name = ITEMS.get(code, {}).get("name", code)
        await query.message.answer(f"↩️ Лот №{listing_id} снят. Возвращено: {item_name} ×{qty}.")
    elif action == "listing" and len(parts) == 3 and parts[2].isdigit():
        listing_id = int(parts[2])
        async with aiosqlite.connect(db.path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT seller_id,item_code,quantity,price_each FROM market_listings WHERE id=? AND chat_id=?",
                (listing_id, query.message.chat.id),
            )
            row = await cur.fetchone()
            if not row:
                await conn.rollback()
                await query.answer("Лот уже недоступен.", show_alert=True)
                return
            seller_id, code, qty, price = int(row[0]), row[1], int(row[2]), int(row[3])
            if code not in ITEMS:
                await conn.rollback()
                await query.answer("Этот предмет больше не поддерживается.", show_alert=True)
                return
            if seller_id == query.from_user.id:
                await conn.rollback()
                await query.answer("Нельзя купить собственный лот.", show_alert=True)
                return
            total = qty * price
            await conn.execute("INSERT OR IGNORE INTO wallets(chat_id,user_id,balance) VALUES(?,?,0)",
                               (query.message.chat.id, query.from_user.id))
            cur = await conn.execute("SELECT balance FROM wallets WHERE chat_id=? AND user_id=?",
                                     (query.message.chat.id, query.from_user.id))
            balance = int((await cur.fetchone())[0])
            if balance < total:
                await conn.rollback()
                await query.answer(f"Нужно {total} V-coins, у тебя {balance}.", show_alert=True)
                return
            await conn.execute("UPDATE wallets SET balance=balance-? WHERE chat_id=? AND user_id=?",
                               (total, query.message.chat.id, query.from_user.id))
            commission = total * 5 // 100
            seller_credit = total - commission
            await conn.execute("""
                INSERT INTO wallets(chat_id,user_id,balance) VALUES(?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET balance=wallets.balance+excluded.balance
            """, (query.message.chat.id, seller_id, seller_credit))
            await _add_item(conn, query.message.chat.id, query.from_user.id, code, qty)
            await conn.execute("DELETE FROM market_listings WHERE id=?", (listing_id,))
            await conn.commit()
        await query.message.answer(f"✅ Лот №{listing_id} куплен. Списано {total} V-coins.")
    else:
        await query.answer("Неизвестное действие.", show_alert=True)
        return
    await query.answer()


# Pending button-driven gift/listing flows. The user replies with ordinary text,
# never a slash command.
_pending_shop_action: dict[tuple[int, int], tuple[str, str]] = {}

@router.callback_query(lambda q: q.data and q.data.startswith("shopui:gift:"))
async def gift_button_callback(query: CallbackQuery):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await query.answer("Подарки доступны в группе.", show_alert=True)
        return
    code = query.data.split(":")[-1]
    if code not in ITEMS:
        await query.answer("Предмет не найден.", show_alert=True)
        return
    _pending_shop_action[(query.message.chat.id, query.from_user.id)] = ("gift", code)
    await query.message.answer(
        f"🎁 Чтобы подарить {ITEMS[code]['name']}, ответь на сообщение получателя числом количества (например, 2)."
    )
    await query.answer()

@router.callback_query(lambda q: q.data and q.data.startswith("shopui:sell:"))
async def sell_button_callback(query: CallbackQuery):
    if not query.message or not query.from_user:
        await query.answer()
        return
    if query.message.chat.type == ChatType.PRIVATE:
        await query.answer("Продажа доступна в группе.", show_alert=True)
        return
    code = query.data.split(":")[-1]
    if code not in ITEMS:
        await query.answer("Предмет не найден.", show_alert=True)
        return
    _pending_shop_action[(query.message.chat.id, query.from_user.id)] = ("sell", code)
    await query.message.answer(
        f"🏷 Продажа {ITEMS[code]['name']}. Отправь обычным сообщением два числа: количество и цену за штуку. Например: <code>2 150</code>."
    )
    await query.answer()

@router.message(Command("cancel"), lambda m: m.chat.type != ChatType.PRIVATE and m.from_user is not None
                and (m.chat.id, m.from_user.id) in _pending_shop_action)
async def cancel_shop_action(message: Message):
    if message.from_user:
        _pending_shop_action.pop((message.chat.id, message.from_user.id), None)
    await message.answer("Операция с предметом отменена.")


@router.message(lambda m: m.chat.type != ChatType.PRIVATE and m.from_user is not None
                and (m.chat.id, m.from_user.id) in _pending_shop_action
                and not (m.text or "").startswith("/"))
async def handle_shop_plain_input(message: Message, db: Database):
    if not message.from_user:
        return
    key = (message.chat.id, message.from_user.id)
    action, code = _pending_shop_action.get(key, ("", ""))
    if action == "gift":
        recipient_message = message.reply_to_message
        if not recipient_message or not recipient_message.from_user:
            await message.answer("Для подарка ответь на сообщение нужного участника.")
            return
        recipient = recipient_message.from_user
        if recipient.is_bot or recipient.id == message.from_user.id:
            await message.answer("Нельзя подарить предмет себе или боту.")
            return
        try:
            quantity = int((message.text or "").strip())
        except ValueError:
            await message.answer("Отправь количество предметов числом, ответив на сообщение получателя.")
            return
        if not 1 <= quantity <= 100:
            await message.answer("Количество должно быть от 1 до 100.")
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
                await message.answer("Недостаточно предметов в инвентаре.")
                return
            await conn.execute(
                "UPDATE user_items SET quantity=quantity-? WHERE chat_id=? AND user_id=? AND item_code=?",
                (quantity, message.chat.id, message.from_user.id, code),
            )
            await _add_item(conn, message.chat.id, recipient.id, code, quantity)
            await conn.commit()
        _pending_shop_action.pop(key, None)
        await message.answer(f"🎁 Подарок отправлен: {ITEMS[code]['name']} ×{quantity} для {escape(recipient.full_name)}.")
        return
    if action == "sell":
        parts = (message.text or "").split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await message.answer("Введи два числа: количество и цену за штуку. Например: <code>2 150</code>.")
            return
        quantity, price = map(int, parts)
        if not 1 <= quantity <= 100 or not 1 <= price <= 1_000_000:
            await message.answer("Количество должно быть 1–100, цена — 1–1 000 000.")
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
                await message.answer("Недостаточно предметов для продажи.")
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
        _pending_shop_action.pop(key, None)
        await message.answer(f"🏪 Выставлено: {ITEMS[code]['name']} ×{quantity}, цена {price} V-coins за штуку.")
