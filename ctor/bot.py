"""Бот-конструктор: меню, мастер создания магазина, баланс, «Мои боты».

Мастер (7 шагов): 1 цвет → 2 стиль → 3 заголовок → 4 описание (в мини-приложении или кнопками в чате)
→ 5 приветствие → 6 поддержка → 7 токен (в чате) → «Проверь данные магазина» → ✅ Всё верно → магазин создан.
Данные копятся в черновике (ctor_drafts), следующий шаг — первый незаполненный (core.next_step), поэтому
«✏️ Изменить» просто стирает одно поле и снова спрашивает только его.

Созданный магазин — обычный бот клиента (hosting.py) с отметкой source='ctor'. Его настройки (цвет, стиль,
заголовок, описание, приветствие, поддержка) записываются в базу магазина до первого запуска.
"""
import asyncio
import html
import json
import logging
import os
import sqlite3

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import BotCommand, CallbackQuery, Message

import appcfg
import config
import db
import hosting
from ctor import core
from ctor.core import bt, money, tx
from ui import fix_url, kb, media_of, raw_btn, render, send_media

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")

_bot = None       # бот-конструктор (None — не запущен)
_me = None
_dp = None
_task = None
_busy = set()     # кто сейчас создаёт магазин (защита от двойного нажатия)
_tok_busy = set()

INPUT_STEPS = {"hex", "title", "desc", "welcome", "support", "token", "retoken", "amount", "receipt"}


# ======================= запуск =======================
class Mw(BaseMiddleware):
    """Регистрирует пользователя конструктора и не пускает заблокированных."""

    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u is None or u.is_bot:
            return await handler(event, data)
        row = core.touch_user(u)
        if row["banned"] and u.id not in config.ADMINS:
            if isinstance(event, CallbackQuery):
                return await event.answer(core.plain(tx("banned")), show_alert=True)
            if isinstance(event, Message) and event.chat.type == "private":
                return await event.answer(tx("banned"))
            return None
        data["cu"] = row
        if u.id not in config.ADMINS and not (isinstance(event, CallbackQuery) and event.data == "c:subchk"):
            if isinstance(event, Message) and event.chat.type != "private":
                return await handler(event, data)
            need = await sub_missing(data["bot"], u.id)
            if need:
                return await sub_prompt(event, need)
        return await handler(event, data)


# ======================= обязательная подписка =======================
async def sub_missing(b, uid):
    """Каналы, на которые пользователь ещё не подписан (настраиваются в /admin → 📣 Обязательная подписка)."""
    import subscription
    try:
        return await subscription.missing(b, uid)
    except Exception as e:
        log.warning("конструктор: проверка подписки не удалась: %s", e)
        return []


def sub_text_kb(need):
    lines = "\n".join(f"• {html.escape(c['title'] or str(c['chat_id']))}" for c in need)
    rows = [[raw_btn(f"📣 {c['title'] or 'Канал'}"[:60], url=c["url"])] for c in need if c["url"]]
    rows.append([B("sub_check", "c:subchk")])
    return tx("sub_prompt", channels=lines), kb(rows)


async def sub_prompt(event, need):
    text, markup = sub_text_kb(need)
    if isinstance(event, CallbackQuery):
        await event.answer()
        return await out(event, text, markup)
    if isinstance(event, Message):
        return await event.answer(text, reply_markup=markup)


def running():
    return _bot is not None and _task is not None and not _task.done()


def bot():
    return _bot


def username():
    return (_me.username if _me else None) or core.get("username")


def link():
    """Ссылка на конструктор для кнопки «Создать своего бота» в магазинах клиентов."""
    u = username()
    return f"https://t.me/{u}" if u else ""


def app_url():
    base = appcfg.public_url()
    return f"{base}/c/app" if base.startswith("https://") else None


def main_bot_id():
    """id основного магазина @heliys_shop_bot — его токен нельзя подключить как магазин клиента."""
    try:
        return int(config.BOT_TOKEN.split(":", 1)[0]) if not config.CTOR_MODE else MAIN_SHOP_ID
    except ValueError:
        return 0


MAIN_SHOP_ID = int(os.getenv("MAIN_BOT_ID") or 0)  # id @heliys_shop_bot (необязательно)


