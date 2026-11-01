"""Конструктор: дополнения к магазину, бесплатный курс, партнёрка для админов каналов, пуш «открой приложение»,
значок «Проверенный магазин» и чат с куратором (сообщения из мини-приложения → админам → ответ обратно).

Всё настраивается в /admin конструктора → 📈 Рост и продажи (ctor/admin2.py).
"""
import html
import logging
import sqlite3

from aiogram import F, Router
from aiogram.types import CallbackQuery

import config
import db
import hosting
from ctor import core
from ctor.core import money, tx
from ui import kb, raw_btn

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")


def _cb():
    from ctor import bot as cbot
    return cbot


# ======================= дополнения =======================
@router.callback_query(F.data == "c:addons")
async def cb_addons(call: CallbackQuery):
    cb = _cb()
    keys = [k for k in core.ADDONS if core.addon_on(k)]
    text = tx("addons_head") + "\n\n" + "\n\n".join(tx("addon_" + k, price=money(core.addon_price(k))) for k in keys)
    rows = [[cb.B("addons", f"c:ad:{k}", text=f"{core.ADDONS[k][0]} · {money(core.addon_price(k))}")] for k in keys]
    rows.append([cb.B("bots", "c:bots"), cb.B("menu", "c:menu")])
    await cb.out(call, text if keys else "Дополнений пока нет.", kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("c:ad:"))
async def cb_addon(call: CallbackQuery):
    """c:ad:<ключ> — выбор магазина (если их несколько) → c:ad:<ключ>:<id> — способы оплаты."""
    cb = _cb()
    uid = call.from_user.id
    parts = call.data.split(":")
    key = parts[2]
    if not core.addon_on(key):
        return await call.answer("Это дополнение сейчас недоступно", show_alert=True)
    bots = [b for b in db.user_hosted(uid) if b["tg_id"] and b["status"] not in ("canceled", "deleted")]
    if len(parts) > 3 and parts[3].isdigit():
        bid = int(parts[3])
    elif len(bots) == 1:
        bid = bots[0]["id"]
    elif not bots:
        bid = 0
    else:
        rows = [[raw_btn(f"🤖 @{b['username']}", f"c:ad:{key}:{b['id']}")] for b in bots[:10]]
        rows.append([cb.B("back", "c:addons")])
        await cb.out(call, tx("addon_pick_bot"), kb(rows))
        return await call.answer()
    await call.answer()
    await cb.pay_menu(call, uid, "addon", bid, key)


# ======================= бесплатный курс =======================
@router.callback_query(F.data.startswith("c:course:"))
async def cb_course(call: CallbackQuery):
    cb = _cb()
    lessons = core.jget("course", core.COURSE)
    if not lessons:
        return await call.answer("Курс скоро появится", show_alert=True)
    try:
        i = min(max(int(call.data.split(":")[2]), 0), len(lessons) - 1)
    except ValueError:
        i = 0
    rows = []
    if i < len(lessons) - 1:
        rows.append([cb.B("course_next", f"c:course:{i + 1}")])
    else:
        url = cb.app_url()
        rows.append([raw_btn(core.plain(tx("course_done"))[:60], web_app=url + "#create") if url
                     else raw_btn(core.plain(tx("course_done"))[:60], "c:new", style="success")])
    nav = []
    if i > 0:
        nav.append(cb.B("back", f"c:course:{i - 1}"))
    nav.append(cb.B("menu", "c:menu"))
    rows.append(nav)
    await cb.out(call, lessons[i].get("x") or lessons[i].get("t") or "—", kb(rows))
    await call.answer()


# ======================= партнёрка =======================
@router.callback_query(F.data == "c:partner")
async def cb_partner(call: CallbackQuery):
    cb = _cb()
    p = core.partner_of(call.from_user.id)
    if not p:
        return await call.answer("Ты пока не партнёр — напиши в поддержку", show_alert=True)
    users, buyers, due = core.partner_stats(p)
    u = cb.username()
    link = f"https://t.me/{u}?start=p_{p['code']}" if u else "—"
    await cb.out(call, tx("partner", reward=money(p["reward"]), users=users, buyers=buyers,
                          earned=money(p["earned"]), due=money(due), link=html.escape(link)),
                 kb([[cb.B("menu", "c:menu")]]))
    await call.answer()


