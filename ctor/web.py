"""Мини-приложение конструктора: страница /c/app и API /c/api/* на сайте основного бота.

Каждый запрос подписан Telegram (initData) — подпись проверяется токеном конструктора, поэтому подделать
пользователя нельзя. Шаги 1–4 мастера (цвет, стиль, заголовок, описание) заполняются здесь, после чего
бот-конструктор сам пишет пользователю в чат следующий шаг (приветствие).
"""
import asyncio
import hashlib
import hmac
import logging
import os
from urllib.parse import quote

from aiohttp import web

import appcfg
import db
from ctor import core

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "webapp", "ctor.html")
_locks = {}


def _mw():
    import web as mainweb  # сайт основного бота (загружен к моменту запросов)
    return mainweb


def jerr(code, msg, status=400):
    return web.json_response({"ok": False, "error": code, "message": msg}, status=status)


async def _auth(request):
    from ctor import bot as cbot
    if not cbot.running():
        return None, jerr("off", "Конструктор сейчас выключен", 503)
    tg = _mw().check_init_data(request.headers.get("X-Init-Data"), token=core.token())
    if not tg:
        return None, jerr("auth", "Откройте приложение из Telegram", 401)
    u = core.touch_tg(tg)
    if tg["id"] not in __import__("config").ADMINS:  # защита от спама запросами
        import flood
        if flood.check(("cweb", tg["id"])) != "ok":
            return None, jerr("flood", flood.WARN_TEXT, 429)
    if core.get("maint") == "1" and tg["id"] not in __import__("config").ADMINS:
        return None, jerr("maint", core.plain(core.tx("maint")), 503)
    if u["banned"] and tg["id"] not in __import__("config").ADMINS:
        return None, jerr("banned", core.plain(core.ban_text(u)), 403)
    if tg["id"] not in __import__("config").ADMINS:  # обязательная подписка (/admin → 📣)
        need = await cbot.sub_missing(cbot.bot(), tg["id"])
        if need:
            mw = _mw()
            return None, web.json_response({
                "ok": False, "error": "sub", "message": core.plain(core.tx("app_sub_title")),
                "sub": {"title": mw.sanitize(core.tx("app_sub_title")), "text": mw.sanitize(core.tx("app_sub_text")),
                        "check": mw.sanitize(core.tx("app_sub_check")),
                        "channels": [{"title": c["title"], "url": c["url"]} for c in need]}}, status=403)
    return (tg, u), None


# ---------- медиа (фон карточки) — файлы бота-конструктора ----------
def media_sig(fid):
    return hmac.new(core.token().encode(), fid.encode(), hashlib.sha256).hexdigest()[:20]


def media(raw):
    if not raw or "|" not in raw:
        return None
    kind, fid = raw.split("|", 1)
    return {"url": f"/c/m/{media_sig(fid)}/{quote(fid, safe='')}", "type": kind}


async def tg_media(request):
    from ctor import bot as cbot
    fid = request.match_info["fid"]
    if not core.token() or not hmac.compare_digest(media_sig(fid), request.match_info["sig"]):
        raise web.HTTPForbidden()
    b = cbot.bot()
    if not b:
        raise web.HTTPNotFound()
    mw = _mw()
    key = "c" + hashlib.sha1(fid.encode()).hexdigest()
    path = mw._cached(key)
    if not path:
        lock = _locks.setdefault(key, asyncio.Lock())
        async with lock:
            path = mw._cached(key)
            if not path:
                try:
                    f = await b.get_file(fid)
                    ext = os.path.splitext(f.file_path or "")[1].lower() or ".bin"
                    os.makedirs(mw.CACHE, exist_ok=True)
                    path = os.path.join(mw.CACHE, key + ext)
                    await b.download_file(f.file_path, destination=path + ".part")
                    os.replace(path + ".part", path)
                except Exception as e:
                    log.info("конструктор: медиа не скачалось: %s", e)
                    raise web.HTTPNotFound()
    return mw._file_response(path)


# ---------- данные ----------
def _bots(uid):
    from handlers import builder
    from ctor.bot import STATUS_RU
    out = []
    for b in db.user_hosted(uid):
        if not b["tg_id"]:
            continue
        out.append({"id": b["id"], "username": b["username"], "status": b["status"],
                    "status_text": STATUS_RU.get(b["status"], b["status"]),
                    "trial_until": builder.fmt_until(b["trial_until"]) if b["trial_until"] else None,
                    "plan": core.bot_plan(b), "plan_text": core.plan_line(b), "verified": bool(b["verified"]),
                    "can_buy": bool(b["trial_until"] and b["token"])})
    return out


