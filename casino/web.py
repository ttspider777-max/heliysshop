"""Cursed Casino — сайт: мини-приложение (/app) и API. Игрока определяет подпись Telegram (initData)."""
import hashlib
import hmac
import html
import json
import time
from urllib.parse import parse_qsl, quote

from aiohttp import web

from . import config, engine, games, store

GameError = engine.GameError
MAX_AGE = 24 * 3600


def check_init_data(raw, token):
    """Проверка подписи initData по документации Telegram. Возвращает данные игрока или None."""
    if not raw or len(raw) > 4096:
        return None
    try:
        data = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    got = data.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, check.encode(), hashlib.sha256).hexdigest(), got):
        return None
    try:
        if time.time() - int(data.get("auth_date", 0)) > MAX_AGE:
            return None
        return json.loads(data["user"])
    except (KeyError, ValueError):
        return None


def buy_url(uid):
    support = (store.get("support") or config.SUPPORT).lstrip("@")
    if not support:
        return ""
    text = f"Здравствуйте! Хочу купить CRX. Мой ID: {uid}"
    return f"https://t.me/{support}?text={quote(text)}"


def me_payload(uid):
    u = store.user(uid)
    lo, hi = store.limits()
    return {
        "id": uid, "name": u["name"], "username": u["username"], "balance": u["balance"],
        "brand": store.get("brand") or config.NAME, "currency": config.CURRENCY,
        "min_bet": lo, "max_bet": hi, "rtp": store.rtp(),
        "daily_left": games.daily_left(u), "daily_prizes": [p for p, _ in engine.DAILY_PRIZES],
        "stats": {"games": u["games"], "wagered": u["wagered"], "won": u["won"]},
        "ref": {"percent": int(store.get("ref_percent") or 0), "earned": u["ref_earned"],
                "count": store.q("SELECT COUNT(*) c FROM users WHERE ref_by=?", (uid,)).fetchone()["c"]},
        "fair": store.fair_info(uid), "buy_url": buy_url(uid),
        "resume": games.resume(uid), "plinko": games.plinko_tables(),
        "dice_mult": engine.ROULETTE_MULT,
    }


def _wrap(fn):
    async def handler(request):
        user = check_init_data(request.headers.get("X-Init-Data", ""), config.BOT_TOKEN)
        if not user or "id" not in user:
            return web.json_response({"ok": False, "error": "Откройте игру из Telegram", "auth": False}, status=401)
        uid = int(user["id"])
        u, _ = store.touch(uid, user.get("username"), user.get("first_name"))
        if u["banned"]:
            return web.json_response({"ok": False, "error": "Доступ закрыт"}, status=403)
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        try:
            res = fn(uid, body)
        except GameError as e:
            return web.json_response({"ok": False, "error": str(e)})
        except Exception:
            import logging
            logging.exception("ошибка игры %s", fn.__name__)
            return web.json_response({"ok": False, "error": "Что-то пошло не так, попробуйте ещё раз"}, status=500)
        return web.json_response({"ok": True, **(res or {})})
    return handler


def _history(uid, p):
    return {"history": store.history(uid)}


def _rotate(uid, p):
    return store.rotate_seed(uid, str(p.get("client_seed") or "").strip() or None)


def _me(uid, p):
    return me_payload(uid)


ROUTES = {
    "me": _me, "daily": games.daily, "history": _history, "fair/rotate": _rotate,
    "coin": games.play_coin, "dice": games.play_dice, "limbo": games.play_limbo,
    "plinko": games.play_plinko, "roulette": games.play_roulette,
    "crash/start": games.crash_start, "crash/state": games.crash_state, "crash/cash": games.crash_cash,
    "mines/start": games.mines_start, "mines/open": games.mines_open, "mines/cash": games.mines_cash,
}


async def app_page(request):
    try:
        with open(config.APP_HTML, encoding="utf-8") as f:
            page = f.read()
    except OSError:
        return web.Response(text="app.html не найден", status=500)
    page = page.replace("{{BRAND}}", html.escape(store.get("brand") or config.NAME))
    return web.Response(text=page, content_type="text/html",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


async def health(request):
    return web.Response(text="ok")


def make_app():
    app = web.Application(client_max_size=64 * 1024)
    app.router.add_get("/", app_page)
    app.router.add_get("/app", app_page)
    app.router.add_get("/health", health)
    for path, fn in ROUTES.items():
        app.router.add_post(f"/api/{path}", _wrap(fn))
    return app


async def start():
    runner = web.AppRunner(make_app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, config.HOST, config.PORT).start()
    return runner
