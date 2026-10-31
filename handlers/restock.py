"""Админ-панель → 🗂 Товары → товар → «📢 Уведомить всех о пополнении»: рассылка всем пользователям бота
о поступлении товара со ссылкой на него. Текст — «🔥 Рассылка о пополнении» в ✏️ Оформление → 📝 Все тексты:
туда можно вставить премиум-эмодзи, бот их сохранит."""
import asyncio
import html
import re

from aiogram import Bot, F
from aiogram.types import CallbackQuery

import db
from handlers.admin import B, back, router
from handlers.shop import name_html
from services import broadcast
from texts import money, t
from ui import as_media, btn, kb, render, send_media

CAPTION_MAX = 1024


def post_text(p, lang, bot_username):
    stock = "∞" if db.unlimited(p) else f"{db.stock(p['id'])} шт." if lang != "en" else f"{db.stock(p['id'])} pcs."
    link = f"https://t.me/{bot_username}?start=p_{p['id']}"
    return t("restock_post", lang, name=name_html(p), price=money(p["price"]), stock=stock, link=link)


def post_kb(p, lang):
    return kb([[btn("open_product", lang, f"p:{p['id']}:new")]])


async def send_post(bot: Bot, chat_id, p, lang, username):
    text = post_text(p, lang, username)
    if p["photo"] and len(re.sub(r"<[^>]+>", "", text)) <= CAPTION_MAX:
        await send_media(bot, chat_id, as_media(p["photo"], p["media_type"]), text, post_kb(p, lang))
    else:
        await bot.send_message(chat_id, text, reply_markup=post_kb(p, lang))


@router.callback_query(F.data.startswith("a:rsn:"))
async def cb_restock_preview(call: CallbackQuery, bot: Bot):
    pid = int(call.data.split(":")[2])
    p = db.product(pid)
    if not p:
        return await call.answer("Товар не найден", show_alert=True)
    me = await bot.me()
    n = len(db.all_user_ids())
    await render(call, "📢 <b>Рассылка о пополнении</b>\n\nТак сообщение увидят покупатели (с фото товара, если оно есть):\n"
                       "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n\n" + post_text(p, "ru", me.username), kb([
        [B(f"✅ Разослать всем ({n})", f"a:rsn2:{pid}", style="success")],
        [B("✏️ Изменить текст рассылки", "a:tx:restock_post")],
        back(f"a:p:{pid}", "◀️ К товару"),
    ]))
    await call.answer()


@router.callback_query(F.data.startswith("a:rsn2:"))
async def cb_restock_send(call: CallbackQuery, bot: Bot):
    pid = int(call.data.split(":")[2])
    p = db.product(pid)
    if not p:
        return await call.answer("Товар не найден", show_alert=True)
    me = await bot.me()
    ids = db.all_user_ids()

    async def send(b, uid):
        u = db.get_user(uid)
        await send_post(b, uid, p, u["lang"] if u else "ru", me.username)

    asyncio.create_task(broadcast(bot, ids, send, call.from_user.id))
    await render(call, f"📢 Рассылка о пополнении «{html.escape(p['name'])}» запущена на {len(ids)} пользователей.\n"
                       "Когда закончится — пришлю отчёт.", kb([back(f"a:p:{pid}", "◀️ К товару")]))
    await call.answer("Рассылка запущена")
