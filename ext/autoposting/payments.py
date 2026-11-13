"""Пополнение hlx: Telegram Stars, CryptoBot, xRocket."""
import asyncio
import logging
import math
import time

import aiohttp
from aiogram.types import LabeledPrice

import config
import db
from loader import bot

log = logging.getLogger(__name__)

METHODS = {"stars": "Telegram Stars", "cryptobot": "CryptoBot", "xrocket": "xRocket"}
INVOICE_TTL = 3600

_rate = {"value": 0.0, "ts": 0.0}


class PayError(Exception):
    pass


def package(pid):
    return next((p for p in config.PACKAGES if p["id"] == pid), None)


def stars_price(rub) -> int:
    return math.ceil(rub / config.STAR_RATE_RUB)


async def _request(method, url, headers, **kwargs):
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.request(method, url, headers=headers, **kwargs) as r:
                return await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise PayError("Платёжный сервис не отвечает, попробуйте позже") from e


async def _cryptopay(method, **params):
    data = await _request("POST", f"https://pay.crypt.bot/api/{method}",
                          {"Crypto-Pay-API-Token": config.CRYPTOPAY_TOKEN}, json=params)
    if not data.get("ok"):
        log.error("CryptoPay %s: %s", method, data)
        raise PayError("CryptoBot отклонил запрос")
    return data["result"]


async def _xrocket(method, path, **kwargs):
    data = await _request(method, f"https://pay.xrocket.tg/{path}",
                          {"Rocket-Pay-Key": config.XROCKET_TOKEN}, **kwargs)
    if not data.get("success"):
        log.error("xRocket %s: %s", path, data)
        raise PayError("xRocket отклонил запрос")
    return data["data"]


async def usdt_rub() -> float:
    if time.time() - _rate["ts"] > 600:
        for r in await _cryptopay("getExchangeRates"):
            if r["source"] == "USDT" and r["target"] == "RUB" and r.get("is_valid", True):
                _rate.update(value=float(r["rate"]), ts=time.time())
                break
    if not _rate["value"]:
        raise PayError("Не удалось получить курс USDT")
    return _rate["value"]


async def create(user_id, package_id, method) -> dict:
    pkg = package(package_id)
    if not pkg or method not in METHODS:
        raise PayError("Неверный пакет или способ оплаты")
    cur = await db.run("INSERT INTO payments(user_id, method, hlx, rub, created_at) VALUES(?,?,?,?,?)",
                       user_id, method, pkg["hlx"], pkg["rub"], int(time.time()))
    pid = cur.lastrowid
    title = f"{pkg['hlx']} hlx"
    desc = f"Пополнение баланса {config.APP_NAME}: {pkg['hlx']} hlx"
    ext_id = ""
    try:
        if method == "stars":
            url = await bot.create_invoice_link(
                title=title, description=desc, payload=f"pay:{pid}", currency="XTR",
                prices=[LabeledPrice(label=title, amount=stars_price(pkg["rub"]))])
        elif method == "cryptobot":
            inv = await _cryptopay("createInvoice", currency_type="fiat", fiat="RUB", amount=str(pkg["rub"]),
                                   description=desc, payload=f"pay:{pid}", expires_in=INVOICE_TTL)
            ext_id, url = str(inv["invoice_id"]), inv["bot_invoice_url"]
        else:
            amount = round(pkg["rub"] / await usdt_rub(), 2)
            inv = await _xrocket("POST", "tg-invoices", json={
                "amount": amount, "currency": "USDT", "numPayments": 1,
                "description": desc, "payload": f"pay:{pid}", "expiredIn": INVOICE_TTL})
            ext_id, url = str(inv["id"]), inv["link"]
    except Exception:
        await db.run("DELETE FROM payments WHERE id=?", pid)
        raise
    await db.run("UPDATE payments SET ext_id=?, url=? WHERE id=?", ext_id, url, pid)
    return {"payment_id": pid, "url": url, "method": method}


async def credit(payment_id) -> bool:
    """Зачисляет оплату ровно один раз."""
    cur = await db.run("UPDATE payments SET status='paid' WHERE id=? AND status IN ('pending','expired')", payment_id)
    if cur.rowcount == 0:
        return False
    p = await db.one("SELECT * FROM payments WHERE id=?", payment_id)
    await db.add_balance(p["user_id"], p["hlx"], "topup", f"Пополнение · {METHODS[p['method']]}")
    user = await db.get_user(p["user_id"])
    bonus = p["hlx"] * config.REF_PERCENT // 100
    if user and user["referrer_id"] and bonus:
        await db.add_balance(user["referrer_id"], bonus, "ref", "Процент с пополнения реферала")
        await db.run("UPDATE users SET ref_earned = ref_earned + ? WHERE id=?", bonus, user["referrer_id"])
    try:
        await bot.send_message(p["user_id"], f"✅ Баланс пополнен на <b>{p['hlx']} hlx</b>")
    except Exception:
        pass
    return True


async def is_paid_remote(p) -> bool:
    if p["method"] == "cryptobot":
        res = await _cryptopay("getInvoices", invoice_ids=p["ext_id"])
        items = res.get("items", [])
        return bool(items) and items[0]["status"] == "paid"
    if p["method"] == "xrocket":
        inv = await _xrocket("GET", f"tg-invoices/{p['ext_id']}")
        return inv.get("status") == "paid"
    return False


async def check(payment_id, user_id) -> str:
    p = await db.one("SELECT * FROM payments WHERE id=? AND user_id=?", payment_id, user_id)
    if not p:
        raise PayError("Платёж не найден")
    if p["status"] == "pending" and p["method"] != "stars" and await is_paid_remote(p):
        await credit(p["id"])
        return "paid"
    return p["status"]


async def checker():
    """Фоновая проверка неоплаченных крипто-счетов (вебхуки не используются)."""
    while True:
        await asyncio.sleep(20)
        try:
            now = int(time.time())
            await db.run("UPDATE payments SET status='expired' WHERE status='pending' AND created_at < ?",
                         now - INVOICE_TTL - 120)
            for p in await db.all("SELECT * FROM payments WHERE status='pending' AND method != 'stars'"):
                try:
                    if await is_paid_remote(p):
                        await credit(p["id"])
                except PayError:
                    pass
        except Exception:
            log.exception("payments checker")
