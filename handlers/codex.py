"""«🔐 Верификация Codex»: покупатель платит (СБП с чеком, звёзды или баланс), получает номер +1 из API сервиса
виртуальных номеров, запрашивает код из SMS и подтверждает. Если номер получить не удалось или покупатель
отменил его до прихода кода — деньги возвращаются на баланс бота.

Админ-панель → 🔐 Верификация Codex: включение, цены, подключение API номеров, баланс сервиса.
"""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

import admins
import config
import db
import numbers_api as api
from handlers.admin import B, ask, back, done, inp, mark_admin_msg, parse_amount, router as admin_router
from services import ask_review, safe_send, to_admins, user_link
from texts import bt, money, t
from ui import btn, codex_on, fix_url, kb, menu_row, render

router = Router()


class CodexSt(StatesGroup):
    receipt = State()


def cx_price():
    try:
        return float(db.get_setting("cx_price", config.CODEX_PRICE))
    except ValueError:
        return float(config.CODEX_PRICE)


def cx_stars():
    try:
        return int(float(db.get_setting("cx_stars", config.CODEX_STARS)))
    except ValueError:
        return config.CODEX_STARS


def available():
    return codex_on() and api.configured()


# ======================= покупатель =======================
def active_kb(v, lang):
    if v["status"] == "code":
        return kb([[btn("cx_confirm", lang, f"cx:ok:{v['id']}")],
                   [btn("cx_get_code", lang, f"cx:code:{v['id']}")]])
    return kb([[btn("cx_get_code", lang, f"cx:code:{v['id']}")],
               [btn("cx_cancel_num", lang, f"cx:cnl:{v['id']}")]])


