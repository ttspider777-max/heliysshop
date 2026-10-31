"""Оплата криптовалютой: CryptoBot (Crypto Pay API) и xRocket (Rocket Pay).

Ключи вставляет админ: админ-панель → 💎 Криптооплата. Они хранятся в базе бота (не в коде и не на GitHub).
CryptoBot выставляет счёт сразу в рублях (покупатель выбирает монету сам). xRocket — в USDT по курсу из CryptoBot
(или по курсу, который задал админ, если CryptoBot не подключён).
Вебхуки не нужны: фоновая задача раз в 20 секунд проверяет неоплаченные счета, плюс кнопка «Проверить».
"""
import asyncio
import html
import logging
import time

import aiohttp

import db
from texts import money, t

log = logging.getLogger(__name__)

SERVICES = {"cryptobot": "CryptoBot", "xrocket": "xRocket"}
SHORT = {"cb": "cryptobot", "xr": "xrocket"}
INVOICE_TTL = 3600
CB_URL = "https://pay.crypt.bot/api/"
XR_URL = "https://pay.xrocket.tg/"

_rate = {"value": 0.0, "ts": 0.0}


class CryptoError(Exception):
    pass


# ---------- настройки ----------
def token(method):
    return db.get_setting(f"crypto_token:{method}") or ""


def enabled(method):
    """Способ доступен покупателям: ключ вставлен и админ не выключил его."""
    return bool(token(method)) and db.get_setting(f"crypto_on:{method}", "1") == "1"


def methods():
    return [m for m in SERVICES if enabled(m)]


def manual_rate():
    try:
        return float(db.get_setting("crypto_usdt_rate") or 0)
    except ValueError:
        return 0.0


# ---------- запросы к сервисам ----------
async def _request(method, url, headers, **kw):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.request(method, url, headers=headers, **kw) as r:
                return await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise CryptoError("Платёжный сервис не отвечает, попробуйте позже") from e


async def _cb(api_method, tok=None, **params):
    data = await _request("POST", CB_URL + api_method, {"Crypto-Pay-API-Token": tok or token("cryptobot")}, json=params)
    if not isinstance(data, dict) or not data.get("ok"):
        log.warning("CryptoBot %s: %s", api_method, data)
        err = (data or {}).get("error") if isinstance(data, dict) else None
        raise CryptoError(f"CryptoBot: {err.get('name') if isinstance(err, dict) else err or 'ошибка'}")
    return data["result"]


async def _xr(http, path, tok=None, **kw):
    data = await _request(http, XR_URL + path, {"Rocket-Pay-Key": tok or token("xrocket")}, **kw)
    if not isinstance(data, dict) or not data.get("success"):
        log.warning("xRocket %s: %s", path, data)
        raise CryptoError(f"xRocket: {(data or {}).get('message') if isinstance(data, dict) else 'ошибка'}")
    return data["data"]


async def usdt_rub():
    """Сколько рублей стоит 1 USDT: курс CryptoBot (кэш 10 минут) или заданный админом."""
    if token("cryptobot") and time.time() - _rate["ts"] > 600:
        try:
            for r in await _cb("getExchangeRates"):
                if r.get("source") == "USDT" and r.get("target") == "RUB" and r.get("is_valid", True):
                    _rate.update(value=float(r["rate"]), ts=time.time())
                    break
        except CryptoError:
            pass
    rate = _rate["value"] or manual_rate()
    if not rate:
        raise CryptoError("Нет курса USDT: подключите CryptoBot или задайте курс в админке")
    return rate


async def test(method, tok):
    """Проверка ключа из админки -> описание приложения."""
    if method == "cryptobot":
        me = await _cb("getMe", tok)
        return f"приложение «{html.escape(str(me.get('name', '')))}» (id {me.get('app_id')})"
    info = await _xr("GET", "app/info", tok)
    return f"приложение «{html.escape(str(info.get('name', '')))}»"


# ---------- счета ----------
def invoice(iid):
    return db.q1("SELECT * FROM crypto_invoices WHERE id=?", (iid,))


async def create(kind, ref_id, uid, method, rub, desc):
    """Выставляет счёт. -> (запись счёта, доп. строка для покупателя, например «≈ 1.05 USDT»)."""
    if not enabled(method):
        raise CryptoError("Способ оплаты выключен")
    iid = db.x("INSERT INTO crypto_invoices(kind, ref_id, user_id, method, amount, status, created) "
               "VALUES (?,?,?,?,?, 'pending', ?)", (kind, ref_id, uid, method, rub, int(time.time())))
    payload = f"{kind}:{ref_id}:{iid}"
    extra = ""
    try:
        if method == "cryptobot":
            inv = await _cb("createInvoice", currency_type="fiat", fiat="RUB", amount=f"{rub:.2f}",
                            description=desc[:1024], payload=payload, expires_in=INVOICE_TTL)
            ext_id, url = str(inv["invoice_id"]), inv.get("bot_invoice_url") or inv.get("pay_url")
        else:
            usdt = round(rub / await usdt_rub() + 0.004, 2)   # округляем вверх до цента
            inv = await _xr("POST", "tg-invoices", json={
                "amount": usdt, "currency": "USDT", "numPayments": 1, "description": desc[:1000],
                "payload": payload, "expiredIn": INVOICE_TTL})
            ext_id, url = str(inv["id"]), inv["link"]
            extra = f" (≈ {usdt:g} USDT)"
    except Exception:
        db.x("DELETE FROM crypto_invoices WHERE id=?", (iid,))
        raise
    db.x("UPDATE crypto_invoices SET ext_id=?, url=? WHERE id=?", (ext_id, url, iid))
    return invoice(iid), extra


