import logging
import re

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from texts import BUTTONS, bt

# обычные эмодзи (включая флаги, вариационные селекторы и склейки)
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF☀-➿⬀-⯿←-⇿"
    "⌀-⏿■-◿⤀-⥿〰〽㊗㊙©®‼⁉"
    "™ℹ︎️‍⃣]+"
)


def fix_url(url):
    """Приводит ссылку к виду, который принимает Telegram (@name, t.me/name, tg://@name -> https://t.me/name).
    Возвращает None, если ссылку починить нельзя."""
    u = (url or "").strip()
    m = re.fullmatch(r"tg://@?([A-Za-z0-9_]{4,})", u) or re.fullmatch(r"@([A-Za-z0-9_]{4,})", u)
    if m:
        return f"https://t.me/{m.group(1)}"
    if re.match(r"^(t|telegram)\.me/", u):
        return "https://" + u
    return u if re.match(r"^(https?://|tg://)\S+$", u) else None


def strip_emoji(text):
    """Убирает обычные эмодзи из текста кнопки (когда у неё стоит премиум-эмодзи)."""
    cleaned = re.sub(r"\s{2,}", " ", EMOJI_RE.sub("", text)).strip()
    return cleaned or text


def btn(key, lang, cb=None, url=None):
    """Кнопка из настраиваемого набора: текст, премиум-эмодзи и цвет берутся из админ-панели."""
    icon = db.get_setting(f"bi:{key}")
    style = db.get_setting(f"bs:{key}", BUTTONS[key][2])
    return raw_btn(bt(key, lang), cb, url, icon=icon, style=style)


def raw_btn(text, cb=None, url=None, icon=None, style=None):
    kw = {}
    if icon:
        kw["icon_custom_emoji_id"] = icon
        text = strip_emoji(text)  # премиум-эмодзи заменяет обычное
    if style:
        kw["style"] = style
    return InlineKeyboardButton(text=text, callback_data=cb, url=url, **kw)


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


# кнопки главного меню, которые админ может скрыть
MAIN_KEYS = ("catalog", "suppliers", "orders", "profile", "refs", "promo", "lang", "reviews", "support")


def is_hidden(key):
    return db.get_setting(f"bh:{key}") == "1"


def main_kb(lang, is_admin=False):
    def b(key, cb=None, url=None):
        return None if is_hidden(key) else btn(key, lang, cb, url)

    links = []
    for key, setting, default in (("reviews", "reviews_url", config.REVIEWS_URL),
                                  ("support", "support_url", config.SUPPORT_URL)):
        u = fix_url(db.get_setting(setting, default))
        if u:
            links.append(b(key, url=u))
    rows = [
        [b("catalog", "cat")],
        [b("suppliers", f"l:c{db.suppliers_cid()}:0")],
        [b("orders", "ord:m:0"), b("profile", "profile")],
        [b("refs", "refs"), b("promo", "promo")],
        [b("lang", "lang")],
        links,
    ]
    rows = [[x for x in r if x] for r in rows]
    for c in db.custom_buttons():
        u = fix_url(c["url"])
        if u:
            rows.append([raw_btn(c["text"], url=u, icon=c["emoji_id"])])
    if is_admin:
        rows.append([raw_btn("⚙️ Админ-панель", "a:home", style="danger")])
    return kb(rows)


def menu_row(lang):
    return [btn("main_menu", lang, "menu")]


def pager(prefix, page, pages):
    """Ряд навигации ◀️ 1/3 ▶️. prefix — начало callback_data, к нему дописывается номер страницы."""
    if pages <= 1:
        return []
    row = []
    row.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}{page - 1}") if page > 0
               else InlineKeyboardButton(text=" ", callback_data="noop"))
    row.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    row.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}{page + 1}") if page < pages - 1
               else InlineKeyboardButton(text=" ", callback_data="noop"))
    return row


async def render(target, text, markup=None, photo=None):
    """Показать экран: для callback — редактируем сообщение, для сообщения — отправляем новое."""
    if isinstance(target, CallbackQuery):
        msg = target.message
        bot = target.bot
        chat_id = msg.chat.id
        has_media = isinstance(msg, Message) and bool(msg.photo or msg.document or msg.video or msg.animation)
        if not photo and isinstance(msg, Message) and not has_media:
            try:
                await msg.edit_text(text, reply_markup=markup)
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass
    else:
        bot = target.bot
        chat_id = target.chat.id
    await _send(bot, chat_id, text, markup, photo)


def _without_url_buttons(markup):
    if not markup:
        return markup
    rows = [[b for b in row if not b.url] for row in markup.inline_keyboard]
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


async def _send(bot, chat_id, text, markup, photo):
    """Отправка с запасными вариантами: битое фото приветствия или невалидная ссылка в кнопке
    не должны ломать экран (иначе /start просто молчит)."""
    try:
        if photo:
            await bot.send_photo(chat_id, photo, caption=text, reply_markup=markup)
        else:
            await bot.send_message(chat_id, text, reply_markup=markup)
        return
    except TelegramBadRequest as e:
        logging.warning("render: отправка не удалась (%s), пробую упрощённый вариант", e)
    try:
        await bot.send_message(chat_id, text, reply_markup=_without_url_buttons(markup))
    except TelegramBadRequest as e:
        logging.error("render: и упрощённая отправка не удалась: %s", e)
        await bot.send_message(chat_id, re.sub(r"<[^>]+>", "", text))


def split_custom_emoji(m: Message):
    """Из сообщения админа достаёт текст без премиум-эмодзи и id первого премиум-эмодзи."""
    text = m.text or m.caption or ""
    ents = m.entities or m.caption_entities or []
    enc = text.encode("utf-16-le")
    icon = None
    cuts = []
    for e in ents:
        if e.type == "custom_emoji":
            if icon is None:
                icon = e.custom_emoji_id
            cuts.append((e.offset, e.length))
    for off, ln in sorted(cuts, reverse=True):
        enc = enc[:off * 2] + enc[(off + ln) * 2:]
    return enc.decode("utf-16-le").strip(), icon
