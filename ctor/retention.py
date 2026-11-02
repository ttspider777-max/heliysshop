"""Удержание владельцев магазинов (работает в ctor.bot.remind_loop).

• Скидка в последний день пробного: за сутки до конца пробного бот сам создаёт личный промокод (−20% по умолчанию,
  действует 24 часа, одно использование), сразу применяет его и пишет человеку.
• Еженедельный отчёт: раз в 7 дней владелец работающего магазина получает в личку продажи, выручку и новых
  покупателей за неделю (данные — из базы его магазина).
"""
import html
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta

import db
import hosting
from ctor import core
from ctor.core import money, tx

log = logging.getLogger(__name__)
FMT = "%Y-%m-%d %H:%M:%S"


def _ts(s):
    try:
        return datetime.strptime(s, FMT)
    except (TypeError, ValueError):
        return None


# ======================= скидка в последний день пробного =======================
def lastday_pct():
    try:
        return min(max(int(float(core.get("lastday_pct") or 20)), 1), 90)
    except ValueError:
        return 20


def lastday_hours():
    try:
        return min(max(int(float(core.get("lastday_hours") or 24)), 1), 72)
    except ValueError:
        return 24


def make_code(uid):
    while True:
        code = f"LAST{secrets.token_hex(3).upper()}"
        if not core.promo(code):
            return code


async def lastday_tick(now=None):
    """Владельцам пробных магазинов, у которых осталось меньше суток, — личный промокод. -> сколько выдано."""
    from ctor import bot as cbot
    if not core.flag_on("lastday"):
        return 0
    now = now or datetime.now()
    hours = lastday_hours()
    pct = lastday_pct()
    done = 0
    rows = db.q("SELECT * FROM hosted_bots WHERE source='ctor' AND plan='trial' AND status='running' "
                "AND trial_until IS NOT NULL AND token IS NOT NULL")
    for b in rows:
        until = _ts(b["trial_until"])
        if not until or not (timedelta(0) < until - now <= timedelta(hours=24)):
            continue
        if (b["lastday_tag"] or "") == b["trial_until"]:  # за этот пробный уже выдавал
            continue
        db.set_hosted(b["id"], lastday_tag=b["trial_until"])
        uid = b["user_id"]
        u = core.user(uid)
        if not u or u["banned"]:
            continue
        cur = core.active_promo(uid)
        if cur and cur["kind"] == "percent" and cur["value"] >= pct:
            continue  # у человека уже есть скидка не меньше
        code = make_code(uid)
        expires = (now + timedelta(hours=hours)).strftime(FMT)
        db.x("INSERT INTO ctor_promos(code, kind, value, max_uses, used, until, created) "
             "VALUES (?, 'percent', ?, 1, 0, ?, ?)", (code, pct, expires, db.now()))
        core.set_user_promo(uid, code)
        price, _ = core.final_price(uid, "pro")  # для примера в тексте — Pro «навсегда»
        await cbot.send(uid, tx("lastday_offer", pct=pct, code=code, hours=hours,
                                username=html.escape(b["username"] or "?"),
                                old=money(core.tariff_price("pro")), price=money(price)),
                        cbot._buy_kb(b))
        done += 1
    return done


# ======================= еженедельный отчёт =======================
def shop_stats(bid, since, until):
    """Продажи и покупатели магазина за период (из его собственной базы). None — базы нет."""
    path = hosting.db_path(bid)
    if not os.path.exists(path):
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        paid = "status IN ('done','manual')"
        s, u = since.strftime(FMT), until.strftime(FMT)
        n, total = con.execute(f"SELECT COUNT(*), COALESCE(SUM(price),0) FROM orders WHERE {paid} "
                               "AND created >= ? AND created < ?", (s, u)).fetchone()
        new_users = con.execute("SELECT COUNT(*) FROM users WHERE joined >= ? AND joined < ?", (s, u)).fetchone()[0]
        users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        top = con.execute(f"SELECT product_name, COUNT(*) c FROM orders WHERE {paid} AND created >= ? AND created < ? "
                          "GROUP BY product_name ORDER BY c DESC LIMIT 1", (s, u)).fetchone()
        return {"orders": n or 0, "sum": round(total or 0, 2), "new_users": new_users or 0, "users": users or 0,
                "top": top[0] if top else None}
    except sqlite3.Error as e:
        log.info("отчёт: база магазина #%s не прочиталась: %s", bid, e)
        return None
    finally:
        con.close()


def _trend(cur, prev):
    if not prev:
        return ""
    d = round((cur - prev) / prev * 100)
    return f" ({'+' if d >= 0 else ''}{d}% к прошлой неделе)" if d else " (как на прошлой неделе)"


def report_text(b, st, prev):
    lines = [f"🛒 Продаж: <b>{st['orders']}</b>{_trend(st['orders'], prev and prev['orders'])}",
             f"💰 Выручка: <b>{money(st['sum'])}</b>{_trend(st['sum'], prev and prev['sum'])}",
             f"👥 Новых покупателей: <b>{st['new_users']}</b> · всего {st['users']}"]
    if st["top"]:
        lines.append(f"🏆 Хит недели: <b>{html.escape(st['top'])}</b>")
    tip = tx("weekly_tip_zero") if not st["orders"] else tx("weekly_tip_ok")
    return tx("weekly_report", username=html.escape(b["username"] or "?"), stats="\n".join(lines), tip=tip)


async def weekly_tick(now=None):
    """Раз в 7 дней на каждый работающий магазин. Пишу только днём (10–21), чтобы не будить. -> сколько отправлено."""
    from ctor import bot as cbot
    from ui import kb, raw_btn
    if not core.flag_on("weekly"):
        return 0
    now = now or datetime.now()
    if not 10 <= now.hour < 21:
        return 0
    sent = 0
    for b in db.q("SELECT * FROM hosted_bots WHERE source='ctor' AND status='running' AND token IS NOT NULL"):
        last = _ts(b["report_at"]) or _ts(b["started"]) or _ts(b["created"])
        if not last or now - last < timedelta(days=7):
            continue
        db.set_hosted(b["id"], report_at=now.strftime(FMT))
        u = core.user(b["user_id"])
        if not u or u["banned"]:
            continue
        st = shop_stats(b["id"], now - timedelta(days=7), now)
        if st is None:
            continue
        prev = shop_stats(b["id"], now - timedelta(days=14), now - timedelta(days=7))
        rows = [[raw_btn(f"🤖 Открыть @{b['username']}", url=f"https://t.me/{b['username']}")]] if b["username"] else []
        if await cbot.send(b["user_id"], report_text(b, st, prev), kb(rows) if rows else None):
            sent += 1
    return sent
