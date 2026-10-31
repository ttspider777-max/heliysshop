"""«💳 Пополнить баланс»: сумма → СБП (чек админу) или звёзды Telegram.

Пополнения засчитываются в статус покупателя (users.deposited). Настройки: админ-панель → 🎨 Мини-приложение →
💳 Пополнение (минимум, быстрые суммы). Те же функции вызывает мини-приложение (web.py).
"""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

import admins
import appcfg
import config
import db
from handlers.admin import mark_admin_msg, parse_amount, router as admin_router
from services import safe_send, user_link
from texts import bt, money, t
from ui import btn, kb, menu_row, raw_btn, render

router = Router()
MAX_TOPUP = 500_000


class TopSt(StatesGroup):
    amount = State()
    receipt = State()


def stars_for(rub):
    from handlers.shop import stars_for as _sf
    return _sf(rub)


# ======================= выбор суммы =======================
async def topup_view(target, lang, uid):
    u = db.get_user(uid)
    rows, row = [], []
    for a in appcfg.topup_amounts():
        row.append(raw_btn(money(a), f"tu:a:{a}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows += [[btn("topup_custom", lang, "tu:c")], [btn("back", lang, "profile"), btn("main_menu", lang, "menu")]]
    await render(target, t("topup_title", lang, balance=money(u["balance"]), min=money(appcfg.topup_min())), kb(rows))


@router.callback_query(F.data == "topup")
async def cb_topup(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(None)
    await topup_view(call, lang, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "tu:c")
async def cb_custom(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(TopSt.amount)
    await render(call, t("topup_custom", lang, min=money(appcfg.topup_min())), kb([[btn("cancel", lang, "topup")]]))
    await call.answer()


def valid_amount(v):
    return v is not None and appcfg.topup_min() <= v <= MAX_TOPUP


@router.message(TopSt.amount, F.text)
async def msg_custom(m: Message, state: FSMContext, lang: str):
    v = parse_amount(m.text.strip().replace("₽", ""))
    if not valid_amount(v):
        return await m.answer(t("topup_bad", lang, min=money(appcfg.topup_min())))
    await state.set_state(None)
    await method_view(m, lang, v)


def method_kb(lang, amount):
    a = int(amount) if amount == int(amount) else amount
    stars = btn("pay_stars", lang, f"tu:st:{a}")
    if stars:
        stars.text = f"{stars.text} · {stars_for(amount)} ⭐"
    from handlers.cryptopay import crypto_buttons
    return kb([
        [btn("pay_sbp", lang, f"tu:sbp:{a}")],
        [stars],
        crypto_buttons(lang, f"tc:{a}"),
        [btn("back", lang, "topup")],
    ])


async def method_view(target, lang, amount):
    await render(target, t("topup_method", lang, amount=money(amount)), method_kb(lang, amount))


@router.callback_query(F.data.startswith("tu:a:"))
async def cb_amount(call: CallbackQuery, lang: str):
    v = parse_amount(call.data[5:])
    if not valid_amount(v):
        return await call.answer(t("topup_bad", lang, min=money(appcfg.topup_min())), show_alert=True)
    await method_view(call, lang, v)
    await call.answer()


# ======================= СБП =======================
def sbp_message(lang, tid, amount):
    text = t("topup_sbp", lang, tid=tid, amount=money(amount), details=db.get_setting("sbp_details", config.SBP_DETAILS))
    markup = kb([[btn("paid", lang, f"tu:paid:{tid}")], [btn("cancel", lang, f"tu:x:{tid}")]])
    return text, markup


async def start_sbp(bot: Bot, uid, amount, lang):
    """Создаёт заявку и шлёт реквизиты в чат (используется и мини-приложением)."""
    db.x("UPDATE topups SET status='canceled' WHERE user_id=? AND status='wait_pay'", (uid,))
    tid = db.create_topup(uid, amount, "sbp")
    text, markup = sbp_message(lang, tid, amount)
    await bot.send_message(uid, text, reply_markup=markup)
    return tid


@router.callback_query(F.data.startswith("tu:sbp:"))
async def cb_sbp(call: CallbackQuery, lang: str):
    v = parse_amount(call.data[7:])
    if not valid_amount(v):
        return await call.answer(t("topup_bad", lang, min=money(appcfg.topup_min())), show_alert=True)
    db.x("UPDATE topups SET status='canceled' WHERE user_id=? AND status='wait_pay'", (call.from_user.id,))
    tid = db.create_topup(call.from_user.id, v, "sbp")
    text, markup = sbp_message(lang, tid, v)
    await render(call, text, markup)
    await call.answer()


@router.callback_query(F.data.startswith("tu:paid:"))
async def cb_paid(call: CallbackQuery, state: FSMContext, lang: str):
    tid = int(call.data.split(":")[2])
    tp = db.topup(tid)
    if not tp or tp["user_id"] != call.from_user.id or tp["status"] != "wait_pay":
        return await call.answer(t("order_bad", lang), show_alert=True)
    await state.set_state(TopSt.receipt)
    await state.update_data(tu_tid=tid)
    await render(call, t("send_receipt", lang), kb([[btn("cancel", lang, f"tu:x:{tid}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("tu:x:"))
async def cb_cancel(call: CallbackQuery, state: FSMContext, lang: str):
    tid = int(call.data.split(":")[2])
    tp = db.topup(tid)
    if tp and tp["user_id"] == call.from_user.id and tp["status"] == "wait_pay":
        db.set_topup(tid, status="canceled")
    await state.set_state(None)
    await call.answer(t("order_canceled", lang))
    await topup_view(call, lang, call.from_user.id)


@router.message(TopSt.receipt, F.photo | F.document)
async def msg_receipt(m: Message, state: FSMContext, lang: str, bot: Bot):
    tid = (await state.get_data()).get("tu_tid")
    await state.set_state(None)
    tp = db.topup(tid) if tid else None
    if not tp or tp["status"] != "wait_pay":
        tp = db.topup_wait_pay(m.from_user.id)
    if not tp:
        return await m.answer(t("order_bad", lang), reply_markup=kb([menu_row(lang)]))
    await send_receipt(m, tp, lang, bot)


@router.message(TopSt.receipt)
async def msg_receipt_wrong(m: Message, lang: str):
    await m.answer(t("need_receipt", lang))


def _topup_receipt_expected(m: Message):
    return bool(m.from_user) and db.latest_wait_kind(m.from_user.id) == "topup"


@router.message(StateFilter(None), F.photo | F.document, _topup_receipt_expected)
async def msg_receipt_fallback(m: Message, lang: str, bot: Bot):
    await send_receipt(m, db.topup_wait_pay(m.from_user.id), lang, bot)


async def send_receipt(m: Message, tp, lang: str, bot: Bot):
    tid = tp["id"]
    if m.photo:
        file_id, is_photo = m.photo[-1].file_id, True
    else:
        file_id, is_photo = m.document.file_id, False
    db.set_topup(tid, status="pending", receipt=file_id)
    u = db.get_user(m.from_user.id)
    caption = (f"💳 <b>Пополнение баланса — заявка #{tid}</b>\n\n👤 {user_link(u)}\n"
               f"💰 Сумма: <b>{money(tp['amount'])}</b>\n💼 Сейчас на балансе: {money(u['balance'])}")
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Зачислить", callback_data=f"a:tuok:{tid}", style="success"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"a:tuno:{tid}", style="danger"),
    ]])
    for aid in admins.ids():
        try:
            if is_photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception as e:
            logging.warning("не удалось отправить чек пополнения админу %s: %s", aid, e)
    await m.answer(t("topup_receipt_sent", lang), reply_markup=kb([menu_row(lang)]))


# ======================= звёзды =======================
def stars_invoice(lang, tid, amount):
    title = bt("topup", lang).lstrip("💳 ").strip()[:32] or "Top up"
    desc = t("topup_stars_desc", lang, amount=money(amount))[:255]
    return dict(title=title, description=desc, payload=f"tu:{tid}", currency="XTR",
                prices=[LabeledPrice(label=title, amount=stars_for(amount))])


@router.callback_query(F.data.startswith("tu:st:"))
async def cb_stars(call: CallbackQuery, lang: str):
    v = parse_amount(call.data[6:])
    if not valid_amount(v):
        return await call.answer(t("topup_bad", lang, min=money(appcfg.topup_min())), show_alert=True)
    tid = db.create_topup(call.from_user.id, v, "stars")
    await call.message.answer_invoice(**stars_invoice(lang, tid, v))
    await call.answer()


async def stars_link(bot: Bot, uid, amount, lang):
    """Ссылка на счёт в звёздах для мини-приложения (Telegram.WebApp.openInvoice)."""
    tid = db.create_topup(uid, amount, "stars")
    return await bot.create_invoice_link(**stars_invoice(lang, tid, amount))


# ======================= зачисление =======================
async def complete(bot: Bot, tid):
    """Пополнение оплачено: деньги на баланс, засчитываем в статус, сообщаем покупателю."""
    tp = db.topup(tid)
    db.set_topup(tid, status="done")
    db.add_balance(tp["user_id"], tp["amount"])
    db.add_deposited(tp["user_id"], tp["amount"])
    u = db.get_user(tp["user_id"])
    lang = u["lang"] if u else "ru"
    await safe_send(bot, tp["user_id"], t("topup_done", lang, amount=money(tp["amount"]), balance=money(u["balance"])),
                    kb([[btn("profile", lang, "profile")], menu_row(lang)]))


@admin_router.callback_query(F.data.startswith("a:tuok:") | F.data.startswith("a:tuno:"))
async def cb_admin_topup(call: CallbackQuery, bot: Bot):
    _, op, tid = call.data.split(":")
    tp = db.topup(int(tid))
    if not tp or tp["status"] != "pending":
        await mark_admin_msg(call, "ℹ️ Уже обработана")
        return await call.answer("Заявка уже обработана", show_alert=True)
    who = html.escape(call.from_user.first_name)
    if op == "tuok":
        await complete(bot, tp["id"])
        await mark_admin_msg(call, f"✅ Зачислено {money(tp['amount'])} ({who})")
        await call.answer("Зачислено")
    else:
        db.set_topup(tp["id"], status="rejected")
        u = db.get_user(tp["user_id"])
        lang = u["lang"] if u else "ru"
        await safe_send(bot, tp["user_id"], t("topup_rejected", lang, tid=tp["id"]), kb([[btn("support", lang, "sup")]]))
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")
