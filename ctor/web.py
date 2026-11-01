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


def _auth(request):
    from ctor import bot as cbot
    if not cbot.running():
        return None, jerr("off", "Конструктор сейчас выключен", 503)
    tg = _mw().check_init_data(request.headers.get("X-Init-Data"), token=core.token())
    if not tg:
        return None, jerr("auth", "Откройте приложение из Telegram", 401)
    u = core.touch_tg(tg)
    if u["banned"] and tg["id"] not in __import__("config").ADMINS:
        return None, jerr("banned", core.plain(core.tx("banned")), 403)
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
                    "can_buy": bool(b["trial_until"] and b["token"])})
    return out


async def boot(request):
    from ctor import bot as cbot
    ok, err = _auth(request)
    if err:
        return err
    tg, u = ok
    uid = tg["id"]
    mw = _mw()
    days = cbot.days_text()
    pr = core.money(core.price())
    d, _ = core.draft(uid)
    season = core.get("app_season", "none")
    if season not in appcfg.SEASONS:
        season = "none"
    data = {
        "ok": True,
        "app": {
            "texts": {k: mw.sanitize(core.tx(k, days=days, price=pr)) for k in core.APP_TEXTS},
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
        "trial": {"on": cbot.trial_free(uid), "days": core.trial_days(), "text": days},
        "user": {"id": uid, "first_name": u["first_name"], "username": u["username"],
                 "photo_url": tg.get("photo_url"), "balance": round(u["balance"] or 0, 2),
                 "is_admin": uid in __import__("config").ADMINS},
        "bots": _bots(uid),
        "draft": {k: d.get(k) for k in ("color", "hex", "style", "title", "desc")},
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
    ok, err = _auth(request)
    if err:
        return err
    tg, _ = ok
    uid = tg["id"]
    body = await _body(request)
    color = str(body.get("color") or "")
    style = str(body.get("style") or "")
    title = core.clean_title(str(body.get("title") or ""))
    desc = core.clean_desc(str(body.get("desc") or ""))
    if color == "custom":
        hx = core.norm_hex(str(body.get("hex") or ""))
        if not hx:
            return jerr("hex", "Цвет нужен в формате #ff7a1a")
    elif color not in core.COLORS:
        return jerr("color", "Выберите цвет")
    if style not in appcfg.SEASONS:
        return jerr("style", "Выберите стиль")
    if not title:
        return jerr("title", "Напишите заголовок")
    if not desc:
        return jerr("desc", "Напишите описание")
    d, _ = core.draft(uid)
    d.update(color=color, style=style, title=title, desc=desc)
    if color == "custom":
        d["hex"] = hx
    else:
        d.pop("hex", None)
    step = core.next_step(d)
    core.save_draft(uid, d, step)
    await cbot.prompt(uid, uid, step, d)
    return web.json_response({"ok": True, "step": step})


async def topup(request):
    from ctor import bot as cbot
    ok, err = _auth(request)
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
    ok, err = _auth(request)
    if err:
        return err
    tg, _ = ok
    body = await _body(request)
    try:
        bid = int(body.get("bot"))
    except (TypeError, ValueError):
        return jerr("bad", "Бот не найден")
    res = await cbot.buy_bot(tg["id"], bid)
    if res == "no_money":
        return jerr("no_money", f"Не хватает на балансе — нужно {core.money(core.price())}")
    if res != "ok":
        return jerr(res, "Бот уже куплен или занят — обновите страницу")
    u = core.user(tg["id"])
    return web.json_response({"ok": True, "balance": round(u["balance"] or 0, 2), "bots": _bots(tg["id"])})


async def page(request):
    with open(PAGE, encoding="utf-8") as f:
        body = f.read()
    return web.Response(text=body, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-cache"})


def setup(app):
    app.router.add_get("/c/app", page)
    app.router.add_get("/c/app/", page)
    app.router.add_get("/c/api/boot", boot)
    app.router.add_post("/c/api/draft", save_draft)
    app.router.add_post("/c/api/topup", topup)
    app.router.add_post("/c/api/buy", buy)
    app.router.add_get("/c/m/{sig}/{fid}", tg_media)
