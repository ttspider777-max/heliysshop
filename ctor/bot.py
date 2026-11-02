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
import re
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

INPUT_STEPS = {"hex", "title", "desc", "welcome", "support", "token", "retoken", "amount", "receipt", "payreceipt",
               "promo"}
_remind_task = None  # напоминания о пробном и автопокупка
_ab_lock = asyncio.Lock()


# ======================= запуск =======================
class Mw(BaseMiddleware):
    """Регистрирует пользователя конструктора и не пускает заблокированных."""

    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u is None or u.is_bot:
            return await handler(event, data)
        if u.id not in config.ADMINS and not (isinstance(event, Message) and event.successful_payment):
            import flood
            st = flood.check(u.id)
            if st != "ok":
                if st == "warn":
                    if isinstance(event, CallbackQuery):
                        await event.answer(flood.WARN_TEXT, show_alert=True)
                    elif isinstance(event, Message) and event.chat.type == "private":
                        await event.answer(flood.WARN_TEXT)
                elif isinstance(event, CallbackQuery):
                    await event.answer()
                return None
        row = core.touch_user(u)
        if isinstance(event, Message) and event.successful_payment:  # оплата уже списана — проводим всегда
            data["cu"] = row
            return await handler(event, data)
        if core.get("maint") == "1" and u.id not in config.ADMINS:  # /admin → 🛠 Техработы
            if isinstance(event, CallbackQuery):
                return await event.answer(core.plain(tx("maint"))[:190], show_alert=True)
            if isinstance(event, Message) and event.chat.type == "private":
                return await event.answer(tx("maint"))
            return None
        if row["banned"] and u.id not in config.ADMINS:
            if isinstance(event, CallbackQuery):
                return await event.answer(core.plain(core.ban_text(row))[:190], show_alert=True)
            if isinstance(event, Message) and event.chat.type == "private":
                return await event.answer(core.ban_text(row))
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
        from ctor import admin, admin2, growth
        _dp = Dispatcher()
        mw = Mw()
        _dp.message.outer_middleware(mw)
        _dp.callback_query.outer_middleware(mw)
        _dp.include_routers(admin.router, admin2.router, growth.router, router)
    _bot, _me = b, me
    core.put("username", me.username)
    try:
        await b.delete_webhook(drop_pending_updates=False)
        await b.set_my_commands([BotCommand(command="start", description="Главное меню")])
        await setup_menu_button()
    except Exception as e:
        log.info("конструктор: команды/кнопку меню не установил: %s", e)
    _task = asyncio.create_task(_dp.start_polling(b, handle_signals=False, close_bot_session=False))
    global _remind_task
    _remind_task = asyncio.create_task(remind_loop())
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
    global _bot, _task, _remind_task
    t, b = _task, _bot
    _task = None
    _bot = None
    if _remind_task and not _remind_task.done():
        _remind_task.cancel()
    _remind_task = None
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
    rows.append([B("bots", "c:bots"), B("tariffs", "c:tariffs")])
    rows.append([B("ref", "c:ref") if core.ref_percent() > 0 else None,
                 B("promo", "c:promo:m") if core.flag_on("promo_btn") else None])
    rows.append([B("course", "c:course:0") if core.flag_on("course") else None, B("support", "c:sup")])
    if core.partner_of(uid):
        rows.append([B("partner", "c:partner")])
    if uid in config.ADMINS:
        rows.append([raw_btn("⚙️ Админ-панель", "ca:home", style="danger")])
    return kb(rows)


def welcome_text(uid):
    u = core.user(uid)
    pr = money(core.price())
    mn = money(core.min_tariff_price())
    trial = (tx("trial_line", days=days_text(), price=pr, min=mn) if trial_free(uid)
             else tx("price_line", price=pr, min=mn))
    bots = len([b for b in db.user_hosted(uid) if b["token"]])
    return tx("welcome", name=html.escape((u["first_name"] if u else None) or "друг"),
              balance=money(u["balance"] if u else 0), bots=bots, trial=trial, price=pr, min=mn, days=days_text())


async def show_menu(target, uid):
    await out(target, welcome_text(uid), menu_kb(uid), photo=as_media(core.get("welcome_media")))


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    uid = m.from_user.id
    d, step = core.draft(uid)
    if step in INPUT_STEPS or step == "confirm":
        core.set_step(uid, None)  # /start выводит из любого шага; данные черновика остаются
    args = command.args or ""
    if args[:1] == "r" and args[1:].isdigit():  # реферальная ссылка t.me/<бот>?start=r<id>
        ref_id = int(args[1:])
        if core.set_referrer(uid, ref_id):
            await send(ref_id, tx("ref_joined", name=html.escape(m.from_user.first_name or "друг"),
                                  percent=pct(core.ref_percent())))
    if args.startswith("p_"):  # ссылка партнёра (админа канала): t.me/<бот>?start=p_<код>
        core.set_partner(uid, args[2:])
    if args == "create":
        return await advance(m, uid)
    if args == "course" and core.flag_on("course"):
        lessons = core.jget("course", core.COURSE)
        if lessons:
            return await out(m, lessons[0].get("x") or "—", kb([[B("course_next", "c:course:1")] if len(lessons) > 1 else [],
                                                              [B("menu", "c:menu")]]))
    await show_menu(m, uid)


def pct(v):
    return f"{int(v) if v == int(v) else v}%"


# ======================= рефералы =======================
@router.callback_query(F.data == "c:ref")
async def cb_ref(call: CallbackQuery):
    uid = call.from_user.id
    if core.ref_percent() <= 0:
        return await call.answer("Реферальная программа сейчас выключена", show_alert=True)
    invited, paid, earned = core.ref_stats(uid)
    link_ = core.ref_link(uid)
    u = core.user(uid)
    from urllib.parse import quote
    share = f"https://t.me/share/url?url={quote(link_)}&text={quote(core.plain(tx('ref_share')))}" if link_ else None
    await out(call, tx("ref", percent=pct(core.ref_percent()), invited=invited, paid=paid, earned=money(earned),
                       link=html.escape(link_ or "—"), balance=money(u["balance"] if u else 0)),
              kb([[B("ref_share", url=share)] if share else [], [B("menu", "c:menu")]]))
    await call.answer()


# ======================= промокоды =======================
def parse_ctx(ctx):
    """Откуда ввели промокод: «m» (меню), «c.<тариф>» (новый магазин), «b<id>.<тариф>» (продление). -> (k, bid, tariff)"""
    head, _, tariff = (ctx or "m").partition(".")
    tariff = tariff if tariff in core.TARIFFS else "pro"
    if head == "c":
        return "c", 0, tariff
    if head.startswith("b") and head[1:].isdigit():
        return "b", int(head[1:]), tariff
    return "m", 0, tariff