async def start():
    """Запускает конструктор, если задан токен. -> None или текст ошибки."""
    global _bot, _me, _dp, _task
    await stop()
    tok = core.token()
    if not tok:
        return "токен не задан"
    if tok == config.BOT_TOKEN and not config.CTOR_MODE:
        return "это токен основного бота"
    b = Bot(tok, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    try:
        me = await b.get_me()
    except Exception as e:
        await b.session.close()
        log.warning("конструктор не запущен: %s", e)
        return f"Telegram не принял токен ({e.__class__.__name__})"
    if _dp is None:
        from ctor import admin
        _dp = Dispatcher()
        mw = Mw()
        _dp.message.outer_middleware(mw)
        _dp.callback_query.outer_middleware(mw)
        _dp.include_routers(admin.router, router)
    _bot, _me = b, me
    core.put("username", me.username)
    try:
        await b.delete_webhook(drop_pending_updates=False)
        await b.set_my_commands([BotCommand(command="start", description="Главное меню")])
        await setup_menu_button()
    except Exception as e:
        log.info("конструктор: команды/кнопку меню не установил: %s", e)
    _task = asyncio.create_task(_dp.start_polling(b, handle_signals=False, close_bot_session=False))
    log.info("бот-конструктор @%s запущен", me.username)
    return None


async def wait():
    """Ждёт, пока работает поллинг конструктора (для отдельного запуска, см. main.run_constructor)."""
    if _task:
        try:
            await _task
        except asyncio.CancelledError:
            pass


async def stop():
    global _bot, _task
    t, b = _task, _bot
    _task = None
    _bot = None
    if t and not t.done():
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    if b:
        await b.session.close()


async def setup_menu_button():
    from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo
    if not _bot:
        return
    url = app_url()
    try:
        if url:
            await _bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Конструктор", web_app=WebAppInfo(url=url)))
        else:
            await _bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception as e:
        log.info("конструктор: кнопку меню не установил: %s", e)


# ======================= отправка =======================
def B(key, cb=None, url=None, web_app=None, text=None):
    """Кнопка из настраиваемого набора (текст, премиум-эмодзи и цвет меняются в /admin конструктора)."""
    return raw_btn(text or bt(key), cb, url, icon=core.bicon(key), style=core.bstyle(key), web_app=web_app)


def as_media(raw):
    if not raw or "|" not in raw:
        return None
    kind, fid = raw.split("|", 1)
    return (kind, fid)


async def out(target, text, markup=None, photo=None):
    """target — Message / CallbackQuery (как в render) или id чата (сообщения из мини-приложения)."""
    if isinstance(target, int):
        if not _bot:
            return
        try:
            if photo:
                await send_media(_bot, target, photo, text, markup)
            else:
                await _bot.send_message(target, text, reply_markup=markup)
        except Exception as e:
            log.info("конструктор: не отправил %s: %s", target, e)
        return
    await render(target, text, markup, photo=photo)


async def send(uid, text, markup=None):
    """Сообщение пользователю от конструктора. -> True, если доставлено."""
    if not _bot:
        return False
    try:
        await _bot.send_message(uid, text, reply_markup=markup)
        return True
    except Exception as e:
        log.info("конструктор: не отправил %s: %s", uid, e)
        return False


async def to_admins(text, markup=None):
    for aid in sorted(config.ADMINS):
        await send(aid, text, markup)


def uid_of(target):
    return target if isinstance(target, int) else target.from_user.id


# ======================= главное меню =======================
def trial_free(uid):
    return core.trial_days() > 0 and not db.trial_used(uid)


def days_text(n=None):
    n = core.trial_days() if n is None else n
    return f"{n} {core.days_word(n)}"


def menu_kb(uid):
    url = app_url()
    # одна кнопка мини-приложения; создание магазина — внутри него (без сайта — мастер в чате)
    rows = [[B("app", web_app=url) if url else B("create", "c:new")]]
    rows.append([B("bots", "c:bots"), B("topup", "c:top")])
    rows.append([B("support", "c:sup")])
    if uid in config.ADMINS:
        rows.append([raw_btn("⚙️ Админ-панель", "ca:home", style="danger")])
    return kb(rows)


def welcome_text(uid):
    u = core.user(uid)
    pr = money(core.price())
    trial = (tx("trial_line", days=days_text(), price=pr) if trial_free(uid) else tx("price_line", price=pr))
    bots = len([b for b in db.user_hosted(uid) if b["token"]])
    return tx("welcome", name=html.escape((u["first_name"] if u else None) or "друг"),
              balance=money(u["balance"] if u else 0), bots=bots, trial=trial, price=pr, days=days_text())


async def show_menu(target, uid):
    await out(target, welcome_text(uid), menu_kb(uid), photo=as_media(core.get("welcome_media")))


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    uid = m.from_user.id
    d, step = core.draft(uid)
    if step in INPUT_STEPS or step == "confirm":
        core.set_step(uid, None)  # /start выводит из любого шага; данные черновика остаются
    if (command.args or "") == "create":
        return await advance(m, uid)
    await show_menu(m, uid)


@router.callback_query(F.data == "c:menu")
async def cb_menu(call: CallbackQuery):
    uid = call.from_user.id
    _, step = core.draft(uid)
    if step in INPUT_STEPS:
        core.set_step(uid, None)
    await show_menu(call, uid)
    await call.answer()


@router.callback_query(F.data == "c:subchk")
async def cb_sub_check(call: CallbackQuery, bot: Bot):
    import subscription
    subscription.forget(call.from_user.id)
    need = await sub_missing(bot, call.from_user.id)
    if need:
        return await call.answer(core.plain(tx("sub_not_yet")), show_alert=True)
    await call.answer("Спасибо! 🙌")
    await show_menu(call, call.from_user.id)


@router.callback_query(F.data == "c:sup")
async def cb_support(call: CallbackQuery):
    url = fix_url(core.support_url())
    label = html.escape(core.support_url() or "—")
    rows = [[B("support", url=url)]] if url else []
    rows.append([B("menu", "c:menu")])
    await out(call, tx("support", link=label), kb(rows))
    await call.answer()


# ======================= мастер =======================
async def advance(target, uid, d=None):
    """Сохраняет черновик и спрашивает первый незаполненный шаг (или показывает итог)."""
    if d is None:
        d, _ = core.draft(uid)
    step = core.next_step(d)
    core.save_draft(uid, d, step)
    await prompt(target, uid, step, d)


def back_row():
    return [B("menu", "c:menu")]


async def prompt(target, uid, step, d):
    if step == "color":
        items = list(core.COLORS.items())
        rows = [[raw_btn(f"{core.COLOR_EMOJI[k]} {v[0]}", f"c:col:{k}") for k, v in items[i:i + 2]]
                for i in range(0, len(items), 2)]
        rows.append([B("custom_color", "c:hex")])
        url = app_url()
        if url:
            rows.append([B("app", web_app=url + "#create")])
        rows.append(back_row())
        return await out(target, tx("step_color"), kb(rows))
    if step == "hex":
        return await out(target, tx("step_hex"), kb([[B("back", "c:e:color")], back_row()]))
    if step == "style":
        items = list(core.styles().items())
        rows = [[raw_btn(v[0], f"c:sty:{k}") for k, v in items[i:i + 2]] for i in range(0, len(items), 2)]
        rows.append(back_row())
        return await out(target, tx("step_style"), kb(rows))
    if step == "title":
        return await out(target, tx("step_title"), kb([back_row()]))
    if step == "desc":
        ideas = core.desc_ideas(d.get("title"))
        rows = [[raw_btn(("💡 " + s)[:60], f"c:idea:{i}")] for i, s in enumerate(ideas)]
        rows.append(back_row())
        return await out(target, tx("step_desc"), kb(rows))
    if step == "welcome":
        return await out(target, tx("step_welcome"), kb([[B("default_welcome", "c:dw")], back_row()]))
    if step == "support":
        rows = []
        u = core.user(uid)
        if u and u["username"]:
            rows.append([B("my_support", "c:ms", text=f"{bt('my_support')} · @{u['username']}")])
        rows.append([B("skip", "c:skip")])
        rows.append(back_row())
        return await out(target, tx("step_support"), kb(rows))
    if step == "token":
        return await out(target, tx("step_token"), kb([[B("botfather", url="https://t.me/BotFather")], back_row()]))
    if step == "confirm":
        return await show_summary(target, uid, d)


def summary_text(uid, d):
    u = core.user(uid)
    sup = d.get("support") or ""
    welcome_note = "✅ своё" if d.get("welcome") and not d.get("welcome_default") else "✨ готовое"
    if d.get("wmedia"):
        welcome_note += {"photo": " · с фото", "video": " · с видео", "animation": " · с GIF"}.get(d["wmedia"][0], "")
    if trial_free(uid) and not db.trial_used(tg_id=d.get("tg_id")):
        pay = tx("pay_trial", days=days_text(), price=money(core.price()))
    else:
        pay = tx("pay_price", price=money(core.price()), balance=money(u["balance"] if u else 0))
    return (tx("summary") + "\n\n<blockquote>"
            f"🎨 Цвет: <b>{html.escape(core.color_label(d))}</b>\n"
            f"🎭 Стиль: <b>{html.escape(core.style_label(d))}</b>\n"
            f"🏷 Заголовок: <b>{html.escape(d.get('title') or '—')}</b>\n"
            f"📝 Описание: {html.escape(d.get('desc') or '—')}\n"
            f"💬 Поддержка: {html.escape(sup) if sup else 'тикеты в боте'}\n"
            f"👋 Приветствие: {welcome_note}\n"
            f"🤖 Бот: @{html.escape(d.get('username') or '?')}</blockquote>\n\n" + pay)


async def show_summary(target, uid, d):
    await out(target, summary_text(uid, d), kb([
        [B("ok", "c:ok")],
        [B("edit", "c:edit"), B("preview", "c:pv")],
        back_row(),
    ]))


@router.callback_query(F.data == "c:new")
async def cb_new(call: CallbackQuery):
    await advance(call, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "c:reset")
async def cb_reset(call: CallbackQuery):
    core.drop_draft(call.from_user.id)
    await advance(call, call.from_user.id, {})
    await call.answer()


@router.callback_query(F.data.startswith("c:col:"))
async def cb_color(call: CallbackQuery):
    key = call.data[6:]
    if key not in core.COLORS:
        return await call.answer()
    d, _ = core.draft(call.from_user.id)
    d["color"] = key
    d.pop("hex", None)
    await advance(call, call.from_user.id, d)
    await call.answer(core.COLORS[key][0])


@router.callback_query(F.data == "c:hex")
async def cb_hex(call: CallbackQuery):
    uid = call.from_user.id
    d, _ = core.draft(uid)
    core.save_draft(uid, d, "hex")
    await prompt(call, uid, "hex", d)
    await call.answer()


@router.callback_query(F.data.startswith("c:sty:"))
async def cb_style(call: CallbackQuery):
    key = call.data[6:]
    if key not in core.styles():
        return await call.answer()
    d, _ = core.draft(call.from_user.id)
    d["style"] = key
    await advance(call, call.from_user.id, d)
    await call.answer()


@router.callback_query(F.data.startswith("c:idea:"))
async def cb_idea(call: CallbackQuery):
    d, _ = core.draft(call.from_user.id)
    ideas = core.desc_ideas(d.get("title"))
    i = int(call.data[7:]) if call.data[7:].isdigit() else 0
    d["desc"] = ideas[min(i, len(ideas) - 1)]
    await advance(call, call.from_user.id, d)
    await call.answer()


@router.callback_query(F.data == "c:dw")
async def cb_default_welcome(call: CallbackQuery):
    d, _ = core.draft(call.from_user.id)
    d["welcome"] = core.default_welcome(d)
    d["welcome_default"] = True
    d.pop("wmedia", None)
    await advance(call, call.from_user.id, d)
    await call.answer()


@router.callback_query(F.data.in_({"c:ms", "c:skip"}))
async def cb_support_pick(call: CallbackQuery):
    uid = call.from_user.id
    d, _ = core.draft(uid)
    u = core.user(uid)
    d["support"] = f"@{u['username']}" if call.data == "c:ms" and u and u["username"] else ""
    await advance(call, uid, d)
    await call.answer()


# ---------- ✏️ изменить ----------
EDIT_FIELDS = (("color", "🎨 Цвет"), ("style", "🎭 Стиль"), ("title", "🏷 Заголовок"), ("desc", "📝 Описание"),
               ("welcome", "👋 Приветствие"), ("support", "💬 Поддержка"), ("token", "🤖 Бот (токен)"))


@router.callback_query(F.data == "c:edit")
async def cb_edit(call: CallbackQuery):
    rows = [[raw_btn(t1, f"c:e:{k1}"), raw_btn(t2, f"c:e:{k2}")]
            for (k1, t1), (k2, t2) in zip(EDIT_FIELDS[0::2], EDIT_FIELDS[1::2])]
    rows.append([raw_btn(EDIT_FIELDS[-1][1], f"c:e:{EDIT_FIELDS[-1][0]}")])
    rows.append([B("restart", "c:reset")])
    rows.append([B("back", "c:sum")])
    await out(call, tx("edit_menu"), kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("c:e:"))
async def cb_edit_field(call: CallbackQuery):
    uid = call.from_user.id
    field = call.data[4:]
    d, _ = core.draft(uid)
    drop = {"color": ("color", "hex"), "token": ("token", "tg_id", "username", "bot_name"),
            "welcome": ("welcome", "wmedia", "welcome_default")}.get(field, (field,))
    for k in drop:
        d.pop(k, None)
    await advance(call, uid, d)
    await call.answer()


@router.callback_query(F.data == "c:sum")
async def cb_summary(call: CallbackQuery):
    await advance(call, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "c:pv")
async def cb_preview(call: CallbackQuery):
    uid = call.from_user.id
    d, _ = core.draft(uid)
    if not d.get("welcome"):
        return await call.answer(core.plain(tx("no_draft")), show_alert=True)
    u = core.user(uid)
    text = d["welcome"]
    try:
        text = text.format_map(core._Safe(name=html.escape(u["first_name"] or "друг"), balance="0₽", orders=0,
                                          status="🍃 Генин"))
    except (ValueError, IndexError, KeyError, AttributeError):
        pass
    media = tuple(d["wmedia"]) if d.get("wmedia") else None
    try:
        await out(uid, text, kb([[raw_btn("🛍 Открыть магазин", "c:noop")]]), photo=media)
    except Exception:
        pass
    await call.answer("👆 Так увидят покупатели")


@router.callback_query(F.data == "c:noop")
async def cb_noop(call: CallbackQuery):
    await call.answer("Это предпросмотр 🙂")


# ---------- ввод текста на шагах ----------
def _in_step(m: Message):
    if not m.from_user:
        return False
    return core.draft(m.from_user.id)[1] in INPUT_STEPS


@router.message(_in_step)
async def on_step_input(m: Message, bot: Bot):
    uid = m.from_user.id
    d, step = core.draft(uid)
    txt = (m.text or m.caption or "").strip()
    if txt.startswith("/") and not m.photo:
        return  # команды (кроме /start, он выше) не считаем ответом
    if step == "hex":
        h = core.norm_hex(txt)
        if not h:
            return await m.answer("Нужен цвет вида <code>#ff7a1a</code>:")
        d["color"], d["hex"] = "custom", h
        return await advance(m, uid, d)
    if step == "title":
        title = core.clean_title(txt)
        if not title:
            return await m.answer("Напиши название текстом:")
        if len(core.plain(txt).strip()) > 40:
            return await m.answer("Длинновато — до 40 символов. Ещё раз:")
        d["title"] = title
        return await advance(m, uid, d)
    if step == "desc":
        desc = core.clean_desc(txt)
        if not desc:
            return await m.answer("Напиши описание текстом:")
        if len(core.plain(txt).strip()) > 200:
            return await m.answer("Длинновато — до 200 символов. Ещё раз:")
        d["desc"] = desc
        return await advance(m, uid, d)
    if step == "welcome":
        media = media_of(m)
        body = m.html_text if (m.text or m.caption) else ""
        if not body and not media:
            return await m.answer("Пришли текст приветствия (можно с фото, видео или GIF):")
        if media and len(m.caption or "") > 1000:
            return await m.answer("С фото текст должен быть до 1000 символов. Сократи и пришли ещё раз:")
        if len(body) > 3500:
            return await m.answer("Слишком длинно — сократи до 3500 символов:")
        d["welcome"] = body or core.default_welcome(d)
        d["welcome_default"] = not body
        if media:
            d["wmedia"] = list(media)
        else:
            d.pop("wmedia", None)
        return await advance(m, uid, d)
    if step == "support":
        import re
        url = fix_url(txt)
        if not url and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", txt):
            url = "https://t.me/" + txt
        if not url:
            return await m.answer("Пришли <code>@username</code> или ссылку (https://…):")
        d["support"] = txt if txt.startswith("@") else url
        return await advance(m, uid, d)
    if step in ("token", "retoken"):
        return await on_token(m, d, step)
    if step == "amount":
        return await on_amount(m, txt)
    if step == "receipt":
        return await on_receipt(m, d, bot)


# ---------- токен ----------
async def on_token(m: Message, d, step):
    uid = m.from_user.id
    token = hosting.find_token(m.text or "")
    try:
        await m.delete()  # токен — секрет
    except Exception:
        pass
    if uid in _tok_busy:
        return
    if not token:
        return await m.answer(tx("token_format"))
    _tok_busy.add(uid)
    try:
        wait = await m.answer(tx("checking"))
        if token in (config.BOT_TOKEN, core.token()):
            return await wait.edit_text(tx("token_taken"))
        try:
            me = await hosting.check_token(token)
        except hosting.TokenError as e:
            return await wait.edit_text(tx(f"token_{e.code}"))
        if me.id in (main_bot_id(), _me.id if _me else 0):
            return await wait.edit_text(tx("token_taken"))
        if step == "retoken":
            return await _retoken(wait, uid, d, token, me)
        if db.hosted_by_tg(me.id):
            return await wait.edit_text(tx("token_taken"))
        d.update(token=token, tg_id=me.id, username=me.username, bot_name=me.first_name)
        await wait.edit_text(tx("token_ok", username=html.escape(me.username)))
        await advance(m, uid, d)
    finally:
        _tok_busy.discard(uid)


async def _retoken(wait, uid, d, token, me):
    b = db.hosted(int(d.get("_rt") or 0))
    d.pop("_rt", None)
    core.save_draft(uid, d, None)
    if not b or b["user_id"] != uid:
        return await wait.edit_text(tx("no_draft"))
    if me.id != b["tg_id"]:
        return await wait.edit_text(tx("retoken_other", username=html.escape(b["username"] or "?")))
    if b["trial_until"] and b["trial_until"] <= db.now():
        db.set_hosted(b["id"], token=token, status="expired")
        return await wait.edit_text(tx("trial_over", username=html.escape(b["username"] or "?"),
                                       price=money(core.price())), reply_markup=kb([[B("buy", f"c:buy:{b['id']}")]]))
    db.set_hosted(b["id"], token=token, status="running")
    ok = await hosting.restart(b["id"]) if hosting.is_alive(b["id"]) else await hosting.launch(b["id"])
    name = html.escape(b["username"] or "?")
    await wait.edit_text(tx("retoken_ok", username=name) if ok else tx("create_fail", username=name),
                         reply_markup=kb([[raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}")]]))


# ======================= создание магазина =======================
@router.callback_query(F.data == "c:ok")
async def cb_confirm(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    if uid in _busy:
        return await call.answer(core.plain(tx("busy")), show_alert=True)
    d, _ = core.draft(uid)
    if core.next_step(d) != "confirm":
        await call.answer()
        return await advance(call, uid, d)
    _busy.add(uid)
    try:
        await create_shop(call, uid, d, bot)
    finally:
        _busy.discard(uid)


async def create_shop(call: CallbackQuery, uid, d, bot: Bot):
    if db.hosted_by_tg(d["tg_id"]):  # пока проверяли данные, бота подключили в другом месте
        for k in ("token", "tg_id", "username", "bot_name"):
            d.pop(k, None)
        await call.answer(core.plain(tx("token_taken")), show_alert=True)
        return await advance(call, uid, d)
    trial = trial_free(uid) and not db.trial_used(tg_id=d["tg_id"])
    pr = core.price()
    if not trial and pr > 0 and not core.take_balance(uid, pr):
        u = core.user(uid)
        await call.answer()
        return await out(call, tx("no_money", price=money(pr), balance=money(u["balance"] if u else 0)),
                         kb([[B("topup", "c:top")], [B("back", "c:sum")]]))
    await call.answer()
    await out(call, tx("creating"))
    from handlers import builder
    bid = db.create_hosted(uid, 0 if trial else pr)
    fields = dict(status="running", source="ctor", cfg=json.dumps(_public_cfg(d), ensure_ascii=False),
                  token=d["token"], tg_id=d["tg_id"], username=d["username"], shop_name=d.get("title") or d["username"],
                  started=db.now())
    if trial:
        fields.update(trial=1, trial_until=builder.add_days(core.trial_days()))
    db.set_hosted(bid, **fields)
    try:
        await seed_shop(bid, d, bot)
    except Exception:
        log.exception("конструктор: не записал настройки магазина #%s", bid)
    ok = await hosting.launch(bid)
    core.drop_draft(uid)
    b = db.hosted(bid)
    name = html.escape(d["username"])
    u = core.user(uid)
    if ok:
        note = tx("created_trial", until=builder.fmt_until(b["trial_until"])) if b["trial_until"] else ""
        await out(uid, tx("created", username=name, trial=note), kb([
            [raw_btn(f"🤖 Открыть @{d['username']}", url=f"https://t.me/{d['username']}", style="success")],
            [B("bots", "c:bots"), B("menu", "c:menu")],
        ]))
        await send_curator(uid, d["username"])
    else:
        await out(uid, tx("create_fail", username=name), kb([[B("support", "c:sup")], [B("menu", "c:menu")]]))
    await to_admins(f"🏗 <b>Магазин {'создан' if ok else 'создан, но НЕ запустился'}</b> через конструктор\n\n"
                    f"🆔 #{bid} · 🤖 @{name}\n👤 {core.user_link(u)}\n"
                    + (f"🎁 Пробный до {builder.fmt_until(b['trial_until'])}" if b["trial_until"]
                       else f"💰 Оплачено с баланса: {money(pr)}"))


async def send_curator(uid, username):
    """После создания магазина: «Напиши своему куратору» с кнопкой-ссылкой."""
    cur = core.curator() or ""
    url = fix_url(cur)
    label = html.escape(cur if cur.startswith("@") else (f"@{url.rsplit('/', 1)[-1]}" if url and "t.me/" in url else cur))
    await out(uid, tx("curator_msg", curator=label or "—", username=html.escape(username or "?")),
              kb([[B("curator", url=url)]]) if url else None)


def _public_cfg(d):
    """Данные мастера для истории (без токена)."""
    return {k: v for k, v in d.items() if k not in ("token",) and not k.startswith("_")}


async def seed_shop(bid, d, bot: Bot):
    """Записывает настройки магазина в его будущую базу — бот клиента прочитает их при первом запуске."""
    path = hosting.db_path(bid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    title = html.escape(d.get("title") or "")
    vals = {
        "app_accent": core.color_hex(d),
        "app_season": d.get("style") or "none",
        "app_title": title or None,
        "app_desc": html.escape(d.get("desc") or "") or None,
        "t:welcome:ru": d.get("welcome") or None,
        "t:welcome:en": d.get("welcome") or None,
        "support_url": fix_url(d.get("support") or "") or None,
    }
    if d.get("color") == "black":
        vals["app_theme"] = "dark"
    if d.get("wmedia"):
        kind, fid = d["wmedia"]
        ext = {"photo": ".jpg", "video": ".mp4", "animation": ".mp4"}.get(kind, ".bin")
        local = os.path.join(os.path.dirname(path), f"bot_{bid}_welcome{ext}")
        await bot.download(fid, destination=local)
        vals["welcome_local"] = local
        vals["welcome_local_type"] = kind
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        for k, v in vals.items():
            if v is not None:
                con.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET "
                            "value=excluded.value", (k, str(v)))
        con.commit()
    finally:
        con.close()


# ======================= мои боты =======================
STATUS_ICON = {"running": "✅", "stopped": "⏸", "failed": "⚠️", "expired": "⌛", "wait_token": "🔑", "pending": "🔎",
               "rejected": "❌"}
STATUS_RU = {"running": "работает", "stopped": "остановлен", "failed": "не работает", "expired": "пробный закончился",
             "wait_token": "ждёт токен", "pending": "оплата на проверке", "rejected": "отклонён"}


@router.callback_query(F.data == "c:bots")
async def cb_bots(call: CallbackQuery):
    await bots_view(call, call.from_user.id)
    await call.answer()


async def bots_view(target, uid):
    from handlers import builder
    bots = [b for b in db.user_hosted(uid) if b["tg_id"]]
    if not bots:
        url = app_url()
        return await out(target, tx("no_bots"), kb([
            [B("app", web_app=url) if url else B("create", "c:new")], [B("menu", "c:menu")]]))
    text = tx("bots_head") + "\n"
    rows = []
    pr = money(core.price())
    for b in bots[:15]:
        name = f"@{html.escape(b['username'])}" if b["username"] else f"#{b['id']}"
        text += f"\n{STATUS_ICON.get(b['status'], '•')} <b>{name}</b> — {STATUS_RU.get(b['status'], b['status'])}"
        if b["trial_until"] and b["status"] != "expired":
            text += f"\n     🎁 бесплатно до {builder.fmt_until(b['trial_until'])}"
        elif not b["trial_until"]:
            text += "\n     ♾ навсегда"
        if b["status"] == "running" and b["username"]:
            rows.append([raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}")])
        if b["status"] == "failed":
            rows.append([B("new_token", f"c:rt:{b['id']}", text=f"{bt('new_token')} · @{b['username']}")])
        if b["trial_until"] and b["token"]:
            rows.append([B("buy", f"c:buy:{b['id']}", text=f"{bt('buy')} · @{b['username']} · {pr}")])
    u = core.user(uid)
    text += f"\n\n💰 Баланс: <b>{money(u['balance'] if u else 0)}</b>"
    rows.append([B("topup", "c:top"), B("menu", "c:menu")])
    await out(target, text, kb(rows))


async def buy_bot(uid, bid):
    """Покупка пробного бота навсегда с баланса. -> "ok" / "no_money" / "bad" / "busy"."""
    from handlers import builder
    b = db.hosted(bid)
    if not b or b["user_id"] != uid or not b["trial_until"]:
        return "bad"
    if uid in _busy:
        return "busy"
    _busy.add(uid)
    try:
        pr = core.price()
        if pr > 0 and not core.take_balance(uid, pr):
            return "no_money"
        db.set_hosted(bid, price=pr)
        running_now = await builder.make_permanent(_bot, b)
        name = html.escape(b["username"] or "?")
        await to_admins(f"♾ <b>Бот куплен навсегда</b> (с баланса конструктора)\n\n🤖 @{name} · #{bid}\n"
                        f"👤 {core.user_link(core.user(uid))}\n💰 {money(pr)}"
                        + ("" if running_now else "\n⚠️ Бот не запустился — смотрите лог в основном боте."))
        return "ok"
    finally:
        _busy.discard(uid)


@router.callback_query(F.data.startswith("c:buy:"))
async def cb_buy(call: CallbackQuery):
    uid = call.from_user.id
    bid = int(call.data.split(":")[2])
    res = await buy_bot(uid, bid)
    if res == "bad":
        return await call.answer("Этот бот уже куплен 🙂", show_alert=True)
    if res == "busy":
        return await call.answer()
    await call.answer()
    if res == "no_money":
        u = core.user(uid)
        return await out(call, tx("no_money", price=money(core.price()), balance=money(u["balance"] if u else 0)),
                         kb([[B("topup", "c:top")], [B("bots", "c:bots")]]))
    b = db.hosted(bid)
    await out(call, tx("bought", username=html.escape(b["username"] or "?")), kb([
        [raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}", style="success")],
        [B("bots", "c:bots"), B("menu", "c:menu")]]))


@router.callback_query(F.data.startswith("c:rt:"))
async def cb_retoken(call: CallbackQuery):
    uid = call.from_user.id
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or b["user_id"] != uid:
        return await call.answer()
    d, _ = core.draft(uid)
    d["_rt"] = bid
    core.save_draft(uid, d, "retoken")
    await out(call, tx("retoken", username=html.escape(b["username"] or "?")),
              kb([[B("botfather", url="https://t.me/BotFather")], [B("cancel", "c:bots")]]))
    await call.answer()


# ======================= пополнение баланса =======================
AMOUNTS = (100, 300, 500, 1000)


@router.callback_query(F.data == "c:top")
async def cb_topup(call: CallbackQuery):
    await topup_view(call, call.from_user.id)
    await call.answer()


async def topup_view(target, uid):
    d, _ = core.draft(uid)
    core.save_draft(uid, d, "amount")
    mn = core.topup_min()
    amounts = [a for a in AMOUNTS if a >= mn] or [int(mn)]
    rows = [[raw_btn(money(a), f"c:ta:{a}") for a in amounts]]
    rows.append([B("cancel", "c:menu")])
    await out(target, tx("topup_ask", min=money(mn)), kb(rows))


async def on_amount(m: Message, txt):
    try:
        amount = round(float(txt.replace(",", ".").replace("₽", "").strip()), 2)
    except ValueError:
        return await m.answer("Отправь сумму числом, например <code>300</code>:")
    if amount < core.topup_min() or amount > 100000:
        return await m.answer(f"Сумма — от {money(core.topup_min())} до 100000₽. Ещё раз:")
    await start_topup(m, m.from_user.id, amount)


@router.callback_query(F.data.startswith("c:ta:"))
async def cb_topup_amount(call: CallbackQuery):
    await start_topup(call, call.from_user.id, float(call.data[5:]))
    await call.answer()


async def start_topup(target, uid, amount):
    tid = core.create_topup(uid, amount)
    d, _ = core.draft(uid)
    core.save_draft(uid, d, None)
    await out(target, tx("topup_pay", amount=money(amount), details=core.sbp()), kb([
        [B("paid", f"c:tp:{tid}")],
        [B("cancel", f"c:tc:{tid}")],
    ]))


@router.callback_query(F.data.startswith("c:tp:"))
async def cb_topup_paid(call: CallbackQuery):
    uid = call.from_user.id
    tid = int(call.data[5:])
    t = core.topup(tid)
    if not t or t["user_id"] != uid or t["status"] != "wait_pay":
        return await call.answer("Заявка уже обработана", show_alert=True)
    d, _ = core.draft(uid)
    d["_tid"] = tid
    core.save_draft(uid, d, "receipt")
    await out(call, tx("topup_receipt"), kb([[B("cancel", f"c:tc:{tid}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("c:tc:"))
async def cb_topup_cancel(call: CallbackQuery):
    uid = call.from_user.id
    t = core.topup(int(call.data[5:]))
    if t and t["user_id"] == uid and t["status"] == "wait_pay":
        core.set_topup(t["id"], status="canceled")
    d, _ = core.draft(uid)
    d.pop("_tid", None)
    core.save_draft(uid, d, None)
    await call.answer("Отменено")
    await show_menu(call, uid)


async def on_receipt(m: Message, d, bot: Bot):
    uid = m.from_user.id
    if not (m.photo or m.document):
        return await m.answer(tx("topup_need_receipt"))
    t = core.topup(int(d.get("_tid") or 0))
    if not t or t["user_id"] != uid or t["status"] != "wait_pay":
        t = core.topup_wait(uid)
    d.pop("_tid", None)
    core.save_draft(uid, d, None)
    if not t:
        return await m.answer("Заявка на пополнение не найдена — начни заново.", reply_markup=kb([[B("topup", "c:top")]]))
    await send_receipt(m, t, bot)


@router.message(F.photo | F.document, lambda m: bool(m.from_user and core.topup_wait(m.from_user.id)))
async def receipt_fallback(m: Message, bot: Bot):
    """Чек прислали, не нажав «Я оплатил»."""
    await send_receipt(m, core.topup_wait(m.from_user.id), bot)


async def send_receipt(m: Message, t, bot: Bot):
    file_id = m.photo[-1].file_id if m.photo else m.document.file_id
    core.set_topup(t["id"], status="pending", receipt=file_id)
    u = core.user(m.from_user.id)
    caption = (f"💳 <b>Пополнение баланса конструктора — #{t['id']}</b>\n\n👤 {core.user_link(u)}\n"
               f"💰 Сумма: <b>{money(t['amount'])}</b>")
    markup = kb([[raw_btn("✅ Зачислить", f"ca:tok:{t['id']}", style="success"),
                  raw_btn("❌ Отклонить", f"ca:tno:{t['id']}", style="danger")]])
    for aid in sorted(config.ADMINS):
        try:
            if m.photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception as e:
            log.warning("конструктор: чек админу %s не отправлен: %s", aid, e)
    await m.answer(tx("topup_sent"), reply_markup=kb([[B("menu", "c:menu")]]))


# ======================= уведомления от hosting / builder =======================
def _buy_kb(b):
    return kb([[B("buy", f"c:buy:{b['id']}", text=f"{bt('buy')} · {money(core.price())}")], [B("bots", "c:bots")]])


async def trial_notice(b, kind):
    """Пробный период магазина из конструктора: kind = soon (за сутки) / over (выключен)."""
    from handlers import builder
    name = html.escape(b["username"] or "?")
    if kind == "soon":
        return await send(b["user_id"], tx("trial_soon", username=name, until=builder.fmt_until(b["trial_until"]),
                                           price=money(core.price())), _buy_kb(b))
    return await send(b["user_id"], tx("trial_over", username=name, price=money(core.price())),
                      _buy_kb(b) if b["token"] else None)


async def failed_notice(b):
    return await send(b["user_id"], tx("failed", username=html.escape(b["username"] or "?")),
                      kb([[B("new_token", f"c:rt:{b['id']}")], [B("bots", "c:bots")]]))
