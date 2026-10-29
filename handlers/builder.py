"""«🤖 Создать своего бота»: покупатель оплачивает создание, админ одобряет чек, покупатель присылает токен
от @BotFather — и копия магазина сама запускается на этом же сервере (см. hosting.py).

Путь покупателя: 🤖 Создать своего бота → ✅ Я прочитал → реквизиты СБП → ✅ Я оплатил → чек
→ админу приходит чек с кнопками ✅ Одобрить / ❌ Отклонить → «пришлите токен» → токен → бот запущен.
Админ-панель → 🤖 Боты клиентов: список, остановка, запуск, лог, удаление.
"""
import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import admins
import config
import db
import hosting
from handlers.admin import B, back, mark_admin_msg, router as admin_router
from services import safe_send, to_admins, user_link
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


# ======================= покупатель =======================
async def info_view(target, lang, uid):
    text = t("mb_info", lang, price=money(bot_price()))
    rows = [[btn("mb_read", lang, "mb:read")]]
    bots = db.user_hosted(uid)
    if bots:
        text += t("mb_bots_head", lang)
        for b in bots[:10]:
            text += t("mb_bot_line", lang, name=bot_name(b), status=bot_status(b["status"], lang))
            if b["status"] == "running" and b["username"]:
                rows.append([raw_btn(f"🤖 @{b['username']}", url=f"https://t.me/{b['username']}")])
            elif b["status"] == "failed":
                rows.append([raw_btn(f"{bt('mb_token', lang)} · @{b['username']}", f"mb:tok:{b['id']}")])
        if any(b["status"] == "wait_token" for b in bots):
            text += t("mb_send_token", lang)
    rows.append(menu_row(lang))
    await render(target, text, kb(rows))


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
    if not b or b["user_id"] != call.from_user.id or b["status"] != "wait_pay":
        return await call.answer(t("order_bad", lang), show_alert=True)
    await state.set_state(BuildSt.receipt)
    await state.update_data(mb_bid=bid)
    await render(call, t("send_receipt", lang), kb([[btn("cancel", lang, f"mb:cancel:{bid}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("mb:cancel:"))
async def cb_cancel(call: CallbackQuery, state: FSMContext, lang: str):
    bid = int(call.data.split(":")[2])
    b = db.hosted(bid)
    if b and b["user_id"] == call.from_user.id and b["status"] == "wait_pay":
        db.set_hosted(bid, status="canceled")
    await state.set_state(None)
    await call.answer(t("order_canceled", lang))
    await info_view(call, lang, call.from_user.id)


@router.message(BuildSt.receipt, F.photo | F.document)
async def msg_receipt(m: Message, state: FSMContext, lang: str, bot: Bot):
    bid = (await state.get_data()).get("mb_bid")
    await state.set_state(None)
    b = db.hosted(bid) if bid else None
    if not b or b["status"] != "wait_pay":
        b = db.hosted_wait_pay(m.from_user.id)
    if not b:
        return await m.answer(t("order_bad", lang), reply_markup=kb([menu_row(lang)]))
    await send_receipt(m, b, lang, bot)


@router.message(BuildSt.receipt)
async def msg_receipt_wrong(m: Message, lang: str):
    await m.answer(t("need_receipt", lang))


def _bot_receipt_expected(m: Message):
    """Чек прислали без «Я оплатил» (или после перезапуска бота): он за бота, если заявка на бота новее заказа."""
    if not m.from_user:
        return False
    b = db.hosted_wait_pay(m.from_user.id)
    if not b:
        return False
    o = db.last_wait_pay(m.from_user.id)
    return o is None or b["created"] >= o["created"]


@router.message(StateFilter(None), F.photo | F.document, _bot_receipt_expected)
async def msg_receipt_fallback(m: Message, lang: str, bot: Bot):
    await send_receipt(m, db.hosted_wait_pay(m.from_user.id), lang, bot)


async def send_receipt(m: Message, b, lang: str, bot: Bot):
    bid = b["id"]
    if m.photo:
        file_id, is_photo = m.photo[-1].file_id, True
    else:
        file_id, is_photo = m.document.file_id, False
    db.set_hosted(bid, status="pending", receipt=file_id)
    u = db.get_user(m.from_user.id)
    caption = (f"🤖 <b>Оплата создания бота — заявка #{bid}</b>\n\n👤 {user_link(u)}\n"
               f"💰 Сумма: <b>{money(b['price'])}</b>")
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
    await m.answer(t("mb_receipt_sent", lang), reply_markup=kb([menu_row(lang)]))


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

    first = not b["tg_id"]
    db.set_hosted(b["id"], token=token, tg_id=me.id, username=me.username, shop_name=me.first_name,
                  status="running", started=db.now())
    ok = await hosting.launch(b["id"])
    u = db.get_user(uid)
    if ok:
        await wait.edit_text(t("mb_started", lang, username=html.escape(me.username)), reply_markup=kb([
            [raw_btn(f"🤖 @{me.username}", url=f"https://t.me/{me.username}", style="success")],
            menu_row(lang),
        ]))
        await to_admins(bot, f"🤖 <b>Бот клиента {'запущен' if first else 'перезапущен с новым токеном'}</b>\n\n"
                             f"🆔 Заявка #{b['id']}\n🤖 @{html.escape(me.username)}\n👤 Владелец: {user_link(u)}")
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
        surl = fix_url(db.get_setting("support_url", config.SUPPORT_URL))
        await safe_send(bot, b["user_id"], t("mb_rejected", lang, bid=b["id"]),
                        kb([[InlineKeyboardButton(text=bt("support", lang), url=surl)]]) if surl else None)
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")


STATUS_ICON = {"pending": "🔎", "wait_token": "🔑", "running": "✅", "stopped": "⏸", "failed": "⚠️", "rejected": "❌"}


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
    rows.append(back())
    running = sum(1 for b in bots if b["status"] == "running")
    text = (f"{prefix}🤖 <b>Боты клиентов</b>\n\nРаботает: <b>{running}</b> · всего: <b>{len(bots)}</b>\n"
            f"Цена создания: <b>{money(bot_price())}</b> (⚙️ Настройки)\n\n"
            "✅ работает · 🔑 ждёт токен · 🔎 чек на проверке · ⏸ остановлен · ⚠️ упал · ❌ отклонён")
    if not bots:
        text += "\n\n<i>Пока никто не создал бота.</i>"
    await render(target, text, kb(rows))


async def hb_view(target, bid, prefix=""):
    b = db.hosted(bid)
    if not b:
        return await hb_list(target, "Бот не найден.\n\n")
    u = db.get_user(b["user_id"])
    text = (f"{prefix}🤖 <b>Бот клиента #{b['id']}</b>\n\n"
            f"🤖 Бот: {bot_name(b)}\n"
            f"👤 Владелец: {user_link(u) if u else b['user_id']}\n"
            f"📍 Статус: {bot_status(b['status'], 'ru')}"
            + (" (процесс работает)" if hosting.is_alive(b["id"]) else "") + "\n"
            f"💰 Оплачено: {money(b['price'])}\n"
            f"📅 Заявка: {fdate(b['created'])}\n"
            f"🚀 Запущен: {fdate(b['started']) if b['started'] else '—'}")
    rows = []
    if b["status"] == "running":
        rows.append([B("⏸ Остановить", f"a:hbs:{bid}", style="danger")])
    elif b["status"] in ("stopped", "failed") and b["token"]:
        rows.append([B("▶️ Запустить", f"a:hbr:{bid}", style="success")])
    if b["username"]:
        rows.append([B(f"🔗 @{b['username']}", url=f"https://t.me/{b['username']}")])
    if b["token"]:
        rows.append([B("📄 Лог", f"a:hbl:{bid}")])
    rows.append([B("🗑 Удалить", f"a:hbd:{bid}", style="danger")])
    rows.append(back("a:hb", "◀️ К списку"))
    await render(target, text, kb(rows))


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
    await hb_list(call, f"🗑 Бот #{bid} удалён.\n\n")
    await call.answer("Удалён")
