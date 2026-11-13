import html
import re
import time

from aiogram import BaseMiddleware, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery, WebAppInfo,
)

import config
import db
import gate
import payments
import post

router = Router()

DOCS_TEXT = "<b>Документы</b>\n\nИспользуя бота, вы принимаете условия этих документов."


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя и отсекает забаненных."""

    async def __call__(self, handler, event, data):
        tg_user = data.get("event_from_user")
        if tg_user and not tg_user.is_bot:
            user, is_new = await db.upsert_user(tg_user.id, tg_user.username, tg_user.first_name, tg_user.is_premium)
            if user["banned"] and tg_user.id not in config.ADMIN_IDS:
                return
            data["user"], data["is_new"] = user, is_new
        return await handler(event, data)


def button(text, emoji_id="", **kwargs):
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(text=text, **kwargs)


def menu_kb(settings, plain=False):
    def emoji(key):
        return "" if plain else settings[f"btn_{key}_emoji"]

    rows = []
    if config.WEBAPP_URL:
        rows.append([button(settings["btn_app_text"], emoji("app"), web_app=WebAppInfo(url=config.WEBAPP_URL))])
    rows.append([button("📊 Статистика", callback_data="stats")])
    rows.append([button(settings["btn_support_text"], emoji("support"), url=config.SUPPORT_URL),
                 button(settings["btn_docs_text"], emoji("docs"), callback_data="docs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def strip_custom_emoji(text):
    return re.sub(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", r"\1", text)


async def send_menu(message: Message, first_name):
    settings = await db.get_settings()
    text = settings["greeting"].replace("{name}", html.escape(first_name or "друг"))
    try:
        await message.answer(text, reply_markup=menu_kb(settings))
    except TelegramBadRequest:
        # премиум-эмодзи недоступны боту (у владельца нет Premium) — шлём без них
        await message.answer(strip_custom_emoji(text), reply_markup=menu_kb(settings, plain=True))


async def send_gate(message: Message, missing):
    rows = [[InlineKeyboardButton(text=c["title"], url=c["url"])] for c in missing]
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    await message.answer("Чтобы пользоваться ботом, подпишитесь на каналы:",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, user: dict, is_new: bool):
    args = command.args or ""
    if is_new and args.startswith("ref") and args[3:].isdigit():
        await db.set_referrer(user["id"], int(args[3:]))
    missing = await gate.missing_channels(user["id"])
    if missing:
        return await send_gate(message, missing)
    await send_menu(message, user["first_name"])


@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery, user: dict):
    missing = await gate.missing_channels(user["id"])
    if missing:
        return await call.answer("Вы подписались не на все каналы", show_alert=True)
    await call.message.delete()
    await send_menu(call.message, user["first_name"])
    await call.answer()


@router.callback_query(F.data == "docs")
async def docs(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Политика конфиденциальности", url=config.POLICY_URL)],
        [InlineKeyboardButton(text="Пользовательское соглашение", url=config.OFFER_URL)],
        [InlineKeyboardButton(text="‹ Назад", callback_data="menu")],
    ])
    await call.message.edit_text(DOCS_TEXT, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "menu")
async def back_to_menu(call: CallbackQuery, user: dict):
    await call.message.delete()
    await send_menu(call.message, user["first_name"])
    await call.answer()


# ---------- оплата звёздами ----------

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload
    ok = payload.startswith("pay:") and bool(
        await db.one("SELECT 1 FROM payments WHERE id=? AND user_id=?", int(payload[4:]), query.from_user.id))
    await query.answer(ok=ok, error_message=None if ok else "Счёт не найден, создайте новый")


@router.message(F.successful_payment)
async def paid(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("pay:"):
        await payments.credit(int(payload[4:]))


# ---------- статистика ----------

def stats_text(s: dict, title="📊 <b>Статистика рассылок</b>") -> str:
    def block(name, d):
        return (f"<b>{name}</b>\n"
                f"✉️ Отправлено: <b>{d['sent']}</b>  ·  ⏭ Пропущено: {d['failed']}\n"
                f"🔄 Кругов: <b>{d['rounds']}</b>  ·  ➕ Автоподписок: {d['joined']}")
    return "\n\n".join([title, block("Сегодня", s["today"]), block("Вчера", s["yesterday"]),
                         block("За 7 дней", s["week"]), block("За всё время", s["total"])])


async def user_stats_text(user_id) -> str:
    s = await db.stats_summary(user_id)
    rows = await db.all(
        "SELECT m.status, m.sent, m.rounds, m.next_run, a.name account, "
        "(SELECT COUNT(*) FROM mailing_chats c WHERE c.mailing_id=m.id AND c.active=1) chats "
        "FROM mailings m JOIN accounts a ON a.id=m.account_id WHERE m.user_id=? ORDER BY m.id DESC LIMIT 10", user_id)
    text = stats_text(s)
    if rows:
        now = int(time.time())
        lines = []
        for r in rows:
            if r["status"] == "active":
                left = max(0, r["next_run"] - now)
                state = f"🟢 следующий круг через {left // 60} мин" if left else "🟢 идёт круг"
            else:
                state = "⏸ остановлена"
            lines.append(f"• {html.escape(r['account'])}: {r['chats']} чатов, {r['rounds']} кругов, "
                         f"{r['sent']} отправлено — {state}")
        text += "\n\n<b>Рассылки</b>\n" + "\n".join(lines)
    return text


@router.message(Command("stats"))
async def stats_cmd(message: Message, user: dict):
    await message.answer(await user_stats_text(user["id"]))


@router.callback_query(F.data == "stats")
async def stats_cb(call: CallbackQuery, user: dict):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data="stats"),
                                                InlineKeyboardButton(text="‹ Меню", callback_data="menu")]])
    try:
        await call.message.edit_text(await user_stats_text(user["id"]), reply_markup=kb)
    except TelegramBadRequest:
        pass   # ничего не изменилось с прошлого нажатия
    await call.answer()


# ---------- пост для рассылки ----------
# Пользователь присылает боту пост (фото + текст, форматирование, премиум-эмодзи) —
# мини-приложение предложит взять его в рассылку.

def _is_post(message: Message) -> bool:
    if message.chat.type != "private":
        return False
    if message.photo:
        return True
    return bool(message.text) and not message.text.startswith("/")


@router.message(_is_post)
async def save_draft(message: Message, user: dict):
    text = message.text or message.caption or ""
    entities = message.entities if message.text else message.caption_entities
    file_id = message.photo[-1].file_id if message.photo else None
    limit = config.MAX_CAPTION if file_id else config.MAX_TEXT
    if len(text) > limit:
        return await message.answer(f"Слишком длинный текст: {len(text)} символов, можно до {limit}"
                                    f"{' (для поста с фото)' if file_id else ''}.")
    await db.run("INSERT OR REPLACE INTO drafts(user_id, text, entities, file_id, created_at) VALUES(?,?,?,?,?)",
                 user["id"], text, post.entities_from_message(entities), file_id, int(time.time()))
    rows = [[InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=config.WEBAPP_URL))]] \
        if config.WEBAPP_URL else []
    extra = ""
    if any(e.type == "custom_emoji" for e in entities or []):
        extra = "\n💎 Премиум-эмодзи сохранены — они отобразятся, если у аккаунта рассылки есть Telegram Premium."
    await message.answer("✅ <b>Пост сохранён для рассылки.</b>\n"
                         "Откройте приложение → «Рассылки» → «Начать рассылку» и выберите «Пост из чата»." + extra,
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