# ======================= пуш «открой приложение» =======================
def push_hours():
    try:
        return min(max(float(core.get("push_hours", 3)), 0.5), 72)
    except (TypeError, ValueError):
        return 3.0


async def push_tick():
    """Тем, кто нажал /start, но за N часов так и не открыл мини-приложение и не создал бота, — одно сообщение."""
    cb = _cb()
    url = cb.app_url()
    if not url or not core.flag_on("push"):
        return 0
    h = push_hours()
    rows = db.q("SELECT * FROM ctor_users WHERE app_opened IS NULL AND push_sent=0 AND banned=0 "
                "AND joined <= datetime('now','localtime', ?) AND joined >= datetime('now','localtime','-3 days') "
                "AND id NOT IN (SELECT user_id FROM hosted_bots WHERE tg_id IS NOT NULL) LIMIT 30", (f"-{h} hours",))
    n = 0
    for u in rows:
        db.x("UPDATE ctor_users SET push_sent=1 WHERE id=?", (u["id"],))
        if u["id"] in config.ADMINS:
            continue
        ok = await cb.send(u["id"], tx("push_app", name=html.escape(u["first_name"] or "друг")),
                           kb([[cb.B("app", web_app=url)]]))
        n += bool(ok)
    return n


# ======================= «Проверенный магазин» =======================
def verified_need():
    try:
        return max(int(float(core.get("verified_need", 50))), 1)
    except (TypeError, ValueError):
        return 50


def shop_sales(bid):
    """Сколько выполненных заказов в базе магазина клиента."""
    try:
        con = sqlite3.connect(f"file:{hosting.db_path(bid)}?mode=ro", uri=True, timeout=3)
        try:
            return con.execute("SELECT COUNT(*) FROM orders WHERE status IN ('done','manual')").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0


def set_shop_setting(bid, key, value):
    con = sqlite3.connect(hosting.db_path(bid), timeout=5)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value))
        con.commit()
    finally:
        con.close()


async def verified_tick():
    """Раз в полчаса: магазины с N+ продаж получают значок «✅ Проверенный магазин» (виден покупателям)."""
    if not core.flag_on("verified"):
        return 0
    need = verified_need()
    n = 0
    for b in db.q("SELECT * FROM hosted_bots WHERE source='ctor' AND COALESCE(verified,0)=0 "
                  "AND status IN ('running','stopped')"):
        sales = shop_sales(b["id"])
        if sales < need:
            continue
        try:
            set_shop_setting(b["id"], "verified", "1")
        except sqlite3.Error as e:
            log.warning("конструктор: значок магазину #%s не записан: %s", b["id"], e)
            continue
        db.set_hosted(b["id"], verified=1)
        n += 1
        await _cb().send(b["user_id"], tx("verified", username=html.escape(b["username"] or "?"), n=sales))
    return n


# ======================= чат с куратором =======================
async def chat_from_user(uid, text):
    """Сообщение из мини-приложения: сохраняем и отправляем админам с кнопкой «Ответить»."""
    cb = _cb()
    core.chat_add(uid, "user", text)
    u = core.user(uid)
    await cb.to_admins(f"💬 <b>Чат с куратором</b>\n👤 {core.user_link(u)}\n\n{html.escape(text)}",
                       kb([[raw_btn("↩️ Ответить", f"ca:chr:{uid}", style="primary")]]))


async def chat_reply(uid, text):
    """Ответ админа: в историю чата (видно в приложении) и в личку от бота."""
    cb = _cb()
    core.chat_add(uid, "admin", text)
    return await cb.send(uid, tx("chat_reply", text=html.escape(text)),
                         kb([[cb.B("app", web_app=cb.app_url() + "#chat")]]) if cb.app_url() else None)