@router.callback_query(F.data.startswith("c:promo:"))
async def cb_promo(call: CallbackQuery):
    uid = call.from_user.id
    d, _ = core.draft(uid)
    d["_pb"] = call.data[8:]
    core.save_draft(uid, d, "promo")
    k, bid, tariff = parse_ctx(d["_pb"])
    back_cb = {"m": "c:menu", "c": f"c:tsel:c:0:{tariff}"}.get(k, f"c:tsel:b:{bid}:{tariff}")
    await out(call, tx("promo_ask"), kb([[B("cancel", back_cb)]]))
    await call.answer()


async def on_promo(m: Message, d, txt):
    uid = m.from_user.id
    back_to = d.get("_pb") or "m"
    p, err = core.promo_check(txt, uid)
    if err == "not_found":
        return await m.answer(tx("promo_not_found"))
    d.pop("_pb", None)
    core.save_draft(uid, d, core.next_step(d) if core.next_step(d) == "confirm" else None)
    if err:
        await m.answer(tx(f"promo_{err}"))
    elif p["kind"] == "days":
        from handlers import builder
        trials = [b for b in db.user_hosted(uid) if b["trial_until"] and b["status"] == "running"]
        if trials:
            b = min(trials, key=lambda r: r["trial_until"])
            until = builder.add_days(int(p["value"]), base=b["trial_until"])
            db.set_hosted(b["id"], trial_until=until, trial_warned=0)
            core.use_promo(p["code"], uid)
            await m.answer(tx("promo_days_ok", code=html.escape(p["code"]), username=html.escape(b["username"] or "?"),
                              until=builder.fmt_until(until)))
        else:
            core.set_user_promo(uid, p["code"])
            await m.answer(tx("promo_days_saved", code=html.escape(p["code"]), label=core.promo_label(p)))
    else:
        core.set_user_promo(uid, p["code"])
        await m.answer(tx("promo_ok", code=html.escape(p["code"]), label=core.promo_label(p)))
    k, bid, tariff = parse_ctx(back_to)
    if k == "c" and core.next_step(d) == "confirm":
        return await pay_menu(m, uid, "create", 0, tariff)
    if k == "b":
        b = db.hosted(bid)
        if b and b["user_id"] == uid and can_renew(b):
            return await pay_menu(m, uid, "buy", b["id"], tariff)
        return await bots_view(m, uid)
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
    if step == "mode":
        rows = [[B("mode_app", "c:mode:app")], [B("mode_bot", "c:mode:bot")]]
        url = app_url()
        if url:
            rows.append([B("app", web_app=url + "#create")])
        rows.append(back_row())
        return await out(target, tx("step_mode"), kb(rows))
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
    if step == "template":
        items = list(core.TEMPLATES.items())
        rows = [[raw_btn(v[0], f"c:tpl:{k}") for k, v in items[i:i + 2]] for i in range(0, len(items), 2)]
        rows.append(back_row())
        lines = "\n".join(f"{v[0]} — {v[1]}" for v in core.TEMPLATES.values())
        return await out(target, tx("step_template") + f"\n\n<blockquote>{html.escape(lines)}</blockquote>", kb(rows))
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
    if d.get("plan") == "trial" and trial_ok(uid, d):
        pay = tx("pay_trial", days=days_text(core.trial_days() + core.promo_days(uid)), price=money(core.price()),
                 min=money(core.min_tariff_price()))
    elif d.get("plan") in core.TARIFFS and core.tariff_on(d["plan"]):
        amount, _ = core.final_price(uid, d["plan"])
        pay = (f"💳 Тариф: <b>{core.tariff_name(d['plan'])}</b> — {core.tariff_period(d['plan'])}\n"
               + tx("pay_price", price=money(amount), stars=core.stars_for(amount)))
    else:
        amount = core.min_tariff_price()
        pay = tx("pay_price", price="от " + money(amount), stars=core.stars_for(amount))
    tpl = core.template_label(d)
    if d.get("template") and d["template"] != "empty":
        cats, items = core.template_counts(d["template"])
        tpl += f" · {cats} кат., {items} тов."
    look = ("📱 Вид: <b>кнопки в чате (без мини-приложения)</b>\n" if core.no_app(d) else
            "📱 Вид: <b>с мини-приложением</b>\n"
            f"🎨 Цвет: <b>{html.escape(core.color_label(d))}</b>\n"
            f"🎭 Стиль: <b>{html.escape(core.style_label(d))}</b>\n")
    return (tx("summary") + "\n\n<blockquote>" + look +
            f"🏷 Заголовок: <b>{html.escape(d.get('title') or '—')}</b>\n"
            f"📝 Описание: {html.escape(d.get('desc') or '—')}\n"
            f"🧩 Товары: {html.escape(tpl)}\n"
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


@router.callback_query(F.data.startswith("c:mode:"))
async def cb_mode(call: CallbackQuery):
    mode = call.data[7:]
    if mode not in ("app", "bot"):
        return await call.answer()
    d, _ = core.draft(call.from_user.id)
    d["mode"] = mode
    await advance(call, call.from_user.id, d)
    await call.answer()


@router.callback_query(F.data.startswith("c:tpl:"))
async def cb_template(call: CallbackQuery):
    key = call.data[6:]
    if key not in core.TEMPLATES:
        return await call.answer()
    d, _ = core.draft(call.from_user.id)
    d["template"] = key
    await advance(call, call.from_user.id, d)
    await call.answer(core.TEMPLATES[key][0])


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
EDIT_FIELDS = (("mode", "📱 Вид бота"), ("color", "🎨 Цвет"), ("style", "🎭 Стиль"), ("title", "🏷 Заголовок"), ("desc", "📝 Описание"),
               ("template", "🧩 Набор товаров"), ("welcome", "👋 Приветствие"), ("support", "💬 Поддержка"),
               ("token", "🤖 Бот (токен)"))


@router.callback_query(F.data == "c:edit")
async def cb_edit(call: CallbackQuery):
    d, _ = core.draft(call.from_user.id)
    fields = [f for f in EDIT_FIELDS if not (core.no_app(d) and f[0] in core.APP_ONLY)]
    rows = [[raw_btn(t, f"c:e:{k}") for k, t in fields[i:i + 2]] for i in range(0, len(fields), 2)]
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
    if step == "promo":
        return await on_promo(m, d, txt)
    if step == "payreceipt":
        return await on_pay_receipt(m, d, bot)
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


# ======================= создание магазина и оплата =======================
def trial_ok(uid, d=None):
    """Пробный период доступен: включён, человек его не брал и этот Telegram-бот на пробе не был."""
    return trial_free(uid) and not (d and d.get("tg_id") and db.trial_used(tg_id=d["tg_id"]))


@router.callback_query(F.data == "c:ok")
async def cb_confirm(call: CallbackQuery):
    """«✅ Всё верно»: пробный (если выбран в мини-приложении) или выбор способа оплаты."""
    uid = call.from_user.id
    if uid in _busy:
        return await call.answer(core.plain(tx("busy")), show_alert=True)
    d, _ = core.draft(uid)
    if core.next_step(d) != "confirm":
        await call.answer()
        return await advance(call, uid, d)
    if db.hosted_by_tg(d["tg_id"]):  # пока проверяли данные, бота подключили в другом месте
        for k in ("token", "tg_id", "username", "bot_name"):
            d.pop(k, None)
        await call.answer(core.plain(tx("token_taken")), show_alert=True)
        return await advance(call, uid, d)
    if d.get("plan") == "trial" and trial_ok(uid, d):
        return await start_trial(call, uid, d)
    await call.answer()
    if d.get("plan") in core.TARIFFS and core.tariff_on(d["plan"]):  # тариф выбран в мини-приложении
        return await pay_menu(call, uid, "create", 0, d["plan"])
    await tariff_view(call, uid, "c", 0)


@router.callback_query(F.data == "c:trial")
async def cb_trial(call: CallbackQuery):
    uid = call.from_user.id
    d, _ = core.draft(uid)
    if core.next_step(d) != "confirm":
        await call.answer()
        return await advance(call, uid, d)
    if not trial_ok(uid, d):
        return await call.answer(core.plain(tx("app_plan_used")), show_alert=True)
    await start_trial(call, uid, d)


async def start_trial(call: CallbackQuery, uid, d):
    if uid in _busy:
        return await call.answer(core.plain(tx("busy")), show_alert=True)
    _busy.add(uid)
    try:
        await call.answer()
        await out(call, tx("creating"))
        await do_create(uid, d, trial=True)
    finally:
        _busy.discard(uid)


# ---------- тарифы ----------
def can_renew(b):
    """Боту можно купить / продлить тариф: он на пробном или на тарифе со сроком."""
    return bool(b and b["token"] and b["trial_until"])


def tariff_desc(key):
    pr = core.tariff_price(key)
    start, medium = core.tariff_price("start"), core.tariff_price("medium")
    return tx("tariff_" + key, price=money(pr), month=money(round(pr / 3)),
              save=money(max(round(start * 3 - medium, 2), 0)))


def tariffs_text(extra=""):
    parts = [tx("tariffs_head")] + [tariff_desc(k) for k in core.tariffs_on()]
    text = "\n\n".join(parts) + extra
    if len(core.plain(text)) > 3900:  # не влезает в сообщение — только заголовок и короткие строки
        text = tx("tariffs_head") + "\n\n" + "\n".join(
            f"{core.tariff_name(k)} — <b>{money(core.tariff_price(k))}</b> · {core.tariff_period(k)}"
            for k in core.tariffs_on()) + extra
    return text


async def tariff_view(target, uid, k, bid):
    """Выбор тарифа с подробным описанием. k=c — новый магазин, k=b — продление / покупка для бота bid."""
    d, _ = core.draft(uid)
    rows = []
    if k == "c" and trial_ok(uid, d):
        rows.append([B("trial", "c:trial", text=f"{bt('trial')} — {days_text(core.trial_days() + core.promo_days(uid))}")])
    for key in core.tariffs_on():
        amount, _ = core.final_price(uid, key)
        rows.append([raw_btn(f"{core.tariff_name(key)} · {money(amount)} · {core.tariff_period(key)}",
                             f"c:tsel:{k}:{bid}:{key}", style="success" if key == "pro" else None)])
    rows.append([B("back", "c:sum" if k == "c" else "c:bots")])
    extra = ""
    if k == "b":
        b = db.hosted(bid)
        extra = f"\n\n🤖 @{html.escape((b['username'] if b else '') or '?')} — сейчас: {html.escape(core.plan_line(b))}" if b else ""
    if not core.tariffs_on():
        return await out(target, tx("pay_none"), kb([[B("support", "c:sup")], rows[-1]]))
    await out(target, tariffs_text(extra), kb(rows))


@router.callback_query(F.data.startswith("c:tar:"))
async def cb_tariff_view(call: CallbackQuery):
    """c:tar:<c|b>:<id бота>"""
    try:
        _, _, k, bid = call.data.split(":")
        bid = int(bid)
    except ValueError:
        return await call.answer()
    if k == "b":
        b = db.hosted(bid)
        if not b or b["user_id"] != call.from_user.id or not can_renew(b):
            return await call.answer("Этот бот уже куплен навсегда 🙂", show_alert=True)
    await call.answer()
    await tariff_view(call, call.from_user.id, k, bid)


@router.callback_query(F.data.startswith("c:tsel:"))
async def cb_tariff_pick(call: CallbackQuery):
    """c:tsel:<c|b>:<id бота>:<тариф> -> способы оплаты."""
    uid = call.from_user.id
    try:
        _, _, k, bid, key = call.data.split(":")
        bid = int(bid)
    except ValueError:
        return await call.answer()
    d, step = core.draft(uid)
    if step == "promo":
        core.set_step(uid, core.next_step(d) if core.next_step(d) == "confirm" else None)
    if not core.tariff_on(key):
        return await call.answer("Этот тариф сейчас недоступен", show_alert=True)
    if k == "c":
        if core.next_step(d) != "confirm":
            await call.answer()
            return await advance(call, uid, d)
        await call.answer()
        return await pay_menu(call, uid, "create", 0, key)
    b = db.hosted(bid)
    if not b or b["user_id"] != uid or not can_renew(b):
        return await call.answer("Этот бот уже куплен навсегда 🙂", show_alert=True)
    await call.answer()
    await pay_menu(call, uid, "buy", bid, key)


@router.callback_query(F.data == "c:tariffs")
async def cb_tariffs(call: CallbackQuery):
    """Кнопка «💎 Тарифы» в меню: подробное описание всех тарифов."""
    uid = call.from_user.id
    renew = [b for b in db.user_hosted(uid) if can_renew(b)]
    rows = [[B("renew", f"c:tar:b:{b['id']}", text=f"{bt('renew')} · @{b['username']}")] for b in renew[:3]]
    url = app_url()
    rows.append([B("app", web_app=url + "#create") if url else B("create", "c:new")])
    rows.append([B("menu", "c:menu")])
    await out(call, tariffs_text(), kb(rows))
    await call.answer()


def pay_kb(uid, kind, bid=0, item="pro"):
    k = {"create": "c", "buy": "b", "addon": "a"}[kind]
    tag = f"{k}:{bid}:{item}"
    if kind == "addon":
        amount, promo = core.addon_price(item), None
    else:
        amount, promo = core.final_price(uid, item)
    stars = core.stars_for(amount)
    rows = []
    if kind != "addon" and core.tariff_price(item) > 0 and amount <= 0:  # промокод на 100% — без оплаты
        rows.append([B("pay_free", f"c:pm:balance:{tag}")])
    else:
        if core.pay_on("stars"):
            rows.append([B("pay_stars", f"c:pm:stars:{tag}", text=f"{bt('pay_stars')} · {stars} ⭐")])
        crypto_row = [B(f"pay_{m}", f"c:pm:{m}:{tag}") for m in ("cryptobot", "xrocket") if core.pay_on(m)]
        if crypto_row:
            rows.append(crypto_row)
        if core.pay_on("sbp"):
            rows.append([B("pay_sbp", f"c:pm:sbp:{tag}", text=f"{bt('pay_sbp')} · {money(amount)}")])
        u = core.user(uid)
        if u and amount > 0 and (u["balance"] or 0) >= amount:
            rows.append([B("pay_balance", f"c:pm:balance:{tag}", text=f"{bt('pay_balance')} · {money(u['balance'])}")])
    if kind != "addon" and core.flag_on("promo_btn") and not promo:
        rows.append([B("promo", f"c:promo:{'c' if kind == 'create' else 'b' + str(bid)}.{item}")])
    rows.append([B("back", {"create": "c:tar:c:0", "buy": f"c:tar:b:{bid}", "addon": "c:addons"}[kind])])
    return rows


def promo_line(uid, item="pro"):
    amount, p = core.final_price(uid, item)
    if not p:
        return ""
    return tx("promo_line", code=html.escape(p["code"]), label=core.promo_label(p),
              old=money(core.tariff_price(item)), price=money(amount))


async def pay_menu(target, uid, kind, bid=0, item="pro"):
    """Способы оплаты: новый магазин (create), тариф для своего бота (buy) или дополнение (addon). item — тариф / ключ."""
    rows = pay_kb(uid, kind, bid, item)
    pay_rows = [r for r in rows if any((getattr(b, "callback_data", "") or "").startswith("c:pm:") for b in r if b)]
    if not pay_rows:
        return await out(target, tx("pay_none"), kb([[B("support", "c:sup")], rows[-1]]))
    if kind == "addon":
        amount = core.addon_price(item)
        text = tx("addon_" + item, price=money(amount)) + "\n\nВыбери способ оплаты 👇"
        return await out(target, text, kb(rows))
    amount, _ = core.final_price(uid, item)
    common = dict(price=money(amount), stars=core.stars_for(amount), tariff=core.tariff_name(item),
                  period=core.tariff_period(item))
    if kind == "create":
        text = tx("pay_choose", trial="", **common)
    else:
        b = db.hosted(bid)
        text = tx("pay_choose_buy", username=html.escape((b["username"] if b else "") or "?"), **common)
    pl = promo_line(uid, item)
    if pl:
        text += "\n\n" + pl
    await out(target, text, kb(rows))


def item_title(kind, item, b=None):
    """Название покупки для счёта и уведомлений."""
    name = core.ADDONS.get(item, ("Дополнение",))[0] if kind == "addon" else core.tariff_name(item)
    who = f" — @{b['username']}" if b and b["username"] else ""
    return core.plain(name) + who


@router.callback_query(F.data.startswith("c:pm:"))
async def cb_pay_method(call: CallbackQuery, bot: Bot):
    """c:pm:<способ>:<c|b|a>:<id магазина>:<тариф или дополнение>"""
    uid = call.from_user.id
    parts = call.data.split(":")
    try:
        method, k, bid = parts[2], parts[3], int(parts[4])
    except (IndexError, ValueError):
        return await call.answer()
    item = parts[5] if len(parts) > 5 else "pro"
    kind = {"c": "create", "b": "buy", "a": "addon"}.get(k)
    if not kind:
        return await call.answer()
    if method != "balance" and not core.pay_on(method):
        return await call.answer("Этот способ оплаты сейчас выключен", show_alert=True)
    data, b = None, None
    if kind == "create":
        d, _ = core.draft(uid)
        if core.next_step(d) != "confirm":
            await call.answer()
            return await advance(call, uid, d)
        if db.hosted_by_tg(d["tg_id"]):
            return await call.answer(core.plain(tx("token_taken")), show_alert=True)
        data = d
    elif kind == "buy":
        b = db.hosted(bid)
        if not b or b["user_id"] != uid or not can_renew(b):
            return await call.answer("Этот бот уже куплен навсегда 🙂", show_alert=True)
    else:
        b = db.hosted(bid) if bid else None
        if bid and (not b or b["user_id"] != uid):
            return await call.answer()
        if not core.addon_on(item):
            return await call.answer("Это дополнение сейчас недоступно", show_alert=True)
    if kind != "addon" and not core.tariff_on(item):
        return await call.answer("Этот тариф сейчас недоступен", show_alert=True)
    if kind == "addon":
        price, promo = core.addon_price(item), None
    else:
        price, promo = core.final_price(uid, item)
        if price <= 0 and core.tariff_price(item) > 0:
            method = "balance"  # промокод на 100%: оплачивать нечего
    stars = core.stars_for(price)
    pid = core.create_payment(uid, kind, method, price, stars, bid or None, data)
    core.set_payment(pid, tariff=item, promo=promo["code"] if promo else None)

    if method == "balance":
        if price > 0 and not core.take_balance(uid, price):
            core.set_payment(pid, status="canceled")
            return await call.answer("На балансе не хватает", show_alert=True)
        await call.answer()
        return await on_paid(pid, "balance")
    await call.answer()

    if method == "stars":
        from aiogram.types import LabeledPrice
        title = core.plain(tx("stars_title"))[:32] or "Магазин"
        desc = (item_title(kind, item, b) + " · " + core.plain(tx("stars_desc")))[:255]
        try:
            await bot.send_invoice(uid, title=title, description=desc, payload=f"ctor:{pid}", currency="XTR",
                                   prices=[LabeledPrice(label=item_title(kind, item)[:32] or title, amount=stars)])
        except Exception as e:
            log.warning("конструктор: счёт звёздами не выставлен: %s", e)
            core.set_payment(pid, status="canceled")
            return await out(call, "⚠️ Не получилось выставить счёт звёздами — выбери другой способ.",
                             kb(pay_kb(uid, kind, bid, item)))
        return

    if method in ("cryptobot", "xrocket"):
        import crypto
        try:
            inv, extra = await crypto.create("ctor", pid, uid, method, price, item_title(kind, item, b))
        except Exception as e:
            log.warning("конструктор: счёт %s не выставлен: %s", method, e)
            core.set_payment(pid, status="canceled")
            return await out(call, f"⚠️ {core.PAY_NAMES[method]} сейчас не отвечает — выбери другой способ.",
                             kb(pay_kb(uid, kind, bid, item)))
        core.set_payment(pid, inv_id=inv["id"])
        return await out(call, tx("pay_crypto", service=core.PAY_NAMES[method], price=money(price), extra=extra), kb([
            [B("pay_open", url=inv["url"])],
            [B("pay_check", f"c:pchk:{pid}")],
            [B("cancel", f"c:pcan:{pid}")],
        ]))

    # СБП
    await out(call, tx("pay_sbp", id=pid, price=money(price), details=core.sbp()), kb([
        [B("paid", f"c:psent:{pid}")],
        [B("cancel", f"c:pcan:{pid}")],
    ]))


@router.pre_checkout_query()
async def on_pre_checkout(q, bot: Bot):
    """Telegram спрашивает перед списанием звёзд: заявка ещё ждёт оплаты?"""
    ok = False
    if (q.invoice_payload or "").startswith("ctor:"):
        p = core.payment(int(q.invoice_payload[5:] or 0))
        ok = bool(p and p["status"] == "wait" and p["method"] == "stars" and p["user_id"] == q.from_user.id
                  and q.currency == "XTR" and q.total_amount == p["stars"])
    await q.answer(ok=ok, error_message=None if ok else "Счёт устарел — выбери оплату заново.")


@router.message(F.successful_payment)
async def on_stars_paid(m: Message):
    sp = m.successful_payment
    if not (sp.invoice_payload or "").startswith("ctor:"):
        return
    await on_paid(int(sp.invoice_payload[5:]), f"stars:{sp.telegram_payment_charge_id}")


@router.callback_query(F.data.startswith("c:pchk:"))
async def cb_pay_check(call: CallbackQuery, bot: Bot):
    import crypto
    p = core.payment(int(call.data[7:]))
    if not p or p["user_id"] != call.from_user.id:
        return await call.answer()
    if p["status"] == "paid":
        return await call.answer("Уже оплачено ✅")
    res = await crypto.check(bot, p["inv_id"], call.from_user.id) if p["inv_id"] else "not_found"
    if res == "paid":
        return await call.answer("Оплата получена ✅")
    if res == "expired":
        return await call.answer(core.plain(tx("pay_crypto_expired")), show_alert=True)
    await call.answer(core.plain(tx("pay_crypto_wait")), show_alert=True)


@router.callback_query(F.data.startswith("c:pcan:"))
async def cb_pay_cancel(call: CallbackQuery):
    uid = call.from_user.id
    p = core.payment(int(call.data[7:]))
    if p and p["user_id"] == uid and p["status"] == "wait":
        core.set_payment(p["id"], status="canceled")
    d, step = core.draft(uid)
    if step == "payreceipt":
        d.pop("_pid", None)
        core.save_draft(uid, d, "confirm" if core.next_step(d) == "confirm" else None)
    await call.answer(core.plain(tx("pay_canceled")))
    if p and p["kind"] in ("buy", "addon"):
        return await bots_view(call, uid)
    await advance(call, uid)


@router.callback_query(F.data.startswith("c:psent:"))
async def cb_pay_sent(call: CallbackQuery):
    """СБП: «Я оплатил» -> ждём чек."""
    uid = call.from_user.id
    p = core.payment(int(call.data[8:]))
    if not p or p["user_id"] != uid or p["status"] != "wait" or p["method"] != "sbp":
        return await call.answer("Заявка уже обработана", show_alert=True)
    d, _ = core.draft(uid)
    d["_pid"] = p["id"]
    core.save_draft(uid, d, "payreceipt")
    await out(call, tx("pay_receipt"), kb([[B("cancel", f"c:pcan:{p['id']}")]]))
    await call.answer()


async def on_pay_receipt(m: Message, d, bot: Bot):
    uid = m.from_user.id
    if not (m.photo or m.document):
        return await m.answer(tx("topup_need_receipt"))
    p = core.payment(int(d.get("_pid") or 0))
    d.pop("_pid", None)
    core.save_draft(uid, d, "confirm" if core.next_step(d) == "confirm" else None)
    if not p or p["user_id"] != uid or p["status"] != "wait":
        return await m.answer("Заявка не найдена — выбери оплату заново.", reply_markup=kb([[B("menu", "c:menu")]]))
    file_id = m.photo[-1].file_id if m.photo else m.document.file_id
    core.set_payment(p["id"], status="pending", receipt=file_id)
    u = core.user(uid)
    item = p["tariff"] or "pro"
    b = db.hosted(p["bot_id"]) if p["bot_id"] else None
    if p["kind"] == "create":
        data = json.loads(p["data"] or "{}")
        what = (f"🏗 Новый магазин @{html.escape(data.get('username') or '?')} · «{html.escape(data.get('title') or '')}»"
                f"\n💳 Тариф: {core.tariff_name(item)}")
    elif p["kind"] == "addon":
        what = f"🛍 {html.escape(item_title('addon', item, b))}"
    else:
        what = f"💳 {core.tariff_name(item)} для @{html.escape((b['username'] if b else '') or '?')}"
    caption = (f"💳 <b>Оплата по СБП — заявка #{p['id']}</b>\n\n{what}\n👤 {core.user_link(u)}\n"
               f"💰 Сумма: <b>{money(p['amount'])}</b>")
    markup = kb([[raw_btn("✅ Принять", f"ca:pok:{p['id']}", style="success"),
                  raw_btn("❌ Отклонить", f"ca:pno:{p['id']}", style="danger")]])
    for aid in sorted(config.ADMINS):
        try:
            if m.photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception as e:
            log.warning("конструктор: чек админу %s не отправлен: %s", aid, e)
    await m.answer(tx("pay_receipt_sent" if p["kind"] == "create" else "pay_receipt_sent_buy"),
                   reply_markup=kb([[B("menu", "c:menu")]]))


async def after_paid(p):
    """Общее для любой оплаты: промокод израсходован, пригласивший получил свой процент."""
    if "promo" in p.keys() and p["promo"]:
        core.use_promo(p["promo"], p["user_id"])
    try:
        res = core.ref_reward(p)
    except Exception:
        log.exception("конструктор: реферальное начисление не прошло (оплата #%s)", p["id"])
        res = None
    if res:
        ref_id, reward = res
        u, r = core.user(p["user_id"]), core.user(ref_id)
        await send(ref_id, tx("ref_reward", name=html.escape((u["first_name"] if u else None) or "друг"),
                              amount=money(reward), balance=money(r["balance"] if r else 0)))
    try:
        pres = core.partner_reward(p)
    except Exception:
        log.exception("конструктор: партнёрское начисление не прошло (оплата #%s)", p["id"])
        pres = None
    if pres:
        partner, reward = pres
        _, _, due = core.partner_stats(partner)
        await send(partner["user_id"], tx("partner_sale", amount=money(reward), due=money(due)))


async def apply_plan(b, tariff):
    """Тариф оплачен для существующего бота: срок продлевается (от конца текущего) или бот становится бессрочным."""
    from handlers import builder
    days = core.tariff_days(tariff)
    if days:
        base = b["trial_until"] if b["trial_until"] and b["trial_until"] > db.now() else None
        db.set_hosted(b["id"], trial_until=builder.add_days(days, base=base), trial_warned=0, plan=tariff,
                      pay_status=None)
        if b["status"] == "expired" and b["token"]:
            db.set_hosted(b["id"], status="running")
            return await hosting.launch(b["id"])
        return b["status"] == "running"
    db.set_hosted(b["id"], plan=tariff)
    return await builder.make_permanent(_bot, db.hosted(b["id"]))


async def post_purchase(uid, tariff):
    """После покупки тарифа: приглашение в чат владельцев и (для VIP) исходный код."""
    chat = core.get("owners_chat")
    url = fix_url(chat or "")
    if url:
        await out(uid, tx("owners_chat"), kb([[B("owners_chat", url=url)]]))
    if tariff == "vip":
        await send_vip(uid)


async def send_vip(uid):
    """VIP: архив с исходным кодом (загружает админ в /admin → 💎 Тарифы → 👑 VIP) + инструкция."""
    cur = core.curator() or "—"
    fid = core.get("vip_file")
    if fid and _bot:
        try:
            await _bot.send_document(uid, fid)
            await send(uid, tx("vip_delivery", curator=html.escape(cur)))
            return True
        except Exception as e:
            log.warning("конструктор: архив VIP не отправлен %s: %s", uid, e)
    await send(uid, tx("vip_wait", curator=html.escape(cur)))
    await to_admins(f"👑 <b>Куплен VIP</b> — архив с исходным кодом не отправлен автоматически"
                    f"{'' if fid else ' (не загружен в /admin → 💎 Тарифы)'}.\n👤 {core.user_link(core.user(uid))}\n"
                    "Пришлите ему архив вручную.")
    return False


async def on_paid(pid, receipt, auto=False):
    """Оплата подтверждена (звёзды / крипта / СБП после «Принять» / баланс): создаём магазин, включаем тариф
    или выполняем дополнение."""
    if not core.mark_paid(pid, receipt):
        return False
    p = core.payment(pid)
    uid = p["user_id"]
    item = p["tariff"] or "pro"
    method = core.PAY_NAMES.get(p["method"], p["method"]) + (" (автопродление)" if auto else "")
    stars_note = f" ({p['stars']} ⭐)" if p["method"] == "stars" else ""
    await after_paid(p)
    if p["kind"] == "addon":
        b = db.hosted(p["bot_id"]) if p["bot_id"] else None
        name = core.ADDONS.get(item, ("Дополнение",))[0]
        await out(uid, tx("addon_ok", name=name, curator=html.escape(core.curator() or "—")),
                  kb([[B("bots", "c:bots"), B("menu", "c:menu")]]))
        await to_admins(f"🛍 <b>Куплено дополнение</b> — {method}\n\n{name}"
                        + (f"\n🤖 @{html.escape(b['username'] or '?')} · #{b['id']}" if b else "")
                        + f"\n👤 {core.user_link(core.user(uid))}\n💰 {money(p['amount'])}{stars_note}\n\n"
                          "Свяжитесь с покупателем и выполните заказ.")
        return True
    if p["kind"] == "buy":
        b = db.hosted(p["bot_id"])
        if not b:
            return True
        db.set_hosted(b["id"], price=(b["price"] or 0) + (p["amount"] or 0))
        running_now = await apply_plan(b, item)
        b = db.hosted(b["id"])
        name = html.escape(b["username"] or "?")
        u = core.user(uid)
        text = (tx("autobought", username=name, price=money(p["amount"]), plan=html.escape(core.plan_line(b)),
                   balance=money(u["balance"] if u else 0))
                if auto else tx("bought", username=name, plan=html.escape(core.plan_line(b))))
        await out(uid, text, kb([
            [raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}", style="success")],
            [B("bots", "c:bots"), B("menu", "c:menu")]]))
        await to_admins(f"💳 <b>Тариф {core.tariff_name(item)}</b> — {method}\n\n🤖 @{name} · #{b['id']} → "
                        f"{html.escape(core.plan_line(b))}\n👤 {core.user_link(u)}\n💰 {money(p['amount'])}{stars_note}"
                        + (f"\n🎟 Промокод {html.escape(p['promo'])}" if p["promo"] else "")
                        + ("" if running_now else "\n⚠️ Бот не запустился — смотрите лог."))
        if not auto:
            await post_purchase(uid, item)
        elif item == "vip":
            await send_vip(uid)
        return True
    d = json.loads(p["data"] or "{}")
    await out(uid, tx("pay_ok"))
    await do_create(uid, d, trial=False, price=p["amount"], method=method,
                    stars=p["stars"] if p["method"] == "stars" else 0, tariff=item)
    await post_purchase(uid, item)
    return True


async def do_create(uid, d, trial, price=0, method="", stars=0, tariff="pro"):
    """Создаёт магазин клиента из данных мастера и запускает его."""
    from handlers import builder
    u = core.user(uid)
    if not d.get("token") or db.hosted_by_tg(d.get("tg_id") or 0):
        await out(uid, "⚠️ Этот бот уже подключён к другому магазину. Напиши в поддержку — разберёмся"
                       + (" (оплата сохранена)." if not trial else "."), kb([[B("support", "c:sup")]]))
        return await to_admins(f"⚠️ Не удалось создать магазин после {'пробного' if trial else 'оплаты ' + method}: "
                               f"бот @{html.escape(d.get('username') or '?')} уже занят.\n👤 {core.user_link(u)}"
                               + ("" if trial else f"\n💰 {money(price)} — нужно вернуть или помочь вручную"))
    bid = db.create_hosted(uid, 0 if trial else price)
    fields = dict(status="running", source="ctor", cfg=json.dumps(_public_cfg(d), ensure_ascii=False),
                  no_app=1 if core.no_app(d) else 0,
                  token=d["token"], tg_id=d["tg_id"], username=d["username"], shop_name=d.get("title") or d["username"],
                  started=db.now())
    if trial:
        extra = core.promo_days(uid)  # промокод «+N дней пробного»
        fields.update(trial=1, plan="trial", trial_until=builder.add_days(core.trial_days() + extra))
        if extra:
            core.use_promo(core.active_promo(uid)["code"], uid)
    else:
        fields["plan"] = tariff
        if core.tariff_days(tariff):  # Start / Medium — со сроком
            fields["trial_until"] = builder.add_days(core.tariff_days(tariff))
    db.set_hosted(bid, **fields)
    try:
        await seed_shop(bid, d, _bot)
    except Exception:
        log.exception("конструктор: не записал настройки магазина #%s", bid)
    ok = await hosting.launch(bid)
    cur, _ = core.draft(uid)
    if not cur or cur.get("tg_id") == d.get("tg_id"):
        core.drop_draft(uid)
    b = db.hosted(bid)
    name = html.escape(d["username"])
    if ok:
        note = tx("created_trial", until=builder.fmt_until(b["trial_until"]),
                  plan=html.escape(core.plan_line(b))) if b["trial_until"] else ""
        rows = [[raw_btn(f"🤖 Открыть @{d['username']}", url=f"https://t.me/{d['username']}", style="success")]]
        if any(core.addon_on(a) for a in core.ADDONS):
            rows.append([B("addons", "c:addons")])
        rows.append([B("bots", "c:bots"), B("menu", "c:menu")])
        await out(uid, tx("created", username=name, trial=note), kb(rows))
        await send_curator(uid, d["username"])
    else:
        await out(uid, tx("create_fail", username=name), kb([[B("support", "c:sup")], [B("menu", "c:menu")]]))
    await to_admins(f"🏗 <b>Магазин {'создан' if ok else 'создан, но НЕ запустился'}</b> через конструктор\n\n"
                    f"🆔 #{bid} · 🤖 @{name}\n👤 {core.user_link(u)}\n📋 {html.escape(core.plan_line(b))}"
                    + ("" if trial else f"\n💰 Оплачено: {money(price)}" + (f" ({stars} ⭐)" if stars else "")
                       + f" — {method}"))


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
        seed_template(con, d.get("template"))
        con.commit()
    finally:
        con.close()


def seed_template(con, key):
    """Категории и примеры товаров из выбранного шаблона — только в пустую базу магазина."""
    cats = core.TEMPLATES.get(key or "empty", ("", "", []))[2]
    if not cats:
        return 0
    con.executescript(db.SCHEMA)  # те же таблицы, что создаст сам магазин при запуске
    if con.execute("SELECT COUNT(*) FROM categories").fetchone()[0]:
        return 0
    n = 0
    for pos, (cat, items) in enumerate(cats, 1):
        cid = con.execute("INSERT INTO categories(name, position) VALUES (?, ?)", (cat, pos)).lastrowid
        for name, desc, price, kind in items:
            con.execute("INSERT INTO products(category_id, name, description, price, kind, active, created) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (cid, name, desc, price, kind, 0 if kind == "manual" else 1,
                                                         db.now()))
            n += 1
    return n


