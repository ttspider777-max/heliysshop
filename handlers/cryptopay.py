"""Оплата криптовалютой в боте (CryptoBot, xRocket): заказ товара, пополнение баланса, проверка оплаты
и раздел админки «💎 Криптооплата» (ключи, вкл/выкл, курс USDT)."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import crypto
import db
from handlers.admin import B, ask, back, inp, parse_amount, router as admin_router
from handlers.shop import check_buyable, min_qty, stars_ok, total_price  # noqa: F401
from texts import money, t
from ui import btn, kb, menu_row, render

router = Router()


def crypto_buttons(lang, cb_prefix):
    """Кнопки «💎 CryptoBot» / «🚀 xRocket» для доступных способов (cb_prefix + ':cb' / ':xr')."""
    row = []
    for short, method in crypto.SHORT.items():
        if crypto.enabled(method):
            row.append(btn(f"pay_{method}", lang, f"{cb_prefix}:{short}"))
    return row


def invoice_kb(lang, inv, cancel_cb):
    return kb([
        [btn("crypto_pay", lang, url=inv["url"])],
        [btn("crypto_check", lang, f"cc:{inv['id']}")],
        [btn("cancel", lang, cancel_cb)],
    ])


# ======================= заказ товара =======================
@router.callback_query(F.data.startswith("pc:"))
async def cb_pay_crypto(call: CallbackQuery, lang: str):
    _, pid, n, short = (call.data.split(":") + ["", "", "", ""])[:4]
    method = crypto.SHORT.get(short)
    if not method or not crypto.enabled(method):
        return await call.answer(t("crypto_off", lang), show_alert=True)
    qty = max(int(n or 1), 1)
    p = db.product(int(pid))
    err = check_buyable(p, qty)
    if err:
        return await call.answer(t(err, lang, min=min_qty(p)) if p else t(err, lang), show_alert=True)
    db.release_promo_orders(call.from_user.id)
    u = db.get_user(call.from_user.id)
    price, _, code = total_price(u, p, qty)
    oid = db.create_order(u["id"], p, price, method, "wait_pay", code, qty)
    name = p["name"] + (f" × {qty}" if qty > 1 else "")
    try:
        inv, extra = await crypto.create("order", oid, u["id"], method, price, t("stars_desc", lang, oid=oid, name=name))
    except crypto.CryptoError as e:
        logging.warning("crypto invoice for order %s: %s", oid, e)
        db.set_order(oid, status="canceled")
        return await call.answer(t("crypto_error", lang), show_alert=True)
    if code:
        db.consume_promo(u["id"])
    await render(call, t("crypto_order", lang, oid=oid, name=html.escape(name), price=money(price), extra=extra,
                         service=crypto.SERVICES[method]), invoice_kb(lang, inv, f"oc:{oid}"))
    await call.answer()


# ======================= пополнение =======================
@router.callback_query(F.data.startswith("tc:"))
async def cb_topup_crypto(call: CallbackQuery, lang: str):
    from handlers.topup import valid_amount
    import appcfg
    _, amount, short = (call.data.split(":") + ["", "", ""])[:3]
    method = crypto.SHORT.get(short)
    v = parse_amount(amount)
    if not method or not crypto.enabled(method):
        return await call.answer(t("crypto_off", lang), show_alert=True)
    if not valid_amount(v):
        return await call.answer(t("topup_bad", lang, min=money(appcfg.topup_min())), show_alert=True)
    inv, extra, tid = await start_topup(call.from_user.id, v, method, lang)
    if not inv:
        return await call.answer(t("crypto_error", lang), show_alert=True)
    await render(call, t("crypto_topup", lang, tid=tid, amount=money(v), extra=extra, service=crypto.SERVICES[method]),
                 invoice_kb(lang, inv, "topup"))
    await call.answer()


async def start_topup(uid, amount, method, lang):
    """Создаёт пополнение и счёт (используется и мини-приложением). -> (счёт, доп. строка, id пополнения)."""
    tid = db.create_topup(uid, amount, method)
    try:
        inv, extra = await crypto.create("topup", tid, uid, method, amount,
                                         t("topup_stars_desc", lang, amount=money(amount)))
    except crypto.CryptoError as e:
        logging.warning("crypto invoice for topup %s: %s", tid, e)
        db.set_topup(tid, status="canceled")
        return None, "", tid
    return inv, extra, tid


# ======================= проверка оплаты =======================
@router.callback_query(F.data.startswith("cc:"))
async def cb_check(call: CallbackQuery, lang: str, bot: Bot):
    res = await crypto.check(bot, int(call.data.split(":")[1]), call.from_user.id)
    if res == "paid":
        await call.answer("✅")
        try:
            await call.message.edit_reply_markup(reply_markup=kb([menu_row(lang)]))
        except Exception:
            pass
    elif res == "expired":
        await call.answer(t("crypto_expired", lang, iid=call.data.split(":")[1]), show_alert=True)
    else:
        await call.answer(t("crypto_wait", lang), show_alert=True)


# ======================= админка: 💎 Криптооплата =======================
def _mask(tok):
    return f"{tok[:6]}…{tok[-4:]}" if len(tok) > 12 else "задан"


def admin_text():
    lines = ["💎 <b>Криптооплата</b>\n",
             "Покупатели смогут оплачивать товары и пополнять баланс через CryptoBot и xRocket. "
             "Деньги приходят на баланс вашего приложения в этих ботах. Ключи хранятся только в базе бота.\n"]
    for m, name in crypto.SERVICES.items():
        tok = crypto.token(m)
        state = ("🟢 включён" if crypto.enabled(m) else "⏸ выключен") if tok else "⚪️ не подключён"
        lines.append(f"<b>{name}</b>: {state}" + (f" · ключ {_mask(tok)}" if tok else ""))
    rate = crypto.manual_rate()
    lines.append(f"\n💱 Курс USDT для xRocket: {'из CryptoBot' if crypto.token('cryptobot') else ''}"
                 f"{' · запасной ' + money(rate) if rate else '' if crypto.token('cryptobot') else 'не задан'}")
    lines.append("\nГде взять ключи:\n• CryptoBot: @CryptoBot → Crypto Pay → Create App → API Token\n"
                 "• xRocket: @xRocket → Rocket Pay → Создать приложение → API-ключ")
    return "\n".join(lines)


def admin_kb():
    rows = []
    for m, name in crypto.SERVICES.items():
        if crypto.token(m):
            on = crypto.enabled(m)
            rows.append([B(f"{'⏸ Выключить' if on else '▶️ Включить'} {name}", f"a:cryon:{m}",
                           style=None if on else "success"),
                         B("🔑 Заменить ключ", f"a:cryt:{m}")])
            rows.append([B(f"🗑 Удалить ключ {name}", f"a:cryd:{m}", style="danger")])
        else:
            rows.append([B(f"🔑 Подключить {name}", f"a:cryt:{m}", style="primary")])
    rows.append([B("💱 Запасной курс USDT", "a:cryrate")])
    rows.append(back())
    return kb(rows)


@admin_router.callback_query(F.data == "a:cry")
async def cb_admin(call: CallbackQuery):
    await render(call, admin_text(), admin_kb())
    await call.answer()


@admin_router.callback_query(F.data.startswith("a:cryt:"))
async def cb_token(call: CallbackQuery, state: FSMContext):
    m = call.data.split(":")[2]
    await ask(call, state, "crytok", f"🔑 Отправьте API-ключ <b>{crypto.SERVICES[m]}</b>.\n\n"
                                     "Бот проверит его и сразу удалит ваше сообщение с ключом из чата.",
              cancel="a:cry", method=m)


@inp("crytok")
async def i_token(m, state, d, txt, bot):
    method = d["method"]
    try:
        await m.delete()   # ключ не должен оставаться в переписке
    except Exception:
        pass
    if not txt or " " in txt or len(txt) > 600:
        return await m.answer("Это не похоже на ключ. Отправьте ключ одной строкой:")
    try:
        info = await crypto.test(method, txt)
    except crypto.CryptoError as e:
        return await m.answer(f"❌ Ключ не подошёл: {html.escape(str(e))}\n\nОтправьте другой ключ или нажмите «Отмена».",
                              reply_markup=kb([[B("❌ Отмена", "a:cry", style="danger")]]))
    db.set_setting(f"crypto_token:{method}", txt)
    db.set_setting(f"crypto_on:{method}", "1")
    await state.clear()
    await m.answer(f"✅ {crypto.SERVICES[method]} подключён: {info}\n\n" + admin_text(), reply_markup=admin_kb())


@admin_router.callback_query(F.data.startswith("a:cryon:"))
async def cb_toggle(call: CallbackQuery):
    m = call.data.split(":")[2]
    db.set_setting(f"crypto_on:{m}", "0" if crypto.enabled(m) else "1")
    await render(call, admin_text(), admin_kb())
    await call.answer()


@admin_router.callback_query(F.data.startswith("a:cryd:"))
async def cb_delete(call: CallbackQuery):
    m = call.data.split(":")[2]
    db.set_setting(f"crypto_token:{m}", None)
    await render(call, admin_text(), admin_kb())
    await call.answer("Ключ удалён")


@admin_router.callback_query(F.data == "a:cryrate")
async def cb_rate(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "cryrate", "💱 Отправьте курс: сколько рублей стоит 1 USDT (например <code>95</code>).\n\n"
                                      "Нужен для xRocket, только если CryptoBot не подключён (иначе курс берётся из "
                                      "CryptoBot автоматически). <code>0</code> — убрать.", cancel="a:cry")


@inp("cryrate")
async def i_rate(m, state, d, txt, bot):
    v = parse_amount(txt)
    if v is None or v < 0 or v > 100000:
        return await m.answer("Отправьте число, например <code>95</code>:")
    db.set_setting("crypto_usdt_rate", str(v) if v else None)
    await state.clear()
    await m.answer(admin_text(), reply_markup=admin_kb())
