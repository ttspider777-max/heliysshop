"""Встроенный сайт бота: мини-приложение магазина (/app + /api), документы (/privacy, /terms).

Мини-приложение: каталог, карточки товаров с фото/видео, покупка (баланс / звёзды / СБП), профиль со статусом,
ежедневный бонус, пополнение, заказы, рефералы, промокод. Каждый запрос к /api подписан Telegram (initData) —
бот проверяет подпись своим токеном, поэтому подделать пользователя нельзя.

Файлы из Telegram (фото/видео товаров, фон карточки) отдаются по /m/<подпись>/<file_id> и кешируются на диске.
Премиум-эмодзи — /api/emoji (данные стикеров) и /ef/<файл>.

Боты клиентов слушают свой внутренний порт; основной бот выводит их наружу по адресу /b/<номер>/...
"""
import asyncio
import gzip
import hashlib
import hmac
import html
import json
import logging
import os
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote

import aiohttp
from aiohttp import web

import admins
import appcfg
import config
import crypto
import db
from texts import APP_TEXTS, fdate, money, status as order_status, t
from ui import doc_text

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "webapp")
CACHE = os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)), "media_cache")
MAX_MEDIA = 20 * 1024 * 1024  # Bot API отдаёт файлы до 20 МБ

_bot = None

DOCS = {
    "privacy": "Политика конфиденциальности",
    "terms": "Пользовательское соглашение",
}


