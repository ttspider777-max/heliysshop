"""Подключение внешних магазинов по API: импорт их товаров с наценкой и перепродажа.

Коннектор универсальный: ожидает JSON-API. Адреса методов, способ авторизации и тело запроса покупки
настраиваются для каждого магазина в админ-панели (🔌 Внешние магазины), а ответы разбираются «на лету»:
список товаров ищется в корне или в ключах data / products / items / result, поля — по частым названиям
(id, name/title, price/cost, stock/count/quantity, description).
"""
import asyncio
import json
import logging
import re

import aiohttp

import db

log = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=25)
MAX_BODY = 5_000_000
SYNC_EVERY = 600  # секунд между автообновлением остатков и цен

DEFAULT_BUY_BODY = '{"product_id": "$id", "quantity": "$qty"}'
AUTH_MODES = ("bearer", "header", "query")
AUTH_TITLES = {"bearer": "Authorization: Bearer КЛЮЧ", "header": "заголовок (X-Api-Key)", "query": "параметр в URL (?api_key=)"}
AUTH_DEFAULT_NAME = {"header": "X-Api-Key", "query": "api_key"}

LIST_KEYS = ("data", "products", "items", "result", "goods", "list", "response", "offers")
ITEM_KEYS = ("items", "accounts", "goods", "codes", "keys", "content", "data", "result", "order", "numbers", "values")
TEXT_KEYS = ("content", "data", "value", "account", "text", "code", "key", "credentials", "item")


class ExtError(Exception):
    pass


# ---------- HTTP ----------
def _url(shop, path):
    path = (path or "").strip()
    if re.match(r"^https?://", path):
        return path
    return shop["base_url"].rstrip("/") + "/" + path.lstrip("/")


def _auth(shop):
    headers, params = {}, {}
    key = shop["api_key"] or ""
    mode = shop["auth_mode"] or "bearer"
    name = shop["auth_name"] or AUTH_DEFAULT_NAME.get(mode, "")
    if key:
        if mode == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        elif mode == "header":
            headers[name] = key
        elif mode == "query":
            params[name] = key
    return headers, params


async def request(shop, method, path, body=None):
    if not re.match(r"^https?://", shop["base_url"] or ""):
        raise ExtError("Адрес магазина должен начинаться с http:// или https://")
    headers, params = _auth(shop)
    headers["Accept"] = "application/json"
    method = (method or "GET").upper()
    kw = {"headers": headers}
    if method == "GET":
        params.update({k: str(v) for k, v in (body or {}).items()})
    else:
        kw["json"] = body or {}
    kw["params"] = params
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.request(method, _url(shop, path), **kw) as r:
                raw = await r.content.read(MAX_BODY)
                text = raw.decode("utf-8", errors="replace")
                if r.status >= 400:
                    raise ExtError(f"HTTP {r.status}: {text[:300]}")
    except asyncio.TimeoutError:
        raise ExtError("Магазин не ответил за 25 секунд")
    except aiohttp.ClientError as e:
        raise ExtError(f"Нет соединения: {e}")
    try:
        return json.loads(text)
    except ValueError:
        raise ExtError(f"Ответ не в формате JSON: {text[:200]}")


# ---------- разбор ответов ----------
def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ".").replace(" ", "").rstrip("₽руб.$").strip())
        except ValueError:
            return None
    return None


def extract_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in LIST_KEYS:
            v = data.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = extract_list(v)
                if inner:
                    return inner
        vals = list(data.values())
        if vals and all(isinstance(v, dict) for v in vals):  # {"12": {...}, "13": {...}}
            return [{"id": k, **v} if "id" not in v else v for k, v in data.items()]
    return []


def parse_product(raw):
    """Сырой товар из ответа -> {id, name, cost, stock, description} или None, если это не похоже на товар."""
    if not isinstance(raw, dict):
        return None
    pid = _first(raw, ("id", "product_id", "pid", "sku", "uuid", "code"))
    name = _first(raw, ("name", "title", "product_name", "product"))
    cost = _num(_first(raw, ("price", "cost", "amount", "price_rub", "sum")))
    if pid is None or not isinstance(name, str) or cost is None:
        return None
    stock = None
    for k in ("stock", "count", "quantity", "available", "in_stock", "qty", "left", "amount_available"):
        if k in raw:
            v = raw[k]
            if isinstance(v, bool):
                stock = 1000 if v else 0
            elif _num(v) is not None:
                stock = int(_num(v))
            if stock is not None:
                break
    desc = _first(raw, ("description", "desc", "info", "about", "text"))
    return {"id": str(pid), "name": name.strip()[:100], "cost": cost,
            "stock": -1 if stock is None else max(stock, 0),  # -1 — магазин остаток не сообщает
            "description": desc.strip() if isinstance(desc, str) else ""}


