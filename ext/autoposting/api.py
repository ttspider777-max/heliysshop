"""HTTP API и раздача Mini App."""
import hashlib
import hmac
import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

import accounts
import config
import db
import gate
import payments
import post
from loader import bot

log = logging.getLogger(__name__)
routes = web.RouteTableDef()
WEBAPP_DIR = config.BASE_DIR / "webapp"
INIT_DATA_TTL = 86400


class ApiError(Exception):
    pass


def err(message, status=400, **extra):
    return web.json_response({"error": message, **extra}, status=status)


def validate_init_data(init_data: str) -> dict | None:
    """Проверяет подпись Telegram и возвращает данные пользователя."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received = pairs.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return None
        if time.time() - int(pairs["auth_date"]) > INIT_DATA_TTL:
            return None
        return json.loads(pairs["user"])
    except (KeyError, ValueError):
        return None


@web.middleware
async def auth(request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    tg_user = validate_init_data(request.headers.get("X-Init-Data", ""))
    if not tg_user:
        return err("unauthorized", 401)
    user, _ = await db.upsert_user(tg_user["id"], tg_user.get("username"), tg_user.get("first_name"),
                                   tg_user.get("is_premium", False))
    if user["banned"] and user["id"] not in config.ADMIN_IDS:
        return err("banned", 403)
    missing = await gate.missing_channels(user["id"])
    if missing:
        return err("subscribe", 403, channels=[{"title": c["title"], "url": c["url"]} for c in missing])
    request["user"] = user
    try:
        return await handler(request)
    except (ApiError, accounts.AccError, payments.PayError) as e:
        return err(str(e))
    except accounts.AccountDead:
        return err("Сессия аккаунта завершена, подключите его заново")
    except Exception:
        log.exception("api %s", request.path)
        return err("Внутренняя ошибка", 500)


async def body(request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ApiError("Неверный запрос")
    return data


async def own_account(request):
    acc = await db.one("SELECT * FROM accounts WHERE id=? AND user_id=?",
                       int(request.match_info["id"]), request["user"]["id"])
    if not acc:
        raise ApiError("Аккаунт не найден")
    return acc


async def own_mailing(request):
    m = await db.one("SELECT * FROM mailings WHERE id=? AND user_id=?",
                     int(request.match_info["id"]), request["user"]["id"])
    if not m:
        raise ApiError("Рассылка не найдена")
    return m


async def require_mailing_access(user):
    """Рассылки доступны на Free; отличие Pro — лимиты аккаунтов и чатов."""
    return None


# ---------- профиль ----------

@routes.get("/api/me")
async def me(request):
    user = request["user"]
    me_bot = await bot.me()
    refs = (await db.one("SELECT COUNT(*) c FROM users WHERE referrer_id=?", user["id"]))["c"]
    settings = await db.get_settings()
    return web.json_response({
        "user": {
            "id": user["id"], "name": user["first_name"], "balance": user["balance"],
            "sub_until": user["sub_until"], "sub_active": db.sub_active(user), "acc_limit": db.acc_limit(user),
            "plan": "pro" if db.sub_active(user) else "free", "chat_limit": db.plan(user)["chats"],
        },
        "ref": {
            "link": f"https://t.me/{me_bot.username}?start=ref{user['id']}", "count": refs,
            "earned": user["ref_earned"], "bonus": config.REF_BONUS, "percent": config.REF_PERCENT,
        },
        "packages": [{**p, "stars": payments.stars_price(p["rub"])} for p in config.PACKAGES],
        "plans": config.SUB_PLANS,
        "intervals": config.INTERVALS,
        "limits": {"free": config.ACC_LIMIT_FREE, "sub": config.ACC_LIMIT_SUB, "chats": db.plan(user)["chats"],
                   "text": config.MAX_TEXT, "caption": config.MAX_CAPTION, "photo_mb": config.MAX_PHOTO_MB,
                   "free_chats": config.FREE["chats"], "pro_chats": config.PRO["chats"],
                   "autojoin_day": config.AUTOJOIN_PER_DAY},
        "bot_username": me_bot.username,
        "links": {"support": config.SUPPORT_URL, "policy": config.POLICY_URL, "offer": config.OFFER_URL},
        "mailing_requires_sub": False,
    })


@routes.get("/api/stats")
async def stats(request):
    user = request["user"]
    s = await db.stats_summary(user["id"])
    mailings = await db.all(
        "SELECT m.id, m.status, m.sent, m.failed, m.rounds, m.joined, m.last_run, m.next_run, m.interval_min, "
        "a.name account, (SELECT COUNT(*) FROM mailing_chats c WHERE c.mailing_id=m.id AND c.active=1) chats, "
        "(SELECT COUNT(*) FROM mailing_chats c WHERE c.mailing_id=m.id AND c.active=0) removed "
        "FROM mailings m JOIN accounts a ON a.id=m.account_id WHERE m.user_id=? ORDER BY m.id DESC", user["id"])
    return web.json_response({"stats": s, "mailings": mailings, "now": int(time.time())})


# ---------- пост для рассылки ----------

@routes.get("/api/draft")
async def draft(request):
    """Пост, который пользователь прислал боту в чат (с фото, форматированием и премиум-эмодзи)."""
    d = await db.one("SELECT * FROM drafts WHERE user_id=?", request["user"]["id"])
    if not d:
        return web.json_response({"draft": None})
    return web.json_response({"draft": {"text": d["text"] or "", "photo": bool(d["file_id"]),
                                        "emoji": post.has_custom_emoji(d["entities"]),
                                        "formatted": bool(d["entities"]), "created_at": d["created_at"]}})


PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@routes.post("/api/upload")
async def upload(request):
    """Фото для рассылки из мини-приложения (multipart, поле file)."""
    if not request.content_type.startswith("multipart/"):
        raise ApiError("Отправьте фото")
    reader = await request.multipart()
    part = await reader.next()
    while part is not None and part.name != "file":
        part = await reader.next()
    if part is None or part.headers.get("Content-Type") not in PHOTO_TYPES:
        raise ApiError("Нужно фото в формате JPG, PNG или WEBP")
    ext = PHOTO_TYPES[part.headers["Content-Type"]]
    name = f"u{request['user']['id']}_{secrets.token_hex(8)}{ext}"
    limit = config.MAX_PHOTO_MB * 1024 * 1024
    size = 0
    path = config.MEDIA_DIR / name
    with open(path, "wb") as f:
        while chunk := await part.read_chunk():
            size += len(chunk)
            if size > limit:
                f.close()
                path.unlink(missing_ok=True)
                raise ApiError(f"Фото больше {config.MAX_PHOTO_MB} МБ")
            f.write(chunk)
    return web.json_response({"file": name})


@routes.get("/api/history")
async def history(request):
    user = request["user"]
    tx = await db.all("SELECT amount, kind, note, created_at FROM transactions WHERE user_id=? "
                      "ORDER BY id DESC LIMIT 50", user["id"])
    counts = await db.one(
        "SELECT (SELECT COUNT(*) FROM accounts WHERE user_id=?1) accounts, "
        "(SELECT COUNT(*) FROM mailings WHERE user_id=?1 AND status='active') active", user["id"])
    return web.json_response({"transactions": tx, "stats": {**counts, "sent": user["total_sent"]}})


@routes.post("/api/sub/buy")
async def sub_buy(request):
    user = request["user"]
    plan = next((p for p in config.SUB_PLANS if p["id"] == (await body(request)).get("plan")), None)
    if not plan:
        raise ApiError("Неверный тариф")
    cur = await db.run("UPDATE users SET balance = balance - ?1 WHERE id=?2 AND balance >= ?1", plan["price"], user["id"])
    if cur.rowcount == 0:
        raise ApiError("Недостаточно hlx на балансе")
    await db.run("INSERT INTO transactions(user_id, amount, kind, note, created_at) VALUES(?,?,?,?,?)",
                 user["id"], -plan["price"], "sub", f"Подписка · {plan['title']}", int(time.time()))
    until = await db.add_sub_days(user["id"], plan["days"])
    return web.json_response({"sub_until": until})


# ---------- оплата ----------

@routes.post("/api/pay/create")
async def pay_create(request):
    data = await body(request)
    return web.json_response(await payments.create(request["user"]["id"], data.get("package"), data.get("method")))


@routes.post("/api/pay/check")
async def pay_check(request):
    data = await body(request)
    status = await payments.check(int(data.get("payment_id") or 0), request["user"]["id"])
    return web.json_response({"status": status})


# ---------- аккаунты ----------

@routes.get("/api/accounts")
async def accounts_list(request):
    rows = await db.all(
        "SELECT a.id, a.name, a.username, a.phone, a.alive, "
        "EXISTS(SELECT 1 FROM mailings m WHERE m.account_id=a.id AND m.status='active') busy "
        "FROM accounts a WHERE a.user_id=? ORDER BY a.id", request["user"]["id"])
    for r in rows:
        r["phone"] = accounts.mask_phone(r["phone"])
    return web.json_response({"accounts": rows})


@routes.post("/api/accounts/send_code")
async def acc_send_code(request):
    await accounts.send_code(request["user"], (await body(request)).get("phone"))
    return web.json_response({"ok": True})


@routes.post("/api/accounts/sign_in")
async def acc_sign_in(request):
    done = await accounts.sign_in(request["user"], (await body(request)).get("code"))
    return web.json_response({"done": done, "need_password": not done})


@routes.post("/api/accounts/password")
async def acc_password(request):
    await accounts.sign_in_password(request["user"], (await body(request)).get("password") or "")
    return web.json_response({"done": True})


@routes.post("/api/accounts/cancel")
async def acc_cancel(request):
    await accounts.cancel_login(request["user"]["id"])
    return web.json_response({"ok": True})


@routes.post("/api/accounts/{id:\\d+}/delete")
async def acc_delete(request):
    await accounts.remove(await own_account(request))
    return web.json_response({"ok": True})


@routes.get("/api/accounts/{id:\\d+}/chats")
async def acc_chats(request):
    acc = await own_account(request)
    if not acc["alive"]:
        raise ApiError("Сессия аккаунта завершена, подключите его заново")
    return web.json_response({"chats": await accounts.scan_chats(acc)})


# ---------- рассылки ----------

@routes.get("/api/mailings")
async def mailings_list(request):
    rows = await db.all(
        "SELECT m.id, m.text, m.interval_min, m.status, m.sent, m.failed, m.next_run, m.last_run, a.name account, "
        "m.rounds, m.joined, m.autojoin, m.media IS NOT NULL photo, m.entities IS NOT NULL formatted, "
        "(SELECT COUNT(*) FROM mailing_chats c WHERE c.mailing_id=m.id AND c.active=1) chats "
        "FROM mailings m JOIN accounts a ON a.id=m.account_id WHERE m.user_id=? ORDER BY m.id DESC",
        request["user"]["id"])
    return web.json_response({"mailings": rows})


async def build_post(user, data, old=None):
    """Пост рассылки из запроса: (text, media, entities).
    source=draft — пост из чата с ботом; иначе текст + фото из мини-приложения.
    old — редактируемая рассылка: keep_photo=true оставляет её прежнее фото."""
    media = entities = None
    if data.get("source") == "draft":
        # пост из чата с ботом: фото, форматирование и премиум-эмодзи сохраняются
        d = await db.one("SELECT * FROM drafts WHERE user_id=?", user["id"])
        if not d:
            raise ApiError("Сначала отправьте пост боту в чат")
        text, entities = d["text"] or "", d["entities"]
        if len(text) > (config.MAX_CAPTION if d["file_id"] else config.MAX_TEXT):
            raise ApiError("Пост слишком длинный")
        if d["file_id"]:
            media = f"d{user['id']}_{secrets.token_hex(8)}.jpg"
            try:
                f = await bot.get_file(d["file_id"])
                await bot.download_file(f.file_path, config.MEDIA_DIR / media)
            except Exception:
                log.exception("draft photo download, user %s", user["id"])
                raise ApiError("Не удалось получить фото поста — отправьте пост боту ещё раз")
        return text, media, entities
    text = str(data.get("text") or "").strip()
    photo = str(data.get("photo") or "")
    if photo:
        # только своё фото, загруженное через /api/upload (имя без путей)
        if not photo.startswith(f"u{user['id']}_") or post.media_path(photo) is None or photo != Path(photo).name:
            raise ApiError("Фото не найдено, загрузите его заново")
        media = photo
    elif old and data.get("keep_photo") and post.media_path(old.get("media")):
        media = old["media"]
    limit = config.MAX_CAPTION if media else config.MAX_TEXT
    if len(text) > limit:
        raise ApiError(f"Текст должен быть до {limit} символов")
    if not text and not media:
        raise ApiError("Введите текст рассылки")
    return text, media, entities


@routes.post("/api/mailings")
async def mailing_create(request):
    user = request["user"]
    await require_mailing_access(user)
    data = await body(request)
    acc = await db.one("SELECT * FROM accounts WHERE id=? AND user_id=? AND alive=1",
                       int(data.get("account_id") or 0), user["id"])
    if not acc:
        raise ApiError("Аккаунт не найден")
    interval = data.get("interval")
    if interval not in config.INTERVALS:
        raise ApiError("Неверный интервал")
    scanned = accounts.scans.get(acc["id"], {})
    chat_ids = data.get("chat_ids")
    chats = [scanned[c] for c in dict.fromkeys(chat_ids if isinstance(chat_ids, list) else []) if c in scanned]
    max_chats = db.plan(user)["chats"]
    if not 1 <= len(chats) <= max_chats:
        raise ApiError(f"Выберите от 1 до {max_chats} чатов" +
                       ("" if db.sub_active(user) else f" (в Pro — до {config.PRO['chats']})"))
    if await db.one("SELECT 1 FROM mailings WHERE account_id=? AND status='active'", acc["id"]):
        raise ApiError("На этом аккаунте уже идёт рассылка")
    text, media, entities = await build_post(user, data)
    now = int(time.time())
    cur = await db.run("INSERT INTO mailings(user_id, account_id, text, interval_min, next_run, created_at, media, "
                       "entities, autojoin) VALUES(?,?,?,?,?,?,?,?,?)", user["id"], acc["id"], text, interval, now, now,
                       media, entities, int(bool(data.get("autojoin"))))
    for c in chats:
        await db.run("INSERT INTO mailing_chats(mailing_id, chat_id, kind, access_hash, title) VALUES(?,?,?,?,?)",
                     cur.lastrowid, c["id"], c["kind"], c["access_hash"], c["title"])
    return web.json_response({"id": cur.lastrowid})


@routes.get("/api/mailings/{id:\\d+}")
async def mailing_get(request):
    """Текущий пост рассылки — для редактора."""
    m = await own_mailing(request)
    return web.json_response({"mailing": {"id": m["id"], "text": m["text"] or "", "photo": bool(post.media_path(m["media"])),
                                          "formatted": bool(m["entities"]),
                                          "emoji": post.has_custom_emoji(m["entities"])}})


@routes.post("/api/mailings/{id:\\d+}/post")
async def mailing_edit_post(request):
    """Меняет пост рассылки. Чаты, пауза и статистика остаются, новый пост уйдёт со следующего круга."""
    user = request["user"]
    m = await own_mailing(request)
    text, media, entities = await build_post(user, await body(request), old=m)
    await db.run("UPDATE mailings SET text=?, media=?, entities=? WHERE id=?", text, media, entities, m["id"])
    old_path = post.media_path(m.get("media"))
    if old_path and m["media"] != media:
        old_path.unlink(missing_ok=True)   # прежнее фото больше не нужно
    return web.json_response({"ok": True})


@routes.post("/api/mailings/{id:\\d+}/stop")
async def mailing_stop(request):
    m = await own_mailing(request)
    await db.run("UPDATE mailings SET status='stopped' WHERE id=?", m["id"])
    return web.json_response({"ok": True})


@routes.post("/api/mailings/{id:\\d+}/start")
async def mailing_start(request):
    m = await own_mailing(request)
    await require_mailing_access(request["user"])
    if not await db.one("SELECT 1 FROM accounts WHERE id=? AND alive=1", m["account_id"]):
        raise ApiError("Сессия аккаунта завершена, подключите его заново")
    if await db.one("SELECT 1 FROM mailings WHERE account_id=? AND status='active' AND id != ?",
                    m["account_id"], m["id"]):
        raise ApiError("На этом аккаунте уже идёт рассылка")
    # возобновление не сбрасывает паузу между кругами
    next_run = max(int(time.time()), m["last_run"] + m["interval_min"] * 60)
    await db.run("UPDATE mailings SET status='active', next_run=? WHERE id=?", next_run, m["id"])
    return web.json_response({"ok": True})


@routes.post("/api/mailings/{id:\\d+}/autojoin")
async def mailing_autojoin(request):
    m = await own_mailing(request)
    await db.run("UPDATE mailings SET autojoin=? WHERE id=?", 0 if m["autojoin"] else 1, m["id"])
    return web.json_response({"autojoin": not m["autojoin"]})


@routes.post("/api/mailings/{id:\\d+}/delete")
async def mailing_delete(request):
    m = await own_mailing(request)
    await db.run("DELETE FROM mailing_chats WHERE mailing_id=?", m["id"])
    await db.run("DELETE FROM mailings WHERE id=?", m["id"])
    path = post.media_path(m.get("media"))
    if path:
        path.unlink(missing_ok=True)
    return web.json_response({"ok": True})


# ---------- статика ----------

def _file(name):
    async def handler(request):
        return web.FileResponse(WEBAPP_DIR / name, headers={"Cache-Control": "no-cache"})
    return handler


def build_app() -> web.Application:
    app = web.Application(middlewares=[auth])
    app.add_routes(routes)
    app.router.add_get("/", _file("index.html"))
    for name in ("style.css", "app.js"):
        app.router.add_get(f"/{name}", _file(name))
    return app