# ======================= мои боты =======================
STATUS_ICON = {"running": "✅", "stopped": "⏸", "failed": "⚠️", "expired": "⌛", "wait_token": "🔑", "pending": "🔎",
               "rejected": "❌"}
STATUS_RU = {"running": "работает", "stopped": "остановлен", "failed": "не работает", "expired": "срок закончился",
             "wait_token": "ждёт токен", "pending": "оплата на проверке", "rejected": "отклонён"}


@router.callback_query(F.data == "c:bots")
async def cb_bots(call: CallbackQuery):
    await bots_view(call, call.from_user.id)
    await call.answer()


async def bots_view(target, uid):
    bots =[b for b in db.user_hosted(uid) if b["tg_id"]]
    if not bots:
        url = app_url()
        return await out(target, tx("no_bots"), kb([
            [B("app", web_app=url) if url else B("create", "c:new")], [B("menu", "c:menu")]]))
    text = tx("bots_head") + "\n"
    rows = []
    mn = money(core.min_tariff_price())
    for b in bots[:15]:
        name = f"@{html.escape(b['username'])}" if b["username"] else f"#{b['id']}"
        badge = " 🏅" if b["verified"] else ""
        text += f"\n{STATUS_ICON.get(b['status'], '•')} <b>{name}</b>{badge} — {STATUS_RU.get(b['status'], b['status'])}"
        text += f"\n     {html.escape(core.plan_line(b))}"
        if b["status"] == "running" and b["username"]:
            rows.append([raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}")])
        if b["status"] == "failed":
            rows.append([B("new_token", f"c:rt:{b['id']}", text=f"{bt('new_token')} · @{b['username']}")])
        if can_renew(b):
            rows.append([B("renew", f"c:tar:b:{b['id']}", text=f"{bt('renew')} · @{b['username']} · от {mn}")])
    u = core.user(uid)
    if u and (u["balance"] or 0) > 0:
        text += f"\n\n💰 Баланс: <b>{money(u['balance'])}</b>"
    if core.flag_on("autobuy") and any(can_renew(b) for b in bots):
        on = bool(u and u["autobuy"])
        text += tx("autobuy_info", state="вкл" if on else "выкл")
        rows.append([B("autobuy", "c:ab", text=f"{bt('autobuy')}: {'✅ вкл' if on else '⏸ выкл'}"),
                     B("topup", "c:top")])
    extra = []
    if any(core.addon_on(a) for a in core.ADDONS):
        extra.append(B("addons", "c:addons"))
    chat = fix_url(core.get("owners_chat") or "")
    if chat and has_paid(uid):
        extra.append(B("owners_chat", url=chat))
    if extra:
        rows.append(extra)
    rows.append([B("menu", "c:menu")])
    await out(target, text, kb(rows))


def has_paid(uid):
    """Покупал хоть один тариф — ему положен чат владельцев."""
    return bool(db.val("SELECT COUNT(*) FROM ctor_payments WHERE user_id=? AND status='paid' AND kind!='addon'",
                       (uid,)))


@router.callback_query(F.data == "c:ab")
async def cb_autobuy(call: CallbackQuery):
    uid = call.from_user.id
    u = core.user(uid)
    on = 0 if u and u["autobuy"] else 1
    db.x("UPDATE ctor_users SET autobuy=? WHERE id=?", (on, uid))
    await call.answer("🔁 Автопродление включено" if on else "Автопродление выключено")
    await bots_view(call, uid)
    if on:
        await autobuy_user(uid)


@router.callback_query(F.data.startswith("c:buy:"))
async def cb_buy(call: CallbackQuery):
    """Старые кнопки «Купить навсегда» (из прошлых сообщений) — теперь выбор тарифа."""
    uid = call.from_user.id
    _, step = core.draft(uid)
    if step == "promo":
        core.set_step(uid, None)
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or b["user_id"] != uid or not can_renew(b):
        return await call.answer("Этот бот уже куплен навсегда 🙂", show_alert=True)
    await call.answer()
    await tariff_view(call, uid, "b", bid)


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
    return kb([[B("renew", f"c:tar:b:{b['id']}", text=f"{bt('renew')} · от {money(core.min_tariff_price())}")],
               [B("topup", "c:top"), B("bots", "c:bots")]])


def autobuy_tariff(b):
    """Каким тарифом продлевать автоматически: тот же Start / Medium, пробный — Start (или самый дешёвый)."""
    p = core.bot_plan(b)
    if p in ("start", "medium") and core.tariff_on(p):
        return p
    timed = [k for k in core.tariffs_on() if core.tariff_days(k)]
    if "start" in timed:
        return "start"
    return min(timed or core.tariffs_on() or ["pro"], key=core.tariff_price)


def autobuy_line(b):
    """Подсказка под напоминанием: продлю сам / пополни на N — продлю сам."""
    u = core.user(b["user_id"])
    if not core.flag_on("autobuy") or not u or not u["autobuy"] or not b["token"]:
        return ""
    tariff = autobuy_tariff(b)
    amount, _ = core.final_price(b["user_id"], tariff)
    need = round(amount - (u["balance"] or 0), 2)
    label = f"{core.tariff_name(tariff)}, {money(amount)}"
    if need <= 0:  # выключенного бота сам не продлеваю — пусть нажмёт «Продлить»
        return tx("autobuy_hint", tariff=label) if b["status"] == "running" else ""
    return tx("autobuy_need", need=money(need), tariff=label)


async def trial_notice(b, kind):
    """Срок магазина из конструктора (пробный или тариф): kind = soon (за сутки) / over (выключен)."""
    from handlers import builder
    name = html.escape(b["username"] or "?")
    price = money(core.min_tariff_price())
    trial = core.bot_plan(b) == "trial"
    what = core.plan_what(b)
    if kind == "soon":
        key = "trial_soon" if trial else "sub_soon"
        return await send(b["user_id"], tx(key, username=name, until=builder.fmt_until(b["trial_until"]), price=price,
                                           what=what) + autobuy_line(b), _buy_kb(b))
    key = "trial_over" if trial else "sub_over"
    return await send(b["user_id"], tx(key, username=name, price=price, what=what) + autobuy_line(b),
                      _buy_kb(b) if b["token"] else None)


# ======================= автопродление с баланса =======================
async def try_autobuy(bid):
    """Пробный / срочный (или уже выключенный) бот продлевается с баланса владельца, если денег хватает."""
    async with _ab_lock:
        b = db.hosted(bid)
        if not b or not b["trial_until"] or not b["token"] or b["status"] not in ("running", "expired"):
            return False
        u = core.user(b["user_id"])
        if not core.flag_on("autobuy") or not u or not u["autobuy"] or u["banned"]:
            return False
        if db.val("SELECT COUNT(*) FROM ctor_payments WHERE bot_id=? AND kind='buy' AND status='pending'", (bid,)):
            return False  # чек СБП за этого бота уже на проверке — не списываем второй раз
        tariff = autobuy_tariff(b)
        amount, promo = core.final_price(u["id"], tariff)
        if (u["balance"] or 0) < amount:
            return False
        if amount > 0 and not core.take_balance(u["id"], amount):
            return False
        pid = core.create_payment(u["id"], "buy", "balance", amount, core.stars_for(amount), bid, None)
        core.set_payment(pid, tariff=tariff, promo=promo["code"] if promo else None)
        return await on_paid(pid, "balance:auto", auto=True)


async def autobuy_user(uid):
    """После пополнения баланса: продлить выключенных ботов и тех, кому осталось меньше 3 дней (если хватает)."""
    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    done = 0
    for b in db.user_hosted(uid):
        if not (b["trial_until"] and b["token"]):
            continue
        if b["status"] == "expired" or (b["status"] == "running" and b["trial_until"] <= soon):
            try:
                done += bool(await try_autobuy(b["id"]))
            except Exception:
                log.exception("конструктор: автопродление бота #%s не удалось", b["id"])
    return done


# ======================= напоминания: сколько дней осталось =======================
REMIND_AFTER = (7, 3, 1)  # через сколько дней после выключения напомнить


def remind_days():
    """За сколько дней до конца напоминать (/admin → 🔔 Напоминания). По умолчанию 7, 3, 2, 1."""
    raw = core.get("remind_days") or "7,3,2,1"
    out = sorted({int(x) for x in re.findall(r"\d+", raw) if 0 < int(x) <= 60}, reverse=True)
    return out or [7, 3, 2, 1]


def _ts(s):
    from datetime import datetime
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def remind_key(b, now):
    """Какое напоминание положено боту сейчас (None — никакое): dN (осталось N дней), 3h, aN (выключен N дней)."""
    from datetime import timedelta
    until = _ts(b["trial_until"])
    if not until:
        return None
    if b["status"] == "running":
        left = until - now
        if left <= timedelta(0):
            return None
        if left <= timedelta(hours=3):
            return "3h"
        started = _ts(b["started"]) or _ts(b["created"]) or now
        for n in sorted(remind_days()):
            # «осталось N дней» — в последние сутки перед отметкой N, и только если срок длиннее N дней с запасом
            if timedelta(days=n - 1) < left <= timedelta(days=n) and until - started > timedelta(days=n, hours=12):
                return f"d{n}"
        return None
    if b["status"] == "expired":
        ago = now - until
        for n in REMIND_AFTER:
            if timedelta(days=n) <= ago < timedelta(days=n + 1):
                return f"a{n}"
    return None


async def remind_tick():
    from datetime import datetime, timedelta
    from handlers import builder
    now = datetime.now()
    rows = db.q("SELECT * FROM hosted_bots WHERE source='ctor' AND trial_until IS NOT NULL AND token IS NOT NULL "
                "AND status IN ('running','expired')")
    for b in rows:
        until = _ts(b["trial_until"])
        # уже выключенных ботов сам не продлеваю — только после пополнения баланса (autobuy_user)
        if until and b["status"] == "running" and until - now <= timedelta(hours=1):
            if await try_autobuy(b["id"]):
                continue
        if not core.flag_on("remind"):
            continue
        key = remind_key(b, now)
        if not key:
            continue
        if key == "d1" and b["trial_warned"]:  # «за сутки» уже написал builder.trial_loop
            continue
        tag = f"{key}@{b['trial_until']}"  # продлили — напоминания пойдут заново
        try:
            sent = json.loads(b["reminded"] or "[]")
        except ValueError:
            sent = []
        if tag in sent:
            continue
        sent = (sent + [tag])[-30:]
        fields = {"reminded": json.dumps(sent)}
        if key == "d1":
            fields["trial_warned"] = 1  # чтобы builder не написал второй раз
        db.set_hosted(b["id"], **fields)
        name = html.escape(b["username"] or "?")
        price = money(core.min_tariff_price())
        what = core.plan_what(b)
        if key == "3h":
            text = tx("remind_3h", username=name, price=price, what=what)
        elif key.startswith("d"):
            n = int(key[1:])
            text = tx("remind_days", username=name, price=price, what=what, left=f"{n} {core.days_word(n)}",
                      until=builder.fmt_until(b["trial_until"]))
        else:
            n = int(key[1:])
            text = tx("remind_after", username=name, price=price, days=f"{n} {core.days_word(n)}")
        await send(b["user_id"], text + autobuy_line(b), _buy_kb(b))


async def remind_loop():
    """Раз в минуту: автопродление, напоминания владельцам, пуш «открой приложение», «Проверенный магазин»."""
    from ctor import growth
    n = 0
    while True:
        try:
            await remind_tick()
            await growth.push_tick()
            if n % 30 == 0:
                await growth.verified_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("конструктор: фоновые задачи не прошли")
        n += 1
        await asyncio.sleep(60)


async def failed_notice(b):
    return await send(b["user_id"], tx("failed", username=html.escape(b["username"] or "?")),
                      kb([[B("new_token", f"c:rt:{b['id']}")], [B("bots", "c:bots")]]))