def _tariffs(uid, mw):
    from ctor import bot as cbot
    out = []
    for k in core.tariffs_on():
        amount, _ = core.final_price(uid, k)
        out.append({"id": k, "name": core.tariff_name(k), "days": core.tariff_days(k), "period": core.tariff_period(k),
                    "price": amount, "base": core.tariff_price(k), "stars": core.stars_for(amount),
                    "desc": mw.sanitize(cbot.tariff_desc(k))})
    return out


async def boot(request):
    from ctor import bot as cbot
    ok, err = await _auth(request)
    if err:
        return err
    tg, u = ok
    uid = tg["id"]
    mw = _mw()
    days = cbot.days_text()
    pr = core.money(core.price())
    mn = core.money(core.min_tariff_price())
    d, _ = core.draft(uid)
    if not u["app_opened"]:
        db.x("UPDATE ctor_users SET app_opened=? WHERE id=?", (db.now(), uid))
    season = core.get("app_season", "none")
    if season not in appcfg.SEASONS:
        season = "none"
    if appcfg.ny_on() and season not in ("newyear", "winter"):
        season = "newyear"
    data = {
        "ok": True,
        "app": {
            "texts": {k: mw.sanitize(core.tx(k, days=days, price=pr, min=mn)) for k in core.APP_TEXTS},
            "icons": core.icons(),
            "accent": core.get("app_accent") or "#8b5cf6",
            "season": season,
            "season_badge": appcfg.SEASONS[season][1],
            "bg": media(core.get("app_bg")),
            "bot": cbot.username() or "",
            "support": core.support_url(),
        },
        "colors": [{"id": k, "name": v[0], "hex": v[1], "swatch": v[2]} for k, v in core.COLORS.items()],
        "styles": [{"id": k, "name": v[0], "badge": v[1], "accent": v[3]} for k, v in appcfg.SEASONS.items()],
        "price": core.price(),
        "min_price": core.min_tariff_price(),
        "tariffs": _tariffs(uid, mw),
        "faq": [{"q": mw.sanitize(f.get("q") or ""), "a": mw.sanitize(f.get("a") or "")}
                for f in core.jget("faq", core.FAQ)],
        "course": core.flag_on("course"),
        "chat": [{"me": m["sender"] == "user", "text": m["text"], "at": m["created"][11:16]}
                 for m in core.chat_list(uid)],
        "pay": {"stars": core.stars_price() if core.pay_on("stars") else 0,
                "crypto": [m for m in ("cryptobot", "xrocket") if core.pay_on(m)], "sbp": core.pay_on("sbp")},
        "trial": {"on": cbot.trial_free(uid), "days": core.trial_days(), "text": days},
        "user": {"id": uid, "first_name": u["first_name"], "username": u["username"],
                 "photo_url": tg.get("photo_url"), "balance": round(u["balance"] or 0, 2),
                 "is_admin": uid in __import__("config").ADMINS},
        "bots": _bots(uid),
        "draft": {k: d.get(k) for k in ("mode", "color", "hex", "style", "title", "desc", "plan")},
        "ideas": core.desc_ideas(d.get("title")),
        "topup": {"min": core.topup_min(), "amounts": [a for a in (100, 300, 500, 1000, 2000) if a >= core.topup_min()]},
    }
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def _body(request):
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


