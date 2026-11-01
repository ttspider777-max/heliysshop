"""«🤖 Создать своего бота»: покупатель оплачивает создание, админ одобряет чек, покупатель присылает токен
от @BotFather — и копия магазина сама запускается на этом же сервере (см. hosting.py).

Путь покупателя: 🤖 Создать своего бота → ✅ Я прочитал → реквизиты СБП → ✅ Я оплатил → чек
→ админу приходит чек с кнопками ✅ Одобрить / ❌ Отклонить → «пришлите токен» → токен → бот запущен.
Админ-панель → 🤖 Боты клиентов: список, остановка, запуск, лог, удаление.
"""
import asyncio
import html
import io
import logging
import os
import re
import sqlite3
import tempfile
import zipfile

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import admins
import config
import db
import hosting
from handlers.admin import B, ask, back, done, inp, mark_admin_msg, router as admin_router
from services import broadcast, safe_send, to_admins, user_link
from texts import bot_status, bt, fdate, money, t
from ui import btn, fix_url, kb, menu_row, raw_btn, render

router = Router()
# у бота клиента этого раздела нет
router.message.filter(lambda e: not config.CHILD)
router.callback_query.filter(lambda e: not config.CHILD)

_busy = set()  # покупатели, чей токен сейчас проверяется (защита от двойного запуска)


class BuildSt(StatesGroup):
    receipt = State()


def bot_price():
    try:
        return float(db.get_setting("bot_price", config.BOT_PRICE))
    except ValueError:
        return float(config.BOT_PRICE)


def bot_name(b):
    return "@" + html.escape(b["username"]) if b["username"] else f"#{b['id']}"


# ---------- пробный период ----------
def trial_days():
    """Сколько дней бесплатно (⚙️ Настройки → 🎁 Пробный период; 0 — пробного нет)."""
    try:
        return max(int(float(db.get_setting("trial_days", 3))), 0)
    except ValueError:
        return 3


def fmt_until(ts):
    return f"{ts[8:10]}.{ts[5:7]} {ts[11:16]}" if ts and len(ts) >= 16 else "—"