def extract_items(data):
    """Выданные покупкой позиции (логины, ключи, номера) из ответа магазина -> список строк."""
    if isinstance(data, dict):
        if data.get("success") is False or data.get("ok") is False or str(data.get("status", "")).lower() in ("error", "fail", "failed"):
            raise ExtError(str(_first(data, ("message", "error", "detail", "msg")) or json.dumps(data, ensure_ascii=False))[:300])
        for k in ITEM_KEYS:
            if k in data:
                found = extract_items(data[k])
                if found:
                    return found
        return []
    if isinstance(data, list):
        out = []
        for v in data:
            if isinstance(v, str):
                if v.strip():
                    out.append(v.strip())
            elif isinstance(v, dict):
                s = _first(v, TEXT_KEYS)
                if isinstance(s, str):
                    out.append(s.strip())
                elif v:
                    out.append("\n".join(f"{k}: {val}" for k, val in v.items() if val not in (None, "")))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(str(v))
        return out
    if isinstance(data, str):
        return [data.strip()] if data.strip() else []
    return []


# ---------- операции ----------
async def fetch_products(shop):
    data = await request(shop, "GET", shop["list_path"] or "/products")
    raw = extract_list(data)
    prods = [p for p in (parse_product(r) for r in raw) if p]
    if not prods:
        sample = json.dumps(data, ensure_ascii=False)[:300]
        raise ExtError("В ответе не нашёл список товаров (нужны поля id, название и цена). "
                       f"Ответ магазина: {sample}")
    return prods


def _fill(node, ext_id, qty):
    if isinstance(node, dict):
        return {k: _fill(v, ext_id, qty) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, ext_id, qty) for v in node]
    if node == "$id":
        return int(ext_id) if str(ext_id).isdigit() else ext_id
    if node == "$qty":
        return qty
    return node


async def purchase(shop, p, qty):
    """Покупает у внешнего магазина qty штук товара p. Возвращает список выданных позиций или бросает ExtError."""
    try:
        body = _fill(json.loads(shop["buy_body"] or DEFAULT_BUY_BODY), p["ext_pid"], qty)
    except ValueError:
        raise ExtError("Шаблон запроса покупки — некорректный JSON")
    data = await request(shop, shop["buy_method"] or "POST", shop["buy_path"] or "/buy", body)
    items = extract_items(data)
    if not items:
        raise ExtError(f"Магазин не вернул товар. Ответ: {json.dumps(data, ensure_ascii=False)[:300]}")
    return items


def sell_price(cost, markup):
    return round(cost * (1 + (markup or 0) / 100), 2)


def reprice(sid):
    """Пересчитывает цены товаров магазина после смены наценки (без обращения к API)."""
    shop = db.ext_shop(sid)
    for p in db.ext_products(sid):
        db.update_product(p["id"], price=sell_price(p["ext_price"], shop["markup"]), old_price=0)


def ensure_category(shop):
    cid = shop["category_id"]
    if cid and db.category(cid):
        return cid
    cid = db.add_category(f"🔌 {shop['name']}"[:60])
    db.update_ext_shop(shop["id"], category_id=cid)
    return cid


async def sync_shop(sid):
    """Тянет товары магазина: добавляет новые, обновляет цены и остатки. -> (новых, обновлено, всего)."""
    shop = db.ext_shop(sid)
    try:
        prods = await fetch_products(shop)
    except ExtError as e:
        db.update_ext_shop(sid, last_error=str(e)[:500])
        raise
    cid = ensure_category(shop)
    have = {r["ext_pid"]: r for r in db.ext_products(sid)}
    added = updated = 0
    seen = set()
    for pr in prods:
        seen.add(pr["id"])
        price = sell_price(pr["cost"], shop["markup"])
        row = have.get(pr["id"])
        if row is None:
            db.add_ext_product(sid, cid, pr["id"], pr["name"], pr["description"], pr["cost"], price, pr["stock"])
            added += 1
        else:
            # название и описание админ мог поменять — не трогаем; цену, себестоимость и остаток обновляем
            db.update_product(row["id"], ext_price=pr["cost"], price=price, old_price=0, ext_stock=pr["stock"])
            updated += 1
    for pid_, row in have.items():
        if pid_ not in seen and row["ext_stock"] != 0:
            db.update_product(row["id"], ext_stock=0)
    db.update_ext_shop(sid, last_sync=db.now(), last_error="")
    return added, updated, len(prods)


async def sync_loop():
    """Раз в SYNC_EVERY секунд обновляет остатки и цены у всех включённых магазинов."""
    while True:
        await asyncio.sleep(SYNC_EVERY)
        for shop in db.ext_shops():
            if not shop["active"]:
                continue
            try:
                await sync_shop(shop["id"])
            except Exception as e:
                log.warning("автосинхронизация магазина %s не удалась: %s", shop["name"], e)