async def save_draft(request):
    """Шаги 1–4 из мини-приложения. Дальше бот пишет в чат следующий шаг."""
    from ctor import bot as cbot
    ok, err = await _auth(request)
    if err:
        return err
    tg, _ = ok
    uid = tg["id"]
    body = await _body(request)
    color = str(body.get("color") or "")
    style = str(body.get("style") or "")
    title = core.clean_title(str(body.get("title") or ""))
    desc = core.clean_desc(str(body.get("desc") or ""))
    # «без мини-приложения»: магазин работает кнопками в чате, цвет и стиль не нужны
    mode = "bot" if str(body.get("mode") or "") == "bot" else "app"
    if mode == "app" and color == "custom":
        hx = core.norm_hex(str(body.get("hex") or ""))
        if not hx:
            return jerr("hex", "Цвет нужен в формате #ff7a1a")
    elif mode == "app" and color not in core.COLORS:
        return jerr("color", "Выберите цвет")
    if mode == "app" and style not in appcfg.SEASONS:
        return jerr("style", "Выберите стиль")
    if not title:
        return jerr("title", "Напишите заголовок")
    if not desc:
        return jerr("desc", "Напишите описание")
    d, _ = core.draft(uid)
    d.update(mode=mode, title=title, desc=desc)
    if mode == "app":
        d.update(color=color, style=style)
    else:
        for k in ("color", "style", "hex"):
            d.pop(k, None)
    plan = str(body.get("plan") or "")
    if plan == "trial" and cbot.trial_ok(uid, d):
        d["plan"] = "trial"
    elif plan in core.TARIFFS and core.tariff_on(plan):
        d["plan"] = plan
    else:
        d["plan"] = "buy"  # тариф выберет в чате
    if mode == "app" and color == "custom":
        d["hex"] = hx
    elif mode == "app":
        d.pop("hex", None)
    step = core.next_step(d)
    core.save_draft(uid, d, step)
    await cbot.prompt(uid, uid, step, d)
    return web.json_response({"ok": True, "step": step})


async def topup(request):
    from ctor import bot as cbot
    ok, err = await _auth(request)
    if err:
        return err
    tg, _ = ok
    body = await _body(request)
    try:
        amount = round(float(body.get("amount")), 2)
    except (TypeError, ValueError):
        return jerr("amount", "Укажите сумму")
    if amount < core.topup_min() or amount > 100000:
        return jerr("amount", f"Сумма — от {core.money(core.topup_min())} до 100000₽")
    await cbot.start_topup(tg["id"], tg["id"], amount)
    return web.json_response({"ok": True})


async def buy(request):
    from ctor import bot as cbot
    ok, err = await _auth(request)
    if err:
        return err
    tg, _ = ok
    body = await _body(request)
    try:
        bid = int(body.get("bot"))
    except (TypeError, ValueError):
        return jerr("bad", "Бот не найден")
    b = db.hosted(bid)
    if not b or b["user_id"] != tg["id"] or not cbot.can_renew(b):
        return jerr("bad", "Бот уже куплен навсегда — обновите страницу")
    tariff = str(body.get("tariff") or "")
    if tariff in core.TARIFFS and core.tariff_on(tariff):
        await cbot.pay_menu(tg["id"], tg["id"], "buy", bid, tariff)  # способы оплаты — в чат с ботом
    else:
        await cbot.tariff_view(tg["id"], tg["id"], "b", bid)
    return web.json_response({"ok": True})


async def chat(request):
    """Чат с куратором: GET — история, POST {text} — новое сообщение (уйдёт админам в Telegram)."""
    from ctor import growth
    ok, err = await _auth(request)
    if err:
        return err
    tg, _ = ok
    uid = tg["id"]
    if request.method == "POST":
        body = await _body(request)
        text = str(body.get("text") or "").strip()
        if not text:
            return jerr("text", "Напишите сообщение")
        if len(text) > 2000:
            return jerr("text", "Слишком длинно — до 2000 символов")
        recent = db.val("SELECT COUNT(*) FROM ctor_chat WHERE user_id=? AND sender='user' "
                        "AND created >= datetime('now','localtime','-1 minute')", (uid,)) or 0
        if recent >= 5:
            return jerr("flood", "Не так быстро — подождите минуту", 429)
        await growth.chat_from_user(uid, text)
    msgs = [{"me": m["sender"] == "user", "text": m["text"], "at": m["created"][11:16]} for m in core.chat_list(uid)]
    return web.json_response({"ok": True, "chat": msgs}, headers={"Cache-Control": "no-store"})


async def page(request):
    from web import with_ny
    with open(PAGE, encoding="utf-8") as f:
        body = with_ny(f.read())
    return web.Response(text=body, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-cache"})


def setup(app):
    app.router.add_get("/c/app", page)
    app.router.add_get("/c/app/", page)
    from web import ny_js
    app.router.add_get("/c/ny.js", ny_js)
    app.router.add_get("/c/app/ny.js", ny_js)
    app.router.add_get("/c/api/boot", boot)
    app.router.add_post("/c/api/draft", save_draft)
    app.router.add_post("/c/api/topup", topup)
    app.router.add_post("/c/api/buy", buy)
    app.router.add_get("/c/api/chat", chat)
    app.router.add_post("/c/api/chat", chat)
    app.router.add_get("/c/m/{sig}/{fid}", tg_media)