# ======================= документы =======================
PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {shop}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; font: 16px/1.65 -apple-system, "Segoe UI", Roboto, sans-serif; background: #f5f5f7; color: #1d1d1f; }}
main {{ max-width: 760px; margin: 0 auto; padding: 28px 18px 60px; }}
h1 {{ font-size: 26px; line-height: 1.25; margin: 0 0 6px; }}
.brand {{ color: #6e6e73; margin-bottom: 22px; }}
.doc {{ background: #fff; border-radius: 14px; padding: 20px 22px; white-space: pre-wrap; word-wrap: break-word; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.seller {{ margin-top: 18px; padding: 16px 22px; border-radius: 14px; background: #ececf0; white-space: pre-wrap; font-size: 15px; }}
footer {{ margin-top: 18px; color: #6e6e73; font-size: 13px; }}
a {{ color: #0a66d6; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #111113; color: #f2f2f4; }}
  .doc {{ background: #1c1c1f; box-shadow: none; }}
  .seller {{ background: #26262a; }}
  .brand, footer {{ color: #9a9aa1; }}
  a {{ color: #6cb2ff; }}
}}
</style></head>
<body><main>
<h1>{title}</h1>
<div class="brand">{shop}</div>
<div class="doc">{body}</div>
{seller}
<footer>{footer}</footer>
</main></body></html>"""


def public_url():
    return appcfg.public_url()


def doc_link(name):
    """Ссылка на документ для платёжной системы: своя ссылка админа, иначе страница встроенного сайта."""
    own = db.get_setting(f"doc_url:{name}")
    if own:
        return own
    base = public_url()
    return f"{base}/{name}" if base else None


def _render(title, body, seller="", footer=""):
    seller_html = f'<div class="seller">{seller}</div>' if seller else ""
    return PAGE.format(title=html.escape(title), shop=html.escape(config.SHOP_NAME), body=body,
                       seller=seller_html, footer=footer)


async def page(request):
    name = request.match_info["name"]
    text = doc_text(name)
    if name not in DOCS or not text:
        return web.Response(status=404, content_type="text/html", charset="utf-8",
                            text=_render("Документ не найден", "Этот документ пока не опубликован."))
    ts = db.get_setting(f"doc:{name}:ts") or ""
    footer = f"Редакция от {ts[8:10]}.{ts[5:7]}.{ts[:4]}" if len(ts) >= 10 else ""
    return web.Response(content_type="text/html", charset="utf-8",
                        text=_render(DOCS[name], sanitize(text), sanitize(db.get_setting("seller_info") or ""), footer))


async def index(request):
    raise web.HTTPFound("app")


async def health(request):
    return web.Response(text="ok")


# ======================= безопасный HTML (тексты Telegram -> мини-приложение) =======================
ALLOWED = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "blockquote", "a",
           "tg-emoji", "tg-spoiler", "span", "br"}


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED:
            return
        a = dict(attrs)
        if tag == "br":
            return self.out.append("<br>")
        extra = ""
        if tag == "a":
            href = (a.get("href") or "").strip()
            if not re.match(r"^(https?://|tg://)", href):
                return
            extra = f' href="{html.escape(href)}" target="_blank" rel="noopener"'
        elif tag == "tg-emoji":
            eid = a.get("emoji-id") or ""
            if not eid.isdigit():
                return
            extra = f' emoji-id="{eid}"'
        elif tag == "span":
            if a.get("class") != "tg-spoiler":
                return
            extra = ' class="tg-spoiler"'
        self.out.append(f"<{tag}{extra}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack:
                top = self.stack.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        self.out.append(html.escape(data))

    def result(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize(text):
    p = _Sanitizer()
    p.feed(text or "")
    p.close()
    return p.result()


# ======================= проверка пользователя (initData) =======================
def check_init_data(raw, token=None):
    """Проверка подписи Telegram.WebApp.initData. -> dict пользователя или None."""
    try:
        data = dict(parse_qsl(raw or "", keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    sign = data.pop("hash", None)
    if not sign:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", (token or config.BOT_TOKEN).encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, sign):
        return None
    try:
        if time.time() - int(data.get("auth_date", "0")) > 86400:
            return None
        user = json.loads(data.get("user") or "{}")
    except (ValueError, TypeError):
        return None
    return user if isinstance(user, dict) and isinstance(user.get("id"), int) else None


def jerr(code, msg, status=400, **extra):
    return web.json_response({"ok": False, "error": code, "message": msg, **extra}, status=status)


@web.middleware
async def api_auth(request, handler):
    if not request.path.startswith("/api/") or request.path == "/api/emoji":
        return await handler(request)
    tg = check_init_data(request.headers.get("X-Init-Data"))
    if not tg:
        return jerr("auth", "Откройте магазин из Telegram", 401)
    uid = tg["id"]
    row = db.get_user(uid)
    if row is None:
        lang = "ru" if (tg.get("language_code") or "ru")[:2] in ("ru", "uk", "be", "kk") else "en"
        db.create_user(uid, tg.get("username"), tg.get("first_name"), lang)
        row = db.get_user(uid)
    elif row["username"] != tg.get("username") or row["first_name"] != tg.get("first_name"):
        db.update_user(uid, username=tg.get("username"), first_name=tg.get("first_name"))
        row = db.get_user(uid)
    lang = row["lang"] or "ru"
    is_admin = admins.is_admin(uid)
    if db.get_setting("maint") == "1" and not is_admin:
        return jerr("maint", _plain(t("maint", lang)), 503)
    if row["banned"] and not is_admin:
        return jerr("banned", t("banned", lang), 403)
    if not is_admin and request.path != "/api/agree":
        from ui import has_docs
        if db.get_setting("terms_gate") == "1" and has_docs() and not row["agreed"]:
            return jerr("agree", _plain(t("agree_prompt", lang)), 403, docs=_docs_links())
        import subscription
        need = await subscription.missing(_bot, uid)
        if need:
            return jerr("sub", _plain(t("sub_prompt", lang)), 403,
                        channels=[{"title": c["title"], "url": c["url"]} for c in need])
    request["user"] = row
    request["tg"] = tg
    request["lang"] = lang
    return await handler(request)


def _plain(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _docs_links():
    out = []
    for name in ("terms", "privacy"):
        if doc_text(name):
            link = doc_link(name)
            out.append({"name": DOCS[name], "url": link})
    return out


# ======================= медиа из Telegram =======================
def media_sig(file_id):
    return hmac.new(config.BOT_TOKEN.encode(), file_id.encode(), hashlib.sha256).hexdigest()[:20]


def media_url(file_id, kind="photo"):
    if not file_id:
        return None
    return {"url": f"m/{media_sig(file_id)}/{quote(file_id, safe='')}", "type": kind or "photo"}


_locks = {}
EXT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
             ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
             ".json": "application/json", ".tgs": "application/json"}


def _cached(prefix):
    if not os.path.isdir(CACHE):
        return None
    for name in os.listdir(CACHE):
        if name.startswith(prefix + "."):
            return os.path.join(CACHE, name)
    return None


async def _fetch_tg_file(file_id, key):
    """Скачивает файл из Telegram в кеш (один раз). -> путь к файлу."""
    path = _cached(key)
    if path:
        return path
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        path = _cached(key)
        if path:
            return path
        f = await _bot.get_file(file_id)
        if f.file_size and f.file_size > MAX_MEDIA:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_MEDIA, actual_size=f.file_size)
        ext = os.path.splitext(f.file_path or "")[1].lower() or ".bin"
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, key + ext)
        await _bot.download_file(f.file_path, destination=path + ".part")
        os.replace(path + ".part", path)
        return path


def _file_response(path):
    ext = os.path.splitext(path)[1].lower()
    resp = web.FileResponse(path, headers={"Cache-Control": "public, max-age=604800"})
    if ext in EXT_TYPES:
        resp.content_type = EXT_TYPES[ext]
    return resp


async def tg_media(request):
    file_id = request.match_info["fid"]
    if not hmac.compare_digest(media_sig(file_id), request.match_info["sig"]):
        raise web.HTTPForbidden()
    key = hashlib.sha1(file_id.encode()).hexdigest()
    try:
        path = await _fetch_tg_file(file_id, key)
    except web.HTTPException:
        raise
    except Exception as e:
        log.warning("медиа %s не скачалось: %s", file_id[:20], e)
        raise web.HTTPNotFound()
    return _file_response(path)


# ---------- премиум-эмодзи ----------
_emoji_meta = {}


async def _emoji_info(ids):
    """id -> {"type": lottie|video|image, "url", "thumb"} (скачивает и кеширует файлы стикеров)."""
    need = [i for i in ids if i not in _emoji_meta]
    if need and _bot:
        try:
            stickers = await _bot.get_custom_emoji_stickers(custom_emoji_ids=need[:200])
        except Exception as e:
            log.info("не получил премиум-эмодзи: %s", e)
            stickers = []
        for st in stickers:
            eid = st.custom_emoji_id
            try:
                key = "e" + eid
                path = await _fetch_tg_file(st.file_id, key)
                if st.is_animated and not path.endswith(".json"):  # .tgs — это lottie в gzip
                    with open(path, "rb") as f:
                        raw = gzip.decompress(f.read())
                    new = os.path.join(CACHE, key + ".json")
                    with open(new, "wb") as f:
                        f.write(raw)
                    os.remove(path)
                    path = new
                thumb = None
                if st.is_video and st.thumbnail:
                    tpath = await _fetch_tg_file(st.thumbnail.file_id, "t" + eid)
                    thumb = "ef/" + os.path.basename(tpath)
                kind = "lottie" if st.is_animated else "video" if st.is_video else "image"
                _emoji_meta[eid] = {"type": kind, "url": "ef/" + os.path.basename(path), "thumb": thumb}
            except Exception as e:
                log.info("премиум-эмодзи %s не скачалось: %s", eid, e)
    return {i: _emoji_meta[i] for i in ids if i in _emoji_meta}


async def api_emoji(request):
    ids = [i for i in (request.query.get("ids") or "").split(",") if i.isdigit()][:200]
    return web.json_response(await _emoji_info(ids), headers={"Cache-Control": "public, max-age=3600"})


async def emoji_file(request):
    name = request.match_info["name"]
    if not re.fullmatch(r"[et]\d+\.[a-z0-9]+", name):
        raise web.HTTPNotFound()
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        raise web.HTTPNotFound()
    return _file_response(path)


# ======================= данные для мини-приложения =======================
def _txt(key, lang):
    return sanitize(t(key, lang))


def _icon_id(text):
    m = re.search(r'<tg-emoji emoji-id="(\d+)"', text or "")
    return m.group(1) if m else None


def _days_since(joined):
    try:
        from datetime import datetime
        return max((datetime.now() - datetime.strptime((joined or "")[:19], "%Y-%m-%d %H:%M:%S")).days, 0)
    except ValueError:
        return 0


def user_block(u, tg, lang):
    cur, nxt, pct, left = appcfg.user_status(u)
    me_username = getattr(_bot_me, "username", "") if _bot_me else ""
    paid = "status IN ('done','manual')"
    return {
        "id": u["id"], "username": u["username"], "first_name": u["first_name"], "photo_url": (tg or {}).get("photo_url"),
        "lang": lang, "balance": round(u["balance"], 2), "deposited": round(u["deposited"] or 0, 2),
        "status": cur, "next": nxt, "pct": pct, "left": left,
        "disc": appcfg.disc_of(cur), "next_disc": appcfg.disc_of(nxt) if nxt else None,
        "orders_30d": db.val(f"SELECT COUNT(*) FROM orders WHERE user_id=? AND {paid} "
                             "AND created >= datetime('now','localtime','-30 days')", (u["id"],)),
        "spent": round(db.val(f"SELECT COALESCE(SUM(price),0) FROM orders WHERE user_id=? AND {paid}", (u["id"],)) or 0, 2),
        "days": _days_since(u["joined"]),
        "bonus_left": appcfg.bonus_left(u), "orders": db.count_user_orders(u["id"]), "joined": fdate(u["joined"]),
        "promo": {"code": u["promo_code"], "pct": u["promo_percent"]} if u["promo_percent"] else None,
        "ref": {"link": f"https://t.me/{me_username}?start=ref_{u['id']}" if me_username else "",
                "invited": db.count_refs(u["id"]), "earned": round(u["ref_earned"], 2),
                "available": round(u["ref_balance"], 2), "pct": db.get_setting("ref_percent", config.REF_PERCENT)},
        "is_admin": admins.is_admin(u["id"]),
    }


def cat_block(c):
    return {"id": c["id"], "name": c["name"], "emoji_id": c["emoji_id"], "count": db.count_in_category(c["id"]),
            "media": media_url(c["photo"], c["media_type"]) if c["photo"] else None}


def product_block(p, u=None):
    from handlers.shop import in_stock, min_qty, stars_ok
    unlimited = db.unlimited(p)
    available = in_stock(p)
    out = {"id": p["id"], "name": p["name"], "emoji_id": p["emoji_id"], "price": p["price"],
           "old_price": p["old_price"] if p["old_price"] and p["old_price"] > p["price"] else 0,
           "stock": 0 if not available else -1 if unlimited else db.stock(p["id"]), "cat": p["category_id"],
           "out": not available, "min_qty": min_qty(p), "by_qty": bool(p["min_qty"]), "stars": stars_ok(p),
           "media": media_url(p["photo"], p["media_type"]) if p["photo"] else None}
    return out


_bot_me = None


async def api_boot(request):
    u, lang = request["user"], request["lang"]
    sup = db.suppliers_cid()
    cats = [cat_block(c) for c in db.categories() if c["id"] != sup and db.count_in_category(c["id"])]
    s = appcfg.season()
    shop = {
        # название и бейдж — HTML с премиум-эмодзи (очищенный), title_plain — для заголовка вкладки
        "title": sanitize(appcfg.card_title()), "title_plain": re.sub(r"<[^>]+>", "", appcfg.card_title()),
        "name": config.SHOP_NAME, "season": s, "badge": sanitize(appcfg.badge(lang, s)),
        "accent": appcfg.accent(), "theme": appcfg.theme(), "fx": appcfg.fx_on(),
        "bg": media_url(db.get_setting("app_bg"), db.get_setting("app_bg_type")),
        "logo": media_url(db.get_setting("app_logo"), "photo"),
        "wall": media_url(db.get_setting("app_wall"), "photo"),
        "icons": appcfg.icons(), "texts": {k: _txt(k, lang) for k in APP_TEXTS},
        "statuses": appcfg.statuses(),
        "bonus": {"on": appcfg.bonus_on(), "amount": appcfg.bonus_amount()},
        "topup": {"min": appcfg.topup_min(), "amounts": appcfg.topup_amounts()},
        "star_rate": float(db.get_setting("star_rate", config.STAR_RATE) or config.STAR_RATE),
        "bot": getattr(_bot_me, "username", ""),
        "has_suppliers": bool(db.count_in_category(sup)), "suppliers_cid": sup,
        "docs": _docs_links(),
        "pay": {"balance": not _hidden("pay_balance"), "sbp": not _hidden("pay_sbp"), "stars": True,
                "cryptobot": crypto.enabled("cryptobot") and not _hidden("pay_cryptobot"),
                "xrocket": crypto.enabled("xrocket") and not _hidden("pay_xrocket")},
    }
    return web.json_response({"ok": True, "shop": shop, "user": user_block(u, request["tg"], lang), "cats": cats})


def _hidden(key):
    return db.get_setting(f"bh:{key}") == "1"


async def api_me(request):
    u = db.get_user(request["user"]["id"])
    return web.json_response({"ok": True, "user": user_block(u, request["tg"], request["lang"])})


async def api_list(request):
    kind = request.query.get("kind", "all")
    if not (kind in ("all", "fav", "srch") or re.fullmatch(r"c\d+", kind)):
        return jerr("kind", "bad kind")
    if kind == "all":   # все товары витрины, кроме поставщиков
        sup = db.suppliers_cid()
        items = [p for p in db.q("SELECT * FROM products WHERE active=1 ORDER BY category_id, id")
                 if p["category_id"] != sup]
    else:
        items = db.products_by(kind, request["user"]["id"], request.query.get("q", "")[:64])
    return web.json_response({"ok": True, "items": [product_block(p) for p in items[:200]]})


async def api_product(request):
    from handlers.shop import final_price, is_multi, max_qty
    pid = int(request.match_info["pid"])
    p = db.product(pid)
    u = request["user"]
    is_admin = admins.is_admin(u["id"])
    if not p or (not p["active"] and not is_admin):
        return jerr("not_found", t("not_found", request["lang"]), 404)
    db.add_view(u["id"], pid)
    out = product_block(p)
    fp, pct, code = final_price(u, p["price"])
    cat = db.category(p["category_id"])
    out.update(description=sanitize(p["description"]), multi=is_multi(p), max_qty=max_qty(p),
               fav=db.is_fav(u["id"], pid), promo_price=fp if pct else None, promo_pct=pct,
               cat_name=cat["name"] if cat else "")
    if is_admin:  # для редактора в мини-приложении
        out.update(raw_description=p["description"] or "", kind=p["kind"], active=bool(p["active"]),
                   base_price=p["old_price"] if p["old_price"] and p["old_price"] > p["price"] else p["price"])
    return web.json_response({"ok": True, "product": out})


async def _json(request):
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


async def api_fav(request):
    pid = int((await _json(request)).get("pid") or 0)
    if not db.product(pid):
        return jerr("not_found", "not found", 404)
    return web.json_response({"ok": True, "fav": db.toggle_fav(request["user"]["id"], pid)})


async def api_notify(request):
    pid = int((await _json(request)).get("pid") or 0)
    if db.product(pid):
        db.add_notify(request["user"]["id"], pid)
    return web.json_response({"ok": True, "message": t("notify_on", request["lang"])})


async def api_buy(request):
    from handlers.shop import check_buyable, stars_for, total_price
    from services import fulfill
    data = await _json(request)
    lang = request["lang"]
    try:
        pid, qty = int(data.get("pid") or 0), max(int(data.get("qty") or 1), 1)
    except (TypeError, ValueError):
        return jerr("bad", "bad request")
    method = data.get("method")
    p = db.product(pid)
    err = check_buyable(p, qty)
    if err:
        return jerr(err, t(err, lang, min=p["min_qty"] if p else 1), 409)
    uid = request["user"]["id"]
    db.release_promo_orders(uid)
    u = db.get_user(uid)
    price, _, code = total_price(u, p, qty)
    name = p["name"] + (f" × {qty}" if qty > 1 else "")
    if method == "balance":
        if _hidden("pay_balance"):
            return jerr("method", "method off")
        if u["balance"] < price:
            return jerr("no_money", t("no_money", lang), 402, need=round(price - u["balance"], 2))
        db.add_balance(uid, -price)
        oid = db.create_order(uid, p, price, "balance", "paid", code, qty)
        if code:
            db.consume_promo(uid)
        res = await fulfill(_bot, oid)
        o = db.order(oid)
        return web.json_response({"ok": True, "oid": oid, "result": res, "content": o["content"] if res == "done" else None,
                                  "status": order_status(o["status"], lang)})
    if method == "stars":
        if p["no_stars"]:
            return jerr("method", t("stars_off", lang))
        oid = db.create_order(uid, p, price, "stars", "wait_pay", code, qty)
        if code:
            db.consume_promo(uid)
        from aiogram.types import LabeledPrice
        link = await _bot.create_invoice_link(
            title=name[:32], description=t("stars_desc", lang, oid=oid, name=name)[:255], payload=f"o:{oid}",
            currency="XTR", prices=[LabeledPrice(label=name[:32], amount=stars_for(price))])
        return web.json_response({"ok": True, "oid": oid, "invoice": link})
    if method == "sbp":
        if _hidden("pay_sbp"):
            return jerr("method", "method off")
        from ui import btn, kb
        oid = db.create_order(uid, p, price, "sbp", "wait_pay", code, qty)
        if code:
            db.consume_promo(uid)
        text = t("sbp_text", lang, oid=oid, name=html.escape(name), price=money(price),
                 details=db.get_setting("sbp_details", config.SBP_DETAILS))
        await _bot.send_message(uid, text, reply_markup=kb([[btn("paid", lang, f"paid:{oid}")],
                                                            [btn("cancel", lang, f"oc:{oid}")]]))
        return web.json_response({"ok": True, "oid": oid, "sbp": True, "message": t("sbp_in_chat", lang)})
    if method in crypto.SERVICES:
        if not crypto.enabled(method):
            return jerr("method", t("crypto_off", lang))
        oid = db.create_order(uid, p, price, method, "wait_pay", code, qty)
        try:
            inv, extra = await crypto.create("order", oid, uid, method, price, t("stars_desc", lang, oid=oid, name=name))
        except crypto.CryptoError as e:
            logging.warning("crypto invoice for order %s: %s", oid, e)
            db.set_order(oid, status="canceled")
            return jerr("crypto", t("crypto_error", lang), 502)
        if code:
            db.consume_promo(uid)
        return web.json_response({"ok": True, "oid": oid, "crypto": {"id": inv["id"], "url": inv["url"],
                                                                     "service": crypto.SERVICES[method], "extra": extra}})
    return jerr("method", "unknown method")


async def api_crypto_check(request):
    """Мини-приложение спрашивает, оплачен ли крипто-счёт."""
    iid = int((await _json(request)).get("id") or 0)
    res = await crypto.check(_bot, iid, request["user"]["id"])
    return web.json_response({"ok": True, "status": res,
                              "user": user_block(db.get_user(request["user"]["id"]), request["tg"], request["lang"])})


async def api_bonus(request):
    u, lang = request["user"], request["lang"]
    if not appcfg.bonus_on():
        return jerr("off", t("bonus_off", lang), 409)
    got = appcfg.claim_bonus(u["id"])
    if got is None:
        left = appcfg.bonus_left(db.get_user(u["id"]))
        return jerr("wait", t("bonus_wait", lang, left=appcfg.fmt_left(left, lang)), 409, left=left)
    return web.json_response({"ok": True, "amount": got, "message": _plain(t("bonus_ok", lang, amount=money(got))),
                              "user": user_block(db.get_user(u["id"]), request["tg"], lang)})


async def api_topup(request):
    from handlers.admin import parse_amount
    from handlers.topup import start_sbp, stars_link, valid_amount
    data = await _json(request)
    lang = request["lang"]
    amount = parse_amount(str(data.get("amount") or ""))
    if not valid_amount(amount):
        return jerr("amount", _plain(t("topup_bad", lang, min=money(appcfg.topup_min()))))
    uid = request["user"]["id"]
    if data.get("method") == "stars":
        return web.json_response({"ok": True, "invoice": await stars_link(_bot, uid, amount, lang)})
    if data.get("method") == "sbp":
        if _hidden("pay_sbp"):
            return jerr("method", "method off")
        await start_sbp(_bot, uid, amount, lang)
        return web.json_response({"ok": True, "sbp": True, "message": t("sbp_in_chat", lang)})
    method = data.get("method")
    if method in crypto.SERVICES:
        if not crypto.enabled(method):
            return jerr("method", t("crypto_off", lang))
        from handlers.cryptopay import start_topup
        inv, extra, _ = await start_topup(uid, amount, method, lang)
        if not inv:
            return jerr("crypto", t("crypto_error", lang), 502)
        return web.json_response({"ok": True, "crypto": {"id": inv["id"], "url": inv["url"],
                                                         "service": crypto.SERVICES[method], "extra": extra}})
    return jerr("method", "unknown method")


async def api_orders(request):
    lang = request["lang"]
    out = []
    for o in db.user_orders(request["user"]["id"])[:100]:
        out.append({"id": o["id"], "name": o["product_name"], "price": o["price"], "status": o["status"],
                    "status_text": order_status(o["status"], lang), "date": fdate(o["created"]) + " " + o["created"][11:16],
                    "method": o["method"], "content": o["content"]})
    return web.json_response({"ok": True, "items": out})


async def api_promo(request):
    lang = request["lang"]
    code = str((await _json(request)).get("code") or "").strip()[:32]
    p = db.promo(code) if code else None
    uid = request["user"]["id"]
    if not p or p["used"] >= p["max_uses"]:
        return jerr("bad", _plain(t("promo_bad", lang)), 409)
    if db.promo_used_by(p["code"], uid):
        return jerr("used", _plain(t("promo_used", lang)), 409)
    db.use_promo(p["code"], uid)
    db.update_user(uid, promo_code=p["code"], promo_percent=p["percent"])
    return web.json_response({"ok": True, "message": _plain(t("promo_ok", lang, code=p["code"], pct=p["percent"])),
                              "user": user_block(db.get_user(uid), request["tg"], lang)})


async def api_lang(request):
    lang = "en" if (await _json(request)).get("lang") == "en" else "ru"
    db.update_user(request["user"]["id"], lang=lang)
    return web.json_response({"ok": True})


async def api_agree(request):
    db.update_user(request["user"]["id"], agreed=1)
    return web.json_response({"ok": True})


# ======================= админ-режим в мини-приложении =======================
# Админ прямо в приложении меняет карточки товаров (фото/видео/GIF, премиум-эмодзи, название, цены, описание),
# категории (обложка, эмодзи, название) и главную карточку (название, фон, логотип).
# Файлы загружаются в Telegram (отправкой самому админу с удалением сообщения) — так у них появляется file_id,
# как у медиа, присланных боту в чат.
MAX_UPLOAD = 45 * 1024 * 1024


def _admin_only(request):
    if not admins.is_admin(request["user"]["id"]):
        raise web.HTTPForbidden(text="admins only")


def _num(v, allow_none=False):
    if v in (None, "") and allow_none:
        return None
    try:
        x = round(float(str(v).replace(",", ".")), 2)
    except ValueError:
        raise web.HTTPBadRequest(text="bad number")
    if x < 0 or x != x:
        raise web.HTTPBadRequest(text="bad number")
    return x


def _emoji_id(v):
    v = str(v or "").strip()
    return v if v.isdigit() else None


async def api_admin_product(request):
    _admin_only(request)
    pid = int(request.match_info["pid"])
    p = db.product(pid)
    if not p:
        return jerr("not_found", "Товар не найден", 404)
    d = await _json(request)
    kw = {}
    if "name" in d:
        name = str(d["name"] or "").strip()[:100]
        if not name:
            return jerr("name", "Название не может быть пустым")
        kw["name"] = name
    if "emoji_id" in d:
        kw["emoji_id"] = _emoji_id(d["emoji_id"])
    if "description" in d:
        kw["description"] = str(d["description"] or "")[:4000]
    if "active" in d:
        kw["active"] = 1 if d["active"] else 0
    if "price" in d and p["kind"] != "ext":
        price = _num(d["price"])
        old = _num(d.get("old_price"), allow_none=True) or 0
        kw["price"], kw["old_price"] = price, old if old > price else 0
    if kw:
        db.update_product(pid, **kw)
    return web.json_response({"ok": True})


async def api_admin_category(request):
    _admin_only(request)
    cid = int(request.match_info["cid"])
    if not db.category(cid):
        return jerr("not_found", "Категория не найдена", 404)
    d = await _json(request)
    kw = {}
    if "name" in d and str(d["name"] or "").strip():
        kw["name"] = str(d["name"]).strip()[:60]
    if "emoji_id" in d:
        kw["emoji_id"] = _emoji_id(d["emoji_id"])
    if kw:
        db.update_category(cid, **kw)
    return web.json_response({"ok": True})


async def api_admin_app(request):
    _admin_only(request)
    d = await _json(request)
    if "title" in d:
        title = str(d["title"] or "").strip()[:40]
        db.set_setting("app_title", title or None)
    return web.json_response({"ok": True})


def _set_media(target, ident, file_id, kind):
    if target == "product":
        db.update_product(ident, photo=file_id, media_type=kind if file_id else None)
    elif target == "category":
        db.update_category(ident, photo=file_id, media_type=kind if file_id else None)
    elif target in ("app_bg", "app_logo", "app_wall"):
        db.set_setting(target, file_id)
        db.set_setting(f"{target}_type", kind if file_id else None)
    else:
        raise web.HTTPBadRequest(text="bad target")


async def _empty():
    return
    yield


async def api_admin_media(request):
    """Загрузка фото / видео / GIF на товар, категорию или главную карточку (multipart: target, id, file)."""
    _admin_only(request)
    from aiogram.types import BufferedInputFile
    fields, data, ctype, fname = {}, None, "", "file"
    if not request.content_type.startswith("multipart/"):  # без файла (удаление) форма может прийти обычной
        fields = {k: str(v)[:50] for k, v in (await request.post()).items()}
    reader = await request.multipart() if request.content_type.startswith("multipart/") else None
    async for part in (reader or _empty()):
        if part.name == "file":
            ctype = (part.headers.get("Content-Type") or "").lower()
            fname = part.filename or "file"
            data = await part.read(decode=False)
            if len(data) > MAX_UPLOAD:
                return jerr("big", "Файл больше 45 МБ")
        else:
            fields[part.name] = (await part.text())[:50]
    target = fields.get("target", "")
    ident = int(fields["id"]) if fields.get("id", "").isdigit() else 0
    if target in ("product", "category") and not (db.product(ident) if target == "product" else db.category(ident)):
        return jerr("not_found", "Не найдено", 404)
    if fields.get("remove") == "1":
        _set_media(target, ident, None, None)
        return web.json_response({"ok": True, "media": None})
    if not data:
        return jerr("file", "Файл не получен")
    if target in ("app_logo", "app_wall") and not ctype.startswith("image/"):
        return jerr("type", "Здесь нужна картинка")
    uid = request["user"]["id"]
    try:
        f = BufferedInputFile(data, fname)
        if ctype == "image/gif":
            kind, msg = "animation", await _bot.send_animation(uid, f, disable_notification=True)
            fid = msg.animation.file_id if msg.animation else msg.document.file_id
        elif ctype.startswith("image/"):
            kind, msg = "photo", await _bot.send_photo(uid, f, disable_notification=True)
            fid = msg.photo[-1].file_id
        elif ctype.startswith("video/"):
            kind, msg = "video", await _bot.send_video(uid, f, disable_notification=True, supports_streaming=True)
            fid = msg.video.file_id
        else:
            return jerr("type", "Нужно фото, видео или GIF")
    except Exception as e:
        log.warning("загрузка медиа из мини-приложения не удалась: %s", e)
        return jerr("upload", f"Telegram не принял файл: {e}")
    try:
        await _bot.delete_message(uid, msg.message_id)  # служебное сообщение админу не нужно
    except Exception:
        pass
    _set_media(target, ident, fid, kind)
    return web.json_response({"ok": True, "media": media_url(fid, kind)})


def _pack_name(raw):
    raw = (raw or "").strip()
    m = re.search(r"(?:addemoji|addstickers)/([A-Za-z0-9_]+)", raw)
    name = m.group(1) if m else raw
    return name if re.fullmatch(r"[A-Za-z0-9_]{1,64}", name) else None


def _used_emoji():
    """Премиум-эмодзи, которые уже есть в магазине (товары, категории, иконки, статусы)."""
    ids = []
    for r in db.q("SELECT emoji_id FROM products WHERE emoji_id IS NOT NULL UNION SELECT emoji_id FROM categories "
                  "WHERE emoji_id IS NOT NULL"):
        ids.append(r[0])
    for r in db.q("SELECT value FROM settings WHERE key LIKE 'ai:%' OR key LIKE 'bi:%'"):
        ids.append(r[0])
    for s in appcfg.statuses():
        if s.get("emoji_id"):
            ids.append(s["emoji_id"])
    for r in db.q("SELECT description FROM products WHERE description LIKE '%emoji-id%'"):
        ids += re.findall(r'emoji-id="(\d+)"', r[0] or "")
    seen, out = set(), []
    for i in ids:
        if i and str(i).isdigit() and i not in seen:
            seen.add(i)
            out.append({"id": str(i), "e": "⭐"})
    return out[:120]


async def api_admin_emoji(request):
    """Наборы премиум-эмодзи для выбора в мини-приложении. ?pack=ссылка — добавить набор."""
    _admin_only(request)
    packs = [p for p in (db.get_setting("app_emoji_packs") or "").split(",") if p]
    want = request.query.get("pack")
    if want:
        name = _pack_name(want)
        if not name:
            return jerr("pack", "Пришлите ссылку вида t.me/addemoji/НАЗВАНИЕ")
        try:
            await _bot.get_sticker_set(name=name)
        except Exception:
            return jerr("pack", "Не нашёл такой набор эмодзи")
        packs = [name] + [p for p in packs if p != name]
        db.set_setting("app_emoji_packs", ",".join(packs[:12]))
    out = [{"name": "used", "title": "В магазине", "items": _used_emoji()}]
    for name in packs[:12]:
        try:
            st = await _bot.get_sticker_set(name=name)
        except Exception:
            continue
        items = [{"id": s.custom_emoji_id, "e": s.emoji or "⭐"} for s in st.stickers if s.custom_emoji_id]
        out.append({"name": name, "title": st.title, "items": items[:200]})
    return web.json_response({"ok": True, "packs": out})


async def api_admin_pack_del(request):
    _admin_only(request)
    name = str((await _json(request)).get("name") or "")
    packs = [p for p in (db.get_setting("app_emoji_packs") or "").split(",") if p and p != name]
    db.set_setting("app_emoji_packs", ",".join(packs) or None)
    return web.json_response({"ok": True})


# ======================= мини-приложение и боты клиентов =======================
async def app_page(request):
    path = os.path.join(STATIC, "index.html")
    with open(path, encoding="utf-8") as f:
        body = f.read()
    return web.Response(text=body, content_type="text/html", charset="utf-8",
                        headers={"Cache-Control": "no-cache"})


_proxy_session = None
HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "host"}


async def child_proxy(request):
    """/b/<номер>/... -> бот клиента на 127.0.0.1:<порт>. У каждого бота свой магазин, своя подпись initData."""
    global _proxy_session
    import hosting
    bid = int(request.match_info["bid"])
    b = db.hosted(bid)
    if not b or b["status"] != "running":
        raise web.HTTPNotFound(text="bot is not running")
    tail = request.match_info["tail"]
    url = f"http://127.0.0.1:{hosting.child_port(bid)}/{tail}"
    if _proxy_session is None or _proxy_session.closed:
        _proxy_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60), auto_decompress=False)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    body = await request.read() if request.can_read_body else None
    try:
        async with _proxy_session.request(request.method, url, params=request.query, headers=headers, data=body,
                                          allow_redirects=False) as r:
            data = await r.read()
            out = {k: v for k, v in r.headers.items() if k.lower() not in HOP}
            return web.Response(status=r.status, body=data, headers=out)
    except aiohttp.ClientError:
        raise web.HTTPBadGateway(text="bot is starting, try again")


async def start(bot=None):
    """Запускает сайт рядом с ботом. Если порт занят или недоступен — просто пишет предупреждение."""
    global _bot, _bot_me
    _bot = bot
    if bot:
        try:
            _bot_me = await bot.me()
        except Exception:
            _bot_me = None
    app = web.Application(middlewares=[api_auth], client_max_size=MAX_UPLOAD + 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/app", app_page)
    app.router.add_get("/app/", app_page)
    app.router.add_get("/{name:privacy|terms}", page)
    app.router.add_get("/m/{sig}/{fid}", tg_media)
    app.router.add_get("/ef/{name}", emoji_file)
    app.router.add_get("/api/emoji", api_emoji)
    app.router.add_get("/api/boot", api_boot)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/list", api_list)
    app.router.add_get("/api/product/{pid:\\d+}", api_product)
    app.router.add_get("/api/orders", api_orders)
    for path, fn in (("fav", api_fav), ("notify", api_notify), ("buy", api_buy), ("bonus", api_bonus),
                     ("topup", api_topup), ("promo", api_promo), ("lang", api_lang), ("agree", api_agree),
                     ("crypto_check", api_crypto_check)):
        app.router.add_post(f"/api/{path}", fn)
    app.router.add_post("/api/admin/product/{pid:\\d+}", api_admin_product)
    app.router.add_post("/api/admin/category/{cid:\\d+}", api_admin_category)
    app.router.add_post("/api/admin/app", api_admin_app)
    app.router.add_post("/api/admin/media", api_admin_media)
    app.router.add_get("/api/admin/emoji", api_admin_emoji)
    app.router.add_post("/api/admin/pack_del", api_admin_pack_del)
    if not config.CHILD:
        app.router.add_route("*","/b/{bid:\\d+}/{tail:.*}", child_proxy)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, config.WEB_HOST, config.WEB_PORT).start()
    except OSError as e:
        log.warning("сайт бота не запущен (порт %s): %s", config.WEB_PORT, e)
        await runner.cleanup()
        return None
    log.info("сайт бота (мини-приложение и документы): порт %s", config.WEB_PORT)
    return runner


async def setup_menu_button(bot):
    """Кнопка «Магазин» слева от поля ввода в чате с ботом открывает мини-приложение."""
    from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo
    from texts import bt
    url = appcfg.app_url()
    try:
        if url:
            label = re.sub(r"^[^\w]+", "", bt("shop", "ru")).strip()[:16] or "Магазин"
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text=label, web_app=WebAppInfo(url=url)))
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
    except Exception as e:
        log.info("кнопку меню не установил: %s", e)
