"""Оплата звёздами Telegram (XTR): товары магазина (payload «o:ID»), верификация Codex («cx:ID»)
и пополнение баланса («tu:ID»).
Звёзды приходят владельцу того бота, в котором оплатили (у ботов клиентов — самому клиенту)."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery

import db
from handlers.shop import check_buyable
from services import fulfill, to_admins, user_link
from texts import money, t
from ui import kb, menu_row

router = Router()


def _parse(payload):
    kind, _, ident = (payload or "").partition(":")
    return kind, int(ident) if ident.isdigit() else 0


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    """Последняя проверка перед списанием звёзд: заказ ещё ждёт оплату и товар есть."""
    kind, ident = _parse(q.invoice_payload)
    u = db.get_user(q.from_user.id)
    lang = u["lang"] if u else "ru"
    ok = False
    if kind == "o":
        o = db.order(ident)
        ok = bool(o and o["user_id"] == q.from_user.id and o["status"] == "wait_pay" and o["method"] == "stars"
                  and check_buyable(db.product(o["product_id"]), o["qty"] or 1) is None)
    elif kind == "cx":
        v = db.codex(ident)
        ok = bool(v and v["user_id"] == q.from_user.id and v["status"] == "wait_pay" and v["method"] == "stars")
    elif kind == "tu":
        tp = db.topup(ident)
        ok = bool(tp and tp["user_id"] == q.from_user.id and tp["status"] == "wait_pay" and tp["method"] == "stars")
    if ok:
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message=t("stars_fail", lang))


@router.message(F.successful_payment)
async def paid(m: Message, lang: str, bot: Bot):
    sp = m.successful_payment
    kind, ident = _parse(sp.invoice_payload)
    charge = sp.telegram_payment_charge_id
    if kind == "o":
        o = db.order(ident)
        if not o or o["status"] != "wait_pay":
            logging.warning("звёзды за заказ %s пришли, но заказ уже %s", ident, o["status"] if o else "удалён")
            return await to_admins(bot, f"⚠️ Пришла оплата {sp.total_amount}⭐ за заказ #{ident}, но он уже обработан. "
                                        f"Проверьте вручную. Платёж: <code>{html.escape(charge)}</code>")
        db.set_order(ident, status="paid", receipt=f"stars:{charge}")
        db.add_deposited(o["user_id"], o["price"])
        await m.answer(t("stars_paid", lang, oid=ident), reply_markup=kb([menu_row(lang)]))
        res = await fulfill(bot, ident)
        await to_admins(bot, f"⭐ <b>Оплата звёздами — заказ #{ident}</b>\n\n👤 {user_link(db.get_user(o['user_id']))}\n"
                             f"📦 {html.escape(o['product_name'])}\n💰 {sp.total_amount} ⭐ ({money(o['price'])})\n"
                             f"📍 {'выдан' if res == 'done' else 'ждёт ручной выдачи' if res == 'manual' else 'товара нет — деньги на балансе'}")
    elif kind == "tu":
        from handlers.topup import complete
        tp = db.topup(ident)
        if not tp or tp["status"] != "wait_pay":
            return await to_admins(bot, f"⚠️ Пришла оплата {sp.total_amount}⭐ за пополнение #{ident}, но оно уже обработано. "
                                        f"Платёж: <code>{html.escape(charge)}</code>")
        db.set_topup(ident, receipt=f"stars:{charge}")
        await complete(bot, ident)
        await to_admins(bot, f"⭐ <b>Пополнение #{ident} звёздами</b>: {sp.total_amount} ⭐ → {money(tp['amount'])}\n"
                             f"👤 {user_link(db.get_user(tp['user_id']))}")
    elif kind == "cx":
        from handlers.codex import issue_number
        v = db.codex(ident)
        if not v or v["status"] != "wait_pay":
            return await to_admins(bot, f"⚠️ Пришла оплата {sp.total_amount}⭐ за верификацию #{ident}, но она уже обработана. "
                                        f"Платёж: <code>{html.escape(charge)}</code>")
        db.set_codex(ident, status="paid", receipt=f"stars:{charge}")
        db.add_deposited(v["user_id"], v["price"])
        await to_admins(bot, f"⭐ <b>Верификация Codex #{ident} оплачена звёздами</b> ({sp.total_amount} ⭐)\n"
                             f"👤 {user_link(db.get_user(v['user_id']))}")
        await issue_number(bot, ident)