async def _paid_remote(inv):
    if inv["method"] == "cryptobot":
        res = await _cb("getInvoices", invoice_ids=inv["ext_id"])
        items = res.get("items", []) if isinstance(res, dict) else res
        return bool(items) and items[0].get("status") == "paid"
    data = await _xr("GET", f"tg-invoices/{inv['ext_id']}")
    return data.get("status") == "paid"


async def settle(bot, iid):
    """Счёт оплачен: проводим заказ или пополнение ровно один раз."""
    cur = db.conn.execute("UPDATE crypto_invoices SET status='paid' WHERE id=? AND status IN ('pending','expired')",
                          (iid,))
    db.conn.commit()
    if cur.rowcount == 0:   # уже проведён (или такого счёта нет)
        return False
    inv = invoice(iid)
    from services import fulfill, to_admins, user_link
    from ui import kb, menu_row
    service = SERVICES[inv["method"]]
    u = db.get_user(inv["user_id"])
    lang = u["lang"] if u else "ru"
    if inv["kind"] == "order":
        o = db.order(inv["ref_id"])
        if not o or o["status"] not in ("wait_pay", "canceled"):
            db.add_balance(inv["user_id"], inv["amount"])
            await to_admins(bot, f"⚠️ Пришла оплата {service} {money(inv['amount'])} за заказ #{inv['ref_id']}, но он "
                                 f"уже обработан — деньги зачислены покупателю на баланс.\n👤 {user_link(u)}")
            return True
        db.set_order(o["id"], status="paid", receipt=f"{inv['method']}:{inv['ext_id']}")
        db.add_deposited(o["user_id"], o["price"])
        try:
            await bot.send_message(o["user_id"], t("crypto_paid", lang, oid=o["id"]), reply_markup=kb([menu_row(lang)]))
        except Exception:
            pass
        res = await fulfill(bot, o["id"])
        await to_admins(bot, f"💎 <b>Оплата {service} — заказ #{o['id']}</b>\n\n👤 {user_link(u)}\n"
                             f"📦 {html.escape(o['product_name'])}\n💰 {money(o['price'])}\n"
                             f"📍 {'выдан' if res == 'done' else 'ждёт ручной выдачи' if res == 'manual' else 'товара нет — деньги на балансе'}")
    else:
        from handlers.topup import complete
        tp = db.topup(inv["ref_id"])
        if not tp or tp["status"] not in ("wait_pay", "canceled"):
            db.add_balance(inv["user_id"], inv["amount"])
            await to_admins(bot, f"⚠️ Пришла оплата {service} {money(inv['amount'])} за пополнение #{inv['ref_id']}, "
                                 f"но оно уже обработано — деньги зачислены на баланс.\n👤 {user_link(u)}")
            return True
        db.set_topup(tp["id"], receipt=f"{inv['method']}:{inv['ext_id']}")
        await complete(bot, tp["id"])
        await to_admins(bot, f"💎 <b>Пополнение #{tp['id']} через {service}</b>: {money(tp['amount'])}\n👤 {user_link(u)}")
    return True


async def check(bot, iid, uid):
    """Кнопка «Проверить оплату». -> paid / pending / expired / not_found."""
    inv = invoice(iid)
    if not inv or inv["user_id"] != uid:
        return "not_found"
    if inv["status"] == "pending":
        try:
            if await _paid_remote(inv):
                await settle(bot, iid)
                return "paid"
        except CryptoError:
            pass
    return invoice(iid)["status"]


def _expire_old():
    """Неоплаченные за час счета закрываем, заказы отменяем (промокод возвращается)."""
    old = db.q("SELECT * FROM crypto_invoices WHERE status='pending' AND created < ?",
               (int(time.time()) - INVOICE_TTL - 120,))
    for inv in old:
        db.x("UPDATE crypto_invoices SET status='expired' WHERE id=?", (inv["id"],))
        if inv["kind"] == "order":
            o = db.order(inv["ref_id"])
            if o and o["status"] == "wait_pay" and o["method"] == inv["method"]:
                db.set_order(o["id"], status="canceled")
                db.restore_promo(o)
        else:
            tp = db.topup(inv["ref_id"])
            if tp and tp["status"] == "wait_pay" and tp["method"] == inv["method"]:
                db.set_topup(tp["id"], status="canceled")


async def checker(bot):
    """Фоновая проверка: оплатили ли открытые счета (вебхуки не используются)."""
    while True:
        await asyncio.sleep(20)
        try:
            _expire_old()
            # недавно истёкшие тоже проверяем — вдруг оплатили в последнюю минуту
            for inv in db.q("SELECT * FROM crypto_invoices WHERE status='pending' OR "
                            "(status='expired' AND created > ?)", (int(time.time()) - INVOICE_TTL - 900,)):
                if not token(inv["method"]):
                    continue
                try:
                    if await _paid_remote(inv):
                        await settle(bot, inv["id"])
                except CryptoError:
                    pass
                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("crypto checker")