def add_days(days, base=None):
    from datetime import datetime, timedelta
    start = datetime.strptime(base, "%Y-%m-%d %H:%M:%S") if base else datetime.now()
    return (max(start, datetime.now()) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def buy_kb(bid, lang):
    return kb([[btn("mb_buy", lang, f"mb:buy:{bid}")], [btn("main_menu", lang, "menu")]])


# ======================= покупатель =======================
async def info_view(target, lang, uid):
    text = t("mb_info", lang, price=money(bot_price()))
    rows = [[btn("mb_read", lang, "mb:read")]]
    days = trial_days()
    if days and not db.trial_used(uid):
        text += t("mb_trial_offer", lang, days=days)
        rows.insert(0, [btn("mb_trial", lang, "mb:trial")])
    bots = db.user_hosted(uid)
    if bots:
        text += t("mb_bots_head", lang)
        for b in bots[:10]:
            text += t("mb_bot_line", lang, name=bot_name(b), status=bot_status(b["status"], lang))
            if b["trial_until"] and b["status"] != "expired":
                text += t("mb_trial_line", lang, until=fmt_until(b["trial_until"]))
            if b["status"] == "running" and b["username"]:
                rows.append([raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}")])
            elif b["status"] == "failed":
                rows.append([raw_btn(f"{bt('mb_token', lang)} · @{b['username']}", f"mb:tok:{b['id']}")])
            if b["trial_until"] and b["token"] and b["pay_status"] != "pending":
                rows.append([raw_btn(f"{bt('mb_buy', lang)} · {bot_name(b)} · {money(bot_price())}",
                                     f"mb:buy:{b['id']}", style="success")])
        if any(b["status"] == "wait_token" for b in bots):
            text += t("mb_send_token", lang)
    rows.append(menu_row(lang))
    await render(target, text, kb(rows))


@router.callback_query(F.data == "mb:trial")
async def cb_trial(call: CallbackQuery, state: FSMContext, lang: str):
    uid = call.from_user.id
    await state.set_state(None)
    days = trial_days()
    if not days or db.trial_used(uid):
        return await call.answer(t("mb_trial_used", lang), show_alert=True)
    if db.hosted_wait_token(uid):  # уже ждём токен (оплаченный бот) — сначала его
        await call.answer()
        return await info_view(call, lang, uid)
    bid = db.create_hosted(uid, 0)
    db.set_hosted(bid, status="wait_token", trial=1)
    await render(call, t("mb_trial_start", lang, days=days), kb([[btn("back", lang, "mkbot")]]))
    await call.answer()


@router.callback_query(F.data.startswith("mb:buy:"))
async def cb_buy(call: CallbackQuery, state: FSMContext, lang: str):
    """Покупка пробного бота: те же реквизиты СБП и чек, после одобрения бот становится бессрочным."""
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or b["user_id"] != call.from_user.id or not b["trial_until"] or not b["token"]:
        return await call.answer(t("order_bad", lang), show_alert=True)
    if b["pay_status"] == "pending":
        return await call.answer(t("mb_buy_receipt_sent", lang), show_alert=True)
    await state.set_state(None)
    price = bot_price()
    db.set_hosted(bid, pay_status="wait_pay", pay_at=db.now(), price=price)
    await render(call, t("mb_buy_pay", lang, username=html.escape(b["username"] or "?"), price=money(price),
                         details=db.get_setting("sbp_details", config.SBP_DETAILS)), kb([
        [btn("paid", lang, f"mb:paid:{bid}")],
        [btn("cancel", lang, f"mb:cancel:{bid}")],
    ]))
    await call.answer()


@router.callback_query(F.data == "mkbot")
async def cb_mkbot(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(None)
    await info_view(call, lang, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "mb:read")
async def cb_read(call: CallbackQuery, state: FSMContext, lang: str):
    uid = call.from_user.id
    await state.set_state(None)
    # старые неоплаченные заявки больше не нужны
    db.x("UPDATE hosted_bots SET status='canceled' WHERE user_id=? AND status='wait_pay'", (uid,))
    # пробный, на который так и не прислали токен, — отменяем, чтобы токен после оплаты попал в купленного бота
    db.x("UPDATE hosted_bots SET status='canceled' WHERE user_id=? AND trial=1 AND status='wait_token' "
         "AND tg_id IS NULL", (uid,))
    price = bot_price()
    bid = db.create_hosted(uid, price)
    await render(call, t("mb_pay", lang, bid=bid, price=money(price),
                         details=db.get_setting("sbp_details", config.SBP_DETAILS)), kb([
        [btn("paid", lang, f"mb:paid:{bid}")],
        [btn("cancel", lang, f"mb:cancel:{bid}")],
    ]))
    await call.answer()


@router.callback_query(F.data.startswith("mb:paid:"))
async def cb_paid(call: CallbackQuery, state: FSMContext, lang: str):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or b["user_id"] != call.from_user.id or not _waits_pay(b):
        return await call.answer(t("order_bad", lang), show_alert=True)
    await state.set_state(BuildSt.receipt)
    await state.update_data(mb_bid=bid)
    await render(call, t("send_receipt", lang), kb([[btn("cancel", lang, f"mb:cancel:{bid}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("mb:cancel:"))
async def cb_cancel(call: CallbackQuery, state: FSMContext, lang: str):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if b and b["user_id"] == call.from_user.id:
        if b["pay_status"] == "wait_pay":  # отказался покупать пробного бота — он остаётся как был
            db.set_hosted(bid, pay_status=None)
        elif b["status"] == "wait_pay":
            db.set_hosted(bid, status="canceled")
    await state.set_state(None)
    await call.answer(t("order_canceled", lang))
    await info_view(call, lang, call.from_user.id)


@router.message(BuildSt.receipt, F.photo | F.document)
async def msg_receipt(m: Message, state: FSMContext, lang: str, bot: Bot):
    bid = (await state.get_data()).get("mb_bid")
    await state.set_state(None)
    b = db.hosted(bid) if bid else None
    if not b or not _waits_pay(b):
        b = db.hosted_wait_pay(m.from_user.id)
    if not b:
        return await m.answer(t("order_bad", lang), reply_markup=kb([menu_row(lang)]))
    await send_receipt(m, b, lang, bot)


@router.message(BuildSt.receipt)
async def msg_receipt_wrong(m: Message, lang: str):
    await m.answer(t("need_receipt", lang))


def _waits_pay(b):
    """Заявка ждёт чек: новый бот (status) или покупка пробного (pay_status)."""
    return b["status"] == "wait_pay" or b["pay_status"] == "wait_pay"


def _bot_receipt_expected(m: Message):
    """Чек прислали без «Я оплатил» (или после перезапуска бота): он за бота, если заявка на бота новее заказа."""
    return bool(m.from_user) and db.latest_wait_kind(m.from_user.id) == "hosted"


@router.message(StateFilter(None), F.photo | F.document, _bot_receipt_expected)
async def msg_receipt_fallback(m: Message, lang: str, bot: Bot):
    await send_receipt(m, db.hosted_wait_pay(m.from_user.id), lang, bot)


async def send_receipt(m: Message, b, lang: str, bot: Bot):
    bid = b["id"]
    if m.photo:
        file_id, is_photo = m.photo[-1].file_id, True
    else:
        file_id, is_photo = m.document.file_id, False
    buying_trial = b["pay_status"] == "wait_pay"
    if buying_trial:
        db.set_hosted(bid, pay_status="pending", receipt=file_id)
    else:
        db.set_hosted(bid, status="pending", receipt=file_id)
    u = db.get_user(m.from_user.id)
    caption = ((f"🤖 <b>Покупка пробного бота {bot_name(b)} — заявка #{bid}</b>\n"
                f"📍 Сейчас: {bot_status(b['status'], 'ru')}\n\n") if buying_trial else
               f"🤖 <b>Оплата создания бота — заявка #{bid}</b>\n\n") + \
        f"👤 {user_link(u)}\n💰 Сумма: <b>{money(b['price'])}</b>"
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"a:hbok:{bid}", style="success"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"a:hbno:{bid}", style="danger"),
    ]])
    for aid in admins.ids():
        try:
            if is_photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception as e:
            logging.warning("не удалось отправить чек за бота админу %s: %s", aid, e)
    await m.answer(t("mb_buy_receipt_sent" if buying_trial else "mb_receipt_sent", lang),
                   reply_markup=kb([menu_row(lang)]))


# ---------- токен ----------
LOOKS_LIKE_TOKEN = re.compile(r"\d{5,}\s*:")


def _token_expected(m: Message):
    """Перехватываем текст, только если покупатель ждёт запуска бота и прислал что-то похожее на токен."""
    if not m.from_user or not m.text or not db.hosted_wait_token(m.from_user.id):
        return False
    return bool(hosting.find_token(m.text) or LOOKS_LIKE_TOKEN.search(m.text))


@router.message(F.text, _token_expected)
async def msg_token(m: Message, lang: str, bot: Bot):
    uid = m.from_user.id
    token = hosting.find_token(m.text)
    try:
        await m.delete()  # токен — секрет: убираем его из переписки
    except Exception:
        pass
    if uid in _busy:  # предыдущий токен ещё проверяется
        return
    if not token:
        return await m.answer(t("mb_token_format", lang))
    _busy.add(uid)
    try:
        await _accept_token(m, token, lang, bot)
    finally:
        _busy.discard(uid)


async def _accept_token(m: Message, token, lang, bot: Bot):
    uid = m.from_user.id
    wait = await m.answer(t("mb_checking", lang))
    if token == config.BOT_TOKEN:
        return await wait.edit_text(t("mb_token_taken", lang))
    try:
        me = await hosting.check_token(token)
    except hosting.TokenError as e:
        return await wait.edit_text(t(f"mb_token_{e.code}", lang))
    b = db.hosted_wait_token(uid)
    if not b:
        return await wait.edit_text(t("order_bad", lang))
    other = db.hosted_by_tg(me.id)
    if me.id == bot.id or (other and other["id"] != b["id"]):
        return await wait.edit_text(t("mb_token_taken", lang))
    # пробный период — один раз на Telegram-бота (иначе можно бесконечно пересоздавать пробный с тем же ботом)
    if b["trial"] and me.id != b["tg_id"] and db.trial_used(tg_id=me.id):
        return await wait.edit_text(t("mb_trial_used_bot", lang))
    if b["trial_until"] and b["trial_until"] <= db.now():  # пробный уже закончился — новый токен не включит бота
        db.set_hosted(b["id"], status="expired")
        return await wait.edit_text(t("mb_trial_over", lang, username=html.escape(b["username"] or "?"),
                                      price=money(bot_price())), reply_markup=buy_kb(b["id"], lang))

    first = not b["tg_id"]
    fields = dict(token=token, tg_id=me.id, username=me.username, shop_name=me.first_name,
                  status="running", started=db.now())
    if b["trial"] and not b["trial_until"]:  # отсчёт пробного периода — с момента запуска
        fields["trial_until"] = add_days(trial_days() or 3)
    db.set_hosted(b["id"], **fields)
    b = db.hosted(b["id"])
    ok = await hosting.launch(b["id"])
    u = db.get_user(uid)
    trial_note = t("mb_trial_started", lang, until=fmt_until(b["trial_until"])) if b["trial_until"] else ""
    if ok:
        await wait.edit_text(t("mb_started", lang, username=html.escape(me.username)) + trial_note, reply_markup=kb([
            [raw_btn(f"🤖 @{me.username}", url=f"https://t.me/{me.username}", style="success")],
            menu_row(lang),
        ]))
        await to_admins(bot, f"🤖 <b>Бот клиента {'запущен' if first else 'перезапущен с новым токеном'}</b>\n\n"
                             f"🆔 Заявка #{b['id']}\n🤖 @{html.escape(me.username)}\n👤 Владелец: {user_link(u)}"
                             + (f"\n🎁 Пробный до {fmt_until(b['trial_until'])}" if b["trial_until"] else ""))
    else:
        await wait.edit_text(t("mb_start_fail", lang, username=html.escape(me.username)),
                             reply_markup=kb([menu_row(lang)]))
        await to_admins(bot, f"⚠️ <b>Бот клиента не запустился</b>\n\n🆔 Заявка #{b['id']}\n🤖 @{html.escape(me.username)}\n"
                             f"👤 Владелец: {user_link(u)}\n\nЛог: админ-панель → 🤖 Боты клиентов → #{b['id']} → 📄 Лог")


@router.callback_query(F.data.startswith("mb:tok:"))
async def cb_new_token(call: CallbackQuery, lang: str):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or b["user_id"] != call.from_user.id or b["status"] != "failed":
        return await call.answer(t("order_bad", lang), show_alert=True)
    db.set_hosted(bid, status="wait_token")
    await render(call, t("mb_new_token", lang, username=html.escape(b["username"] or "?")),
                 kb([[btn("back", lang, "mkbot")]]))
    await call.answer()


# ======================= админ: чеки и боты клиентов =======================
@admin_router.callback_query(F.data.startswith("a:hbok:") | F.data.startswith("a:hbno:"))
async def cb_hb_receipt(call: CallbackQuery, bot: Bot):
    _, op, bid = call.data.split(":")
    b = db.hosted(int(bid))
    if b and b["pay_status"] == "pending":  # покупка пробного бота
        return await _trial_receipt(call, bot, b, op == "hbok")
    if not b or b["status"] != "pending":
        await mark_admin_msg(call, f"ℹ️ Уже обработана: {bot_status(b['status'], 'ru') if b else '—'}")
        return await call.answer("Заявка уже обработана", show_alert=True)
    u = db.get_user(b["user_id"])
    lang = u["lang"] if u else "ru"
    who = html.escape(call.from_user.first_name)
    if op == "hbok":
        db.set_hosted(b["id"], status="wait_token")
        await safe_send(bot, b["user_id"], t("mb_approved", lang), kb([[btn("main_menu", lang, "menu")]]))
        await mark_admin_msg(call, f"✅ Одобрено, ждём токен от покупателя ({who})")
        await call.answer("Одобрено")
    else:
        db.set_hosted(b["id"], status="rejected")
        await safe_send(bot, b["user_id"], t("mb_rejected", lang, bid=b["id"]),
                        kb([[btn("support", lang, "sup")]]))
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")


async def make_permanent(bot: Bot, b):
    """Бот куплен (или админ сделал его бессрочным): снимаем пробный срок и включаем, если он был выключен."""
    db.set_hosted(b["id"], trial_until=None, pay_status=None)
    if b["status"] == "expired" and b["token"]:
        db.set_hosted(b["id"], status="running")
        return await hosting.launch(b["id"])
    return b["status"] == "running"


async def _trial_receipt(call: CallbackQuery, bot: Bot, b, ok):
    u = db.get_user(b["user_id"])
    lang = u["lang"] if u else "ru"
    who = html.escape(call.from_user.first_name)
    name = html.escape(b["username"] or "?")
    if ok:
        running = await make_permanent(bot, b)
        await safe_send(bot, b["user_id"], t("mb_bought", lang, username=name),
                        kb([[raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}", style="success")],
                            [btn("main_menu", lang, "menu")]]) if b["username"] else None)
        await mark_admin_msg(call, f"✅ Одобрено, бот бессрочный{'' if running else ' (не запустился — смотрите лог)'} "
                                   f"({who})")
        await call.answer("Одобрено")
    else:
        db.set_hosted(b["id"], pay_status=None)
        await safe_send(bot, b["user_id"], t("mb_buy_rejected", lang, username=name), kb([[btn("support", lang, "sup")]]))
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")


def from_ctor(b):
    """Магазин создан через бот-конструктор — владельцу пишем от конструктора."""
    return b is not None and "source" in b.keys() and b["source"] == "ctor"


def _ctor():
    from ctor import bot as ctor_bot
    return ctor_bot


async def owner_send(bot: Bot, b, text, markup=None):
    if from_ctor(b) and _ctor().running():
        return await _ctor().send(b["user_id"], text)
    return await safe_send(bot, b["user_id"], text, markup)


async def trial_loop(bot: Bot):
    """Раз в минуту: напоминаем за сутки до конца пробного и выключаем ботов, у которых он закончился."""
    while True:
        try:
            await _trial_tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("проверка пробных периодов не удалась")
        await asyncio.sleep(60)


async def _trial_tick(bot: Bot):
    price = money(bot_price())
    for b in db.trials_to_warn():
        db.set_hosted(b["id"], trial_warned=1)
        if from_ctor(b):
            await _ctor().trial_notice(b, "soon")
            continue
        u = db.get_user(b["user_id"])
        lang = u["lang"] if u else "ru"
        await safe_send(bot, b["user_id"], t("mb_trial_soon", lang, username=html.escape(b["username"] or "?"),
                                             until=fmt_until(b["trial_until"]), price=price), buy_kb(b["id"], lang))
    for b in db.trials_to_expire():
        db.set_hosted(b["id"], status="expired")
        await hosting.stop(b["id"])
        u = db.get_user(b["user_id"])
        lang = u["lang"] if u else "ru"
        if from_ctor(b):
            await _ctor().trial_notice(b, "over")
            await to_admins(bot, f"⌛ Пробный период магазина #{b['id']} ({bot_name(b)}) из конструктора закончился — "
                                 f"бот выключен.")
            continue
        await safe_send(bot, b["user_id"], t("mb_trial_over", lang, username=html.escape(b["username"] or "?"),
                                             price=price), buy_kb(b["id"], lang) if b["token"] else None)
        await to_admins(bot, f"⌛ Пробный период бота клиента #{b['id']} ({bot_name(b)}) закончился — бот выключен.\n"
                             f"👤 Владелец: {user_link(u) if u else b['user_id']}")


STATUS_ICON = {"pending": "🔎", "wait_token": "🔑", "running": "✅", "stopped": "⏸", "failed": "⚠️", "rejected": "❌",
               "expired": "⌛"}


@admin_router.callback_query(F.data == "a:hb")
async def cb_hb_list(call: CallbackQuery):
    await hb_list(call)
    await call.answer()


async def hb_list(target, prefix=""):
    bots = db.hosted_list()
    rows = []
    for b in bots:
        rows.append([B(f"{STATUS_ICON.get(b['status'], '•')} #{b['id']} {('@' + b['username']) if b['username'] else '—'}",
                       f"a:hbv:{b['id']}")])
    rows.append([B(f"📢 Рассылка владельцам ботов ({len(db.hosted_owner_ids())})", "a:hbbc", style="primary")])
    rows.append([B("📦 Бэкап всех баз (.zip)", "a:hbzip")])
    rows.append(back())
    running = sum(1 for b in bots if b["status"] == "running")
    text = (f"{prefix}🤖 <b>Боты клиентов</b>\n\nРаботает: <b>{running}</b> · всего: <b>{len(bots)}</b>\n"
            f"Цена создания: <b>{money(bot_price())}</b> (⚙️ Настройки)\n\n"
            f"🎁 Пробный период: <b>{trial_days() or 'выключен'}</b>{' дн.' if trial_days() else ''} (⚙️ Настройки)\n\n"
            "✅ работает · 🔑 ждёт токен · 🔎 чек на проверке · ⏸ остановлен · ⚠️ упал · ❌ отклонён · "
            "⌛ пробный закончился")
    if not bots:
        text += "\n\n<i>Пока никто не создал бота.</i>"
    await render(target, text, kb(rows))


async def hb_view(target, bid, prefix=""):
    b = db.hosted(bid)
    if not b:
        return await hb_list(target, "Бот не найден.\n\n")
    u = db.get_user(b["user_id"])
    text = (f"{prefix}🤖 <b>Бот клиента #{b['id']}</b>\n\n"
            f"🤖 Бот: {bot_name(b)}" + (" · 🏗 из конструктора" if from_ctor(b) else "") + "\n"
            f"👤 Владелец: {user_link(u) if u else b['user_id']}\n"
            f"📍 Статус: {bot_status(b['status'], 'ru')}"
            + (" (процесс работает)" if hosting.is_alive(b["id"]) else "") + "\n"
            + (f"🎁 Пробный до: <b>{fmt_until(b['trial_until'])}</b>"
               + (" · 🔎 чек за покупку на проверке" if b["pay_status"] == "pending" else "") + "\n"
               if b["trial_until"] else
               f"💰 Оплачено: {money(b['price'])}" + (" (был пробный)" if b["trial"] else "") + "\n")
            + f"📅 Заявка: {fdate(b['created'])}\n"
            f"🚀 Запущен: {fdate(b['started']) if b['started'] else '—'}")
    if b["token"]:
        text += ("\n\n🔑 <b>Полный доступ:</b> вы админ в этом боте — откройте его и отправьте /admin. "
                 "Чеки и обращения этого бота приходят его владельцу, а не вам.")
    rows = []
    if b["status"] == "running":
        rows.append([B("⏸ Остановить", f"a:hbs:{bid}", style="danger"), B("🔄 Перезапустить", f"a:hbrs:{bid}")])
    elif b["status"] in ("stopped", "failed") and b["token"]:
        rows.append([B("▶️ Запустить", f"a:hbr:{bid}", style="success")])
    if b["trial_until"] and b["token"]:
        rows.append([B(f"🎁 +{trial_days() or 3} дн. пробного", f"a:hbtx:{bid}"),
                     B("♾ Сделать бессрочным", f"a:hbtp:{bid}", style="success")])
    if b["username"]:
        rows.append([B(f"🔗 Открыть @{b['username']} (/admin)", url=f"https://t.me/{b['username']}", style="primary")])
    if os.path.exists(hosting.db_path(bid)):
        rows.append([B("📊 Статистика", f"a:hbst:{bid}"), B("💾 Скачать базу", f"a:hbdb:{bid}")])
    if b["token"]:
        rows.append([B("♻️ Загрузить базу", f"a:hbup:{bid}"), B("📄 Лог", f"a:hbl:{bid}")])
    rows.append([B("✉️ Написать владельцу", f"a:umsg:{b['user_id']}"), B("👤 Владелец", f"a:tku:{b['user_id']}")])
    rows.append([B("🗑 Удалить", f"a:hbd:{bid}", style="danger")])
    rows.append(back("a:hb", "◀️ К списку"))
    await render(target, text, kb(rows))


# ---------- полный доступ к ботам клиентов: статистика, база ----------
def child_stats(bid):
    """Статистика бота клиента прямо из его базы (только чтение)."""
    path = hosting.db_path(bid)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        def v(sql):
            try:
                return con.execute(sql).fetchone()[0]
            except sqlite3.Error:
                return 0
        paid = "status IN ('done','manual')"
        return {
            "users": v("SELECT COUNT(*) FROM users"),
            "users_today": v("SELECT COUNT(*) FROM users WHERE joined >= date('now','localtime')"),
            "orders": v(f"SELECT COUNT(*) FROM orders WHERE {paid}"),
            "rev": v(f"SELECT COALESCE(SUM(price),0) FROM orders WHERE {paid}"),
            "rev_week": v(f"SELECT COALESCE(SUM(price),0) FROM orders WHERE {paid} AND created >= date('now','localtime','-7 days')"),
            "products": v("SELECT COUNT(*) FROM products"),
            "stock": v("SELECT COUNT(*) FROM items WHERE sold=0"),
            "balances": v("SELECT COALESCE(SUM(balance),0) FROM users"),
            "tickets": v("SELECT COUNT(*) FROM tickets WHERE status='open'"),
            "topups": v("SELECT COALESCE(SUM(amount),0) FROM topups WHERE status='done'"),
            "pending": v("SELECT COUNT(*) FROM orders WHERE status='pending'"),
        }
    finally:
        con.close()


@admin_router.callback_query(F.data.startswith("a:hbst:"))
async def cb_hb_stats(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    try:
        s = child_stats(bid)
    except sqlite3.Error as e:
        return await call.answer(f"База не читается: {e}", show_alert=True)
    text = (f"📊 <b>Статистика бота {bot_name(b)}</b>\n<blockquote>"
            f"👥 Пользователей: <b>{s['users']}</b> (+{s['users_today']} сегодня)\n"
            f"🛒 Продаж: <b>{s['orders']}</b> на <b>{money(s['rev'])}</b>\n"
            f"📅 За 7 дней: {money(s['rev_week'])}\n"
            f"💳 Пополнений: {money(s['topups'])}\n"
            f"📦 Товаров: {s['products']} · на складе {s['stock']}\n"
            f"💰 Сумма балансов: {money(s['balances'])}\n"
            f"🔎 Чеков на проверке: {s['pending']} · 💬 обращений: {s['tickets']}</blockquote>")
    await render(call, text, kb([[B("🔄 Обновить", f"a:hbst:{bid}")], back(f"a:hbv:{bid}", "◀️ К боту")]))
    await call.answer()


def _child_backup(bid):
    src = sqlite3.connect(f"file:{hosting.db_path(bid)}?mode=ro", uri=True)
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(path)
        src.backup(dst)
        dst.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        src.close()
        os.remove(path)


@admin_router.callback_query(F.data.startswith("a:hbdb:"))
async def cb_hb_db(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    try:
        data = _child_backup(bid)
    except (sqlite3.Error, OSError) as e:
        return await call.answer(f"Не удалось: {e}", show_alert=True)
    name = f"bot_{bid}_{(b['username'] or 'client')}_{db.now()[:10]}.db"
    await call.message.answer_document(BufferedInputFile(data, name), caption=f"💾 База бота {bot_name(b)}")
    await call.answer()


@admin_router.callback_query(F.data == "a:hbzip")
async def cb_hb_zip(call: CallbackQuery):
    await call.answer("Собираю архив…")
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"main_{db.now()[:10]}.db", db.backup_bytes())
        for b in db.hosted_list():
            if os.path.exists(hosting.db_path(b["id"])):
                try:
                    z.writestr(f"bot_{b['id']}_{b['username'] or 'client'}.db", _child_backup(b["id"]))
                    n += 1
                except (sqlite3.Error, OSError):
                    pass
    await call.message.answer_document(BufferedInputFile(buf.getvalue(), f"all_bots_{db.now()[:10]}.zip"),
                                       caption=f"📦 Основная база + базы {n} ботов клиентов.")


@admin_router.callback_query(F.data.startswith("a:hbrs:"))
async def cb_hb_restart(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    await call.answer("Перезапускаю…")
    ok = await hosting.restart(bid)
    await hb_view(call, bid, "🔄 Бот перезапущен.\n\n" if ok else "⚠️ Бот не запустился — смотрите лог.\n\n")


@admin_router.callback_query(F.data.startswith("a:hbup:"))
async def cb_hb_upload(call: CallbackQuery, state: FSMContext):
    if not admins.is_owner(call.from_user.id):
        return await call.answer("Это могут только владельцы.", show_alert=True)
    bid = int(call.data.split(":")[2])
    await ask(call, state, "hbup", f"♻️ <b>Замена базы бота #{bid}</b>\n\nОтправьте файл <code>.db</code> документом. "
                                   "Бот клиента остановится, база заменится, и он запустится снова. "
                                   "Старую базу я пришлю вам перед заменой.", cancel=f"a:hbv:{bid}", bid=bid)


@inp("hbup")
async def i_hb_upload(m, state, d, txt, bot):
    bid = d["bid"]
    if not m.document:
        return await m.answer("Отправьте файл .db документом:")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await bot.download(m.document, destination=path)
        err = db.check_backup(path)
        if err:
            return await m.answer(f"❌ Файл не подходит: {err}. Отправьте другой:")
        if os.path.exists(hosting.db_path(bid)):
            await m.answer_document(BufferedInputFile(_child_backup(bid), f"bot_{bid}_before.db"),
                                    caption="💾 База бота до замены.")
        was_running = db.hosted(bid)["status"] == "running"
        await hosting.stop(bid)
        os.makedirs(os.path.dirname(hosting.db_path(bid)), exist_ok=True)
        dst = sqlite3.connect(hosting.db_path(bid))
        src = sqlite3.connect(path)
        src.backup(dst)
        src.close()
        dst.close()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    await state.clear()
    ok = await hosting.launch(bid) if was_running else None
    note = "✅ База заменена" + (", бот запущен." if ok else ", но бот не запустился — смотрите лог." if was_running else ".")
    await hb_view(m, bid, note + "\n\n")


@admin_router.callback_query(F.data == "a:hbbc")
async def cb_hb_broadcast(call: CallbackQuery, state: FSMContext):
    n = len(db.hosted_owner_ids())
    if not n:
        return await call.answer("Пока нет владельцев ботов", show_alert=True)
    await ask(call, state, "hbbc", f"📢 <b>Рассылка владельцам ботов</b> ({n} чел.)\n\n"
                                   "Отправьте сообщение — текст, фото, видео или файл. Его получат все, "
                                   "кто купил бота (форматирование и премиум-эмодзи сохранятся).", cancel="a:hb")


@inp("hbbc")
async def i_hb_broadcast(m, state, d, txt, bot):
    ids = db.hosted_owner_ids()

    async def send(b, uid):
        await b.copy_message(uid, m.chat.id, m.message_id)

    asyncio.create_task(broadcast(bot, ids, send, m.from_user.id))
    await done(m, state, f"📢 Рассылка запущена на {len(ids)} владельцев ботов. Когда закончится — пришлю отчёт.",
               kb([back("a:hb", "◀️ К ботам клиентов")]))


@admin_router.callback_query(F.data.startswith("a:hbv:"))
async def cb_hb_view(call: CallbackQuery):
    await hb_view(call, int(call.data.split(":")[2]))
    await call.answer()


@admin_router.callback_query(F.data.startswith("a:hbs:"))
async def cb_hb_stop(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    db.set_hosted(bid, status="stopped")
    await hosting.stop(bid)
    await hb_view(call, bid, "⏸ Бот остановлен.\n\n")
    await call.answer("Остановлен")


@admin_router.callback_query(F.data.startswith("a:hbr:"))
async def cb_hb_run(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or not b["token"]:
        return await call.answer("У бота нет токена", show_alert=True)
    await call.answer("Запускаю…")
    db.set_hosted(bid, status="running")
    ok = await hosting.launch(bid)
    await hb_view(call, bid, "▶️ Бот запущен.\n\n" if ok else "⚠️ Бот не запустился — смотрите лог.\n\n")


@admin_router.callback_query(F.data.startswith("a:hbtx:"))
async def cb_hb_trial_extend(call: CallbackQuery, bot: Bot):
    """Продлить пробный период (от текущего конца или от сейчас, если уже закончился) и включить бота."""
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or not b["trial_until"]:
        return await call.answer("Бот уже не пробный", show_alert=True)
    await call.answer("Продлеваю…")
    until = add_days(trial_days() or 3, b["trial_until"])
    db.set_hosted(bid, trial_until=until, trial_warned=0)
    note = f"🎁 Пробный продлён до {fmt_until(until)}.\n\n"
    if b["status"] == "expired" and b["token"]:
        db.set_hosted(bid, status="running")
        if not await hosting.launch(bid):
            note += "⚠️ Бот не запустился — смотрите лог.\n\n"
    u = db.get_user(b["user_id"])
    await owner_send(bot, b, t("mb_trial_extended", u["lang"] if u else "ru",
                               username=html.escape(b["username"] or "?"), until=fmt_until(until)))
    await hb_view(call, bid, note)


@admin_router.callback_query(F.data.startswith("a:hbtp:"))
async def cb_hb_trial_permanent(call: CallbackQuery, bot: Bot):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if not b or not b["trial_until"]:
        return await call.answer("Бот уже бессрочный", show_alert=True)
    await call.answer("Готово")
    running = await make_permanent(bot, b)
    u = db.get_user(b["user_id"])
    await owner_send(bot, b, t("mb_bought", u["lang"] if u else "ru", username=html.escape(b["username"] or "?")))
    await hb_view(call, bid, "♾ Бот бессрочный.\n\n" if running else "♾ Бот бессрочный, но не запустился — смотрите лог.\n\n")


@admin_router.callback_query(F.data.startswith("a:hbl:"))
async def cb_hb_log(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    try:
        with open(hosting.log_path(bid), "rb") as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - 200_000, 0))
            data = f.read()
    except OSError:
        return await call.answer("Лога пока нет", show_alert=True)
    if not data.strip():
        return await call.answer("Лог пуст", show_alert=True)
    await call.message.answer_document(BufferedInputFile(data, f"bot_{bid}.log"),
                                       caption=f"📄 Лог бота клиента #{bid} (последние записи)")
    await call.answer()


@admin_router.callback_query(F.data.startswith("a:hbd:"))
async def cb_hb_del(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    await render(call, f"🗑 Удалить бота клиента #{bid}?\n\nБот будет остановлен и пропадёт из списка. "
                       "Его база с товарами останется на сервере.",
                 kb([[B("🗑 Да, удалить", f"a:hbd2:{bid}", style="danger")], back(f"a:hbv:{bid}", "◀️ Отмена")]))
    await call.answer()


@admin_router.callback_query(F.data.startswith("a:hbd2:"))
async def cb_hb_del2(call: CallbackQuery):
    bid = int(call.data.split(":")[2])
    db.set_hosted(bid, status="deleted")
    await hosting.stop(bid)
    try:
        os.remove(hosting.cfg_path(bid))  # в файле токен бота клиента
    except OSError:
        pass
    await hb_list(call, f"🗑 Бот #{bid} удалён.\n\n")
    await call.answer("Удалён")