@router.callback_query(F.data == "codex")
async def cb_codex(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(None)
    uid = call.from_user.id
    v = db.codex_active(uid)
    if v:  # уже есть выданный номер — показываем его
        text = t("cx_number", lang, number=v["number"])
        if v["status"] == "code":
            text += "\n\n" + t("cx_code", lang, code=html.escape(v["code"]))
        await render(call, text, active_kb(v, lang))
        return await call.answer()
    if not available():
        return await call.answer(t("cx_off", lang), show_alert=True)
    u = db.get_user(uid)
    await render(call, t("cx_info", lang, price=money(cx_price()), stars=cx_stars(), balance=money(u["balance"])), kb([
        [btn("cx_sbp", lang, "cx:sbp")],
        [btn("cx_stars", lang, "cx:star")],
        [btn("cx_balance", lang, "cx:bal")],
        menu_row(lang),
    ]))
    await call.answer()


@router.callback_query(F.data == "cx:sbp")
async def cb_sbp(call: CallbackQuery, lang: str):
    if not available():
        return await call.answer(t("cx_off", lang), show_alert=True)
    uid = call.from_user.id
    db.x("UPDATE codex SET status='canceled' WHERE user_id=? AND status='wait_pay'", (uid,))
    vid = db.create_codex(uid, "sbp", cx_price(), 0)
    await render(call, t("cx_pay", lang, vid=vid, price=money(cx_price()),
                         details=db.get_setting("sbp_details", config.SBP_DETAILS)), kb([
        [btn("paid", lang, f"cx:paid:{vid}")],
        [btn("cancel", lang, f"cx:cancel:{vid}")],
    ]))
    await call.answer()


@router.callback_query(F.data.startswith("cx:paid:"))
async def cb_paid(call: CallbackQuery, state: FSMContext, lang: str):
    vid = int(call.data.split(":")[2])
    v = db.codex(vid)
    if not v or v["user_id"] != call.from_user.id or v["status"] != "wait_pay":
        return await call.answer(t("order_bad", lang), show_alert=True)
    await state.set_state(CodexSt.receipt)
    await state.update_data(cx_vid=vid)
    await render(call, t("send_receipt", lang), kb([[btn("cancel", lang, f"cx:cancel:{vid}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("cx:cancel:"))
async def cb_cancel(call: CallbackQuery, state: FSMContext, lang: str):
    vid = int(call.data.split(":")[2])
    v = db.codex(vid)
    if v and v["user_id"] == call.from_user.id and v["status"] == "wait_pay":
        db.set_codex(vid, status="canceled")
    await state.set_state(None)
    await render(call, t("order_canceled", lang), kb([menu_row(lang)]))
    await call.answer()


@router.message(CodexSt.receipt, F.photo | F.document)
async def msg_receipt(m: Message, state: FSMContext, lang: str, bot: Bot):
    vid = (await state.get_data()).get("cx_vid")
    await state.set_state(None)
    v = db.codex(vid) if vid else None
    if not v or v["status"] != "wait_pay":
        v = db.codex_wait_pay(m.from_user.id)
    if not v:
        return await m.answer(t("order_bad", lang), reply_markup=kb([menu_row(lang)]))
    await send_receipt(m, v, lang, bot)


@router.message(CodexSt.receipt)
async def msg_receipt_wrong(m: Message, lang: str):
    await m.answer(t("need_receipt", lang))


def _codex_receipt_expected(m: Message):
    """Чек без «Я оплатил»: он за верификацию, если эта заявка новее заказа и заявки на бота."""
    return bool(m.from_user) and db.latest_wait_kind(m.from_user.id) == "codex"


@router.message(StateFilter(None), F.photo | F.document, _codex_receipt_expected)
async def msg_receipt_fallback(m: Message, lang: str, bot: Bot):
    await send_receipt(m, db.codex_wait_pay(m.from_user.id), lang, bot)


async def send_receipt(m: Message, v, lang: str, bot: Bot):
    vid = v["id"]
    if m.photo:
        file_id, is_photo = m.photo[-1].file_id, True
    else:
        file_id, is_photo = m.document.file_id, False
    db.set_codex(vid, status="pending", receipt=file_id)
    u = db.get_user(m.from_user.id)
    caption = (f"🔐 <b>Оплата верификации Codex — заявка #{vid}</b>\n\n👤 {user_link(u)}\n"
               f"💰 Сумма: <b>{money(v['price'])}</b>")
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"a:cxok:{vid}", style="success"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"a:cxno:{vid}", style="danger"),
    ]])
    for aid in admins.ids():
        try:
            if is_photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception as e:
            logging.warning("не удалось отправить чек верификации админу %s: %s", aid, e)
    await m.answer(t("cx_receipt_sent", lang), reply_markup=kb([menu_row(lang)]))


@router.callback_query(F.data == "cx:star")
async def cb_star(call: CallbackQuery, lang: str):
    if not available():
        return await call.answer(t("cx_off", lang), show_alert=True)
    stars = cx_stars()
    vid = db.create_codex(call.from_user.id, "stars", cx_price(), stars)
    title = bt("codex", lang).lstrip("🔐 ").strip()[:32]
    await call.message.answer_invoice(title=title, description=title + f" · #{vid}", payload=f"cx:{vid}",
                                      currency="XTR", prices=[LabeledPrice(label=title, amount=stars)])
    await call.answer()


@router.callback_query(F.data == "cx:bal")
async def cb_balance(call: CallbackQuery, lang: str, bot: Bot):
    if not available():
        return await call.answer(t("cx_off", lang), show_alert=True)
    u = db.get_user(call.from_user.id)
    price = cx_price()
    if u["balance"] < price:
        return await call.answer(t("no_money", lang), show_alert=True)
    db.add_balance(u["id"], -price)
    vid = db.create_codex(u["id"], "balance", price, 0, status="paid")
    await call.answer()
    await issue_number(bot, vid)


async def issue_number(bot: Bot, vid):
    """Оплата есть — берём номер +1 у сервиса и выдаём покупателю. Не вышло — деньги на баланс."""
    v = db.codex(vid)
    uid = v["user_id"]
    u = db.get_user(uid)
    lang = u["lang"] if u else "ru"
    await safe_send(bot, uid, t("cx_getting", lang))
    try:
        act_id, number = await api.get_number()
    except api.NumError as e:
        db.add_balance(uid, v["price"])
        db.set_codex(vid, status="refunded")
        await safe_send(bot, uid, t("cx_fail", lang, price=money(v["price"])), kb([menu_row(lang)]))
        await to_admins(bot, f"⚠️ <b>Верификация #{vid}: номер не выдан</b>\n👤 {user_link(u)}\n"
                             f"Причина: {html.escape(str(e))}\n{money(v['price'])} возвращено покупателю на баланс.")
        return False
    db.set_codex(vid, status="active", act_id=act_id, number=number)
    await safe_send(bot, uid, t("cx_number", lang, number=number), active_kb(db.codex(vid), lang))
    return True


def _own(call, vid, statuses):
    v = db.codex(vid)
    if not v or v["user_id"] != call.from_user.id or v["status"] not in statuses:
        return None
    return v


@router.callback_query(F.data.startswith("cx:code:"))
async def cb_code(call: CallbackQuery, lang: str):
    vid = int(call.data.split(":")[2])
    v = _own(call, vid, ("active", "code"))
    if not v:
        return await call.answer(t("order_bad", lang), show_alert=True)
    try:
        code = await api.get_code(v["act_id"])
    except api.NumError as e:
        logging.warning("верификация #%s: код не получен: %s", vid, e)
        return await call.answer(t("cx_wait", lang), show_alert=True)
    if not code:
        return await call.answer(t("cx_wait", lang), show_alert=True)
    db.set_codex(vid, status="code", code=code)
    await render(call, t("cx_number", lang, number=v["number"]) + "\n\n" + t("cx_code", lang, code=html.escape(code)),
                 active_kb(db.codex(vid), lang))
    await call.answer()


@router.callback_query(F.data.startswith("cx:ok:"))
async def cb_confirm(call: CallbackQuery, lang: str, bot: Bot):
    vid = int(call.data.split(":")[2])
    v = _own(call, vid, ("code",))
    if not v:
        return await call.answer(t("order_bad", lang), show_alert=True)
    db.set_codex(vid, status="done")
    await api.finish(v["act_id"])
    await render(call, t("cx_done", lang), kb([menu_row(lang)]))
    await call.answer()
    await ask_review(bot, call.from_user.id)


@router.callback_query(F.data.startswith("cx:cnl:"))
async def cb_cancel_number(call: CallbackQuery, lang: str):
    vid = int(call.data.split(":")[2])
    v = _own(call, vid, ("active",))
    if not v:
        v2 = db.codex(vid)
        return await call.answer(t("cx_code_late" if v2 and v2["status"] == "code" else "order_bad", lang), show_alert=True)
    db.set_codex(vid, status="canceled")
    await api.cancel(v["act_id"])
    db.add_balance(v["user_id"], v["price"])
    await render(call, t("cx_canceled", lang, price=money(v["price"])), kb([menu_row(lang)]))
    await call.answer()


# ======================= админ: чеки =======================
@admin_router.callback_query(F.data.startswith("a:cxok:") | F.data.startswith("a:cxno:"))
async def cb_cx_receipt(call: CallbackQuery, bot: Bot):
    _, op, vid = call.data.split(":")
    v = db.codex(int(vid))
    if not v or v["status"] != "pending":
        await mark_admin_msg(call, "ℹ️ Уже обработана")
        return await call.answer("Заявка уже обработана", show_alert=True)
    who = html.escape(call.from_user.first_name)
    if op == "cxok":
        db.set_codex(v["id"], status="paid")
        db.add_deposited(v["user_id"], v["price"])
        await call.answer("Одобрено, выдаю номер…")
        ok = await issue_number(bot, v["id"])
        await mark_admin_msg(call, f"✅ Одобрено, {'номер выдан' if ok else 'номер не получен — деньги на балансе'} ({who})")
    else:
        db.set_codex(v["id"], status="rejected")
        u = db.get_user(v["user_id"])
        lang = u["lang"] if u else "ru"
        await safe_send(bot, v["user_id"], t("cx_rejected", lang, vid=v["id"]),
                        kb([[btn("support", lang, "sup")]]))
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")


# ======================= админ: настройки раздела =======================
CX_FIELDS = {
    "cx_api_url": ("🌐 Адрес API", "Отправьте адрес API сервиса номеров (протокол SMS-Activate), например:\n"
                                  "<code>https://api.sms-activate.ae/stubs/handler_api.php</code>"),
    "cx_api_key": ("🔑 API-ключ", "Отправьте API-ключ из личного кабинета сервиса номеров.\n"
                                 "Сообщение с ключом бот сразу удалит из чата."),
    "cx_service": ("🧩 Код сервиса", "Отправьте код сервиса для Codex/OpenAI в вашем сервисе номеров "
                                    "(в SMS-Activate это <code>dr</code>):"),
    "cx_country": ("🇺🇸 Код страны", "Отправьте код страны США в вашем сервисе номеров "
                                    "(в SMS-Activate это <code>187</code>). Бот всё равно выдаёт только номера +1."),
    "cx_price": ("💰 Цена, ₽", "Отправьте цену верификации в рублях (например 40):"),
    "cx_stars": ("⭐ Цена, звёзды", "Отправьте цену верификации в звёздах (например 20):"),
}


async def cx_admin_view(target, prefix=""):
    on = codex_on()
    key = api.opt("cx_api_key")
    masked = (key[:4] + "…" + key[-3:]) if len(key) > 8 else ("задан" if key else "—")
    text = (f"{prefix}🔐 <b>Верификация Codex</b>\n\n"
            f"Кнопка в меню: <b>{'включена ✅' if on else 'выключена ⛔'}</b>\n"
            f"API номеров: <b>{'подключено ✅' if api.configured() else 'не подключено ⚠️'}</b>\n"
            f"Цена: <b>{money(cx_price())}</b> / <b>{cx_stars()} ⭐</b>\n\n"
            f"🌐 Адрес API: <code>{html.escape(api.opt('cx_api_url') or '—')}</code>\n"
            f"🔑 Ключ: <code>{html.escape(masked)}</code>\n"
            f"🧩 Сервис: <code>{html.escape(api.opt('cx_service'))}</code> · 🇺🇸 Страна: <code>{html.escape(api.opt('cx_country'))}</code>\n\n"
            "<i>Подходит любой сервис номеров с протоколом SMS-Activate (handler_api.php). "
            "Пока API не подключено, покупатели видят «временно недоступна» и оплатить не могут.</i>")
    rows = [[B("⛔ Выключить кнопку" if on else "✅ Включить кнопку", "a:cxon", style="danger" if on else "success")]]
    for k, (title, _) in CX_FIELDS.items():
        rows.append([B(title, f"a:cxs:{k}")])
    rows.append([B("💰 Баланс сервиса номеров", "a:cxbal", style="primary")])
    rows.append(back())
    await render(target, text, kb(rows))


@admin_router.callback_query(F.data == "a:cx")
async def cb_cx_admin(call: CallbackQuery):
    await cx_admin_view(call)
    await call.answer()


@admin_router.callback_query(F.data == "a:cxon")
async def cb_cx_toggle(call: CallbackQuery):
    db.set_setting("cx_on", "0" if codex_on() else "1")
    await cx_admin_view(call)
    await call.answer()


@admin_router.callback_query(F.data == "a:cxbal")
async def cb_cx_balance(call: CallbackQuery):
    try:
        bal = await api.balance()
    except api.NumError as e:
        return await call.answer(f"❌ {e}"[:190], show_alert=True)
    await call.answer(f"💰 Баланс сервиса номеров: {bal}", show_alert=True)


@admin_router.callback_query(F.data.startswith("a:cxs:"))
async def cb_cx_set(call: CallbackQuery, state: FSMContext):
    key = call.data[6:]
    await ask(call, state, "cxs", CX_FIELDS[key][1], cancel="a:cx", key=key)


@inp("cxs")
async def i_cx_set(m, state, d, txt, bot):
    key = d["key"]
    if key == "cx_api_key":
        try:
            await m.delete()  # ключ — секрет
        except Exception:
            pass
    if not txt:
        return await m.answer("Отправьте значение текстом:")
    if key in ("cx_price", "cx_stars"):
        v = parse_amount(txt)
        if v is None or v <= 0:
            return await m.answer("Отправьте число больше нуля:")
        txt = str(int(v) if key == "cx_stars" or v == int(v) else v)
    elif key == "cx_api_url" and not txt.startswith(("http://", "https://")):
        return await m.answer("Адрес должен начинаться с https://")
    db.set_setting(key, txt)
    await state.clear()
    await cx_admin_view(m, "✅ Сохранено.\n\n")
