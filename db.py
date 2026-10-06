import os
import sqlite3
from datetime import datetime

from config import DB_PATH

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    lang TEXT DEFAULT 'ru',
    balance REAL DEFAULT 0,
    ref_balance REAL DEFAULT 0,
    ref_earned REAL DEFAULT 0,
    referrer_id INTEGER,
    joined TEXT,
    banned INTEGER DEFAULT 0,
    promo_code TEXT,
    promo_percent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    emoji_id TEXT,
    position INTEGER DEFAULT 0,
    multi INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER,
    name TEXT,
    description TEXT DEFAULT '',
    price REAL DEFAULT 0,
    old_price REAL DEFAULT 0,
    kind TEXT DEFAULT 'auto',
    active INTEGER DEFAULT 1,
    created TEXT,
    emoji_id TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    content TEXT,
    sold INTEGER DEFAULT 0,
    order_id INTEGER
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    product_id INTEGER,
    product_name TEXT,
    price REAL,
    method TEXT,
    status TEXT,
    promo_code TEXT,
    content TEXT,
    receipt TEXT,
    created TEXT,
    qty INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS favorites (user_id INTEGER, product_id INTEGER, PRIMARY KEY (user_id, product_id));
CREATE TABLE IF NOT EXISTS views (user_id INTEGER, product_id INTEGER, ts TEXT, PRIMARY KEY (user_id, product_id));
CREATE TABLE IF NOT EXISTS notify (user_id INTEGER, product_id INTEGER, PRIMARY KEY (user_id, product_id));
CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, percent INTEGER, max_uses INTEGER, used INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS promo_uses (code TEXT, user_id INTEGER, PRIMARY KEY (code, user_id));
CREATE TABLE IF NOT EXISTS withdrawals (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS custom_buttons (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, url TEXT, emoji_id TEXT);
CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, title TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ext_shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    base_url TEXT,
    api_key TEXT DEFAULT '',
    auth_mode TEXT DEFAULT 'bearer',
    auth_name TEXT DEFAULT '',
    list_path TEXT DEFAULT '/products',
    buy_method TEXT DEFAULT 'POST',
    buy_path TEXT DEFAULT '/buy',
    buy_body TEXT DEFAULT '',
    markup REAL DEFAULT 20,
    category_id INTEGER,
    active INTEGER DEFAULT 1,
    last_sync TEXT,
    last_error TEXT DEFAULT '',
    created TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_prod ON items(product_id, sold);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def q(sql, args=()):
    return conn.execute(sql, args).fetchall()


def q1(sql, args=()):
    return conn.execute(sql, args).fetchone()


def val(sql, args=()):
    r = q1(sql, args)
    return r[0] if r else None


def x(sql, args=()):
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def _migrate():
    """Добавляет новые колонки в уже существующую базу."""
    for table, col, ddl in (("categories", "multi", "INTEGER DEFAULT 0"),
                            ("products", "emoji_id", "TEXT"),
                            ("products", "ext_shop", "INTEGER"),
                            ("products", "ext_pid", "TEXT"),
                            ("products", "ext_price", "REAL DEFAULT 0"),
                            ("products", "ext_stock", "INTEGER DEFAULT 0"),
                            ("users", "agreed", "INTEGER DEFAULT 0"),
                            ("orders", "qty", "INTEGER DEFAULT 1")):
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()


def init():
    conn.executescript(SCHEMA)
    _migrate()
    if not val("SELECT COUNT(*) FROM categories"):
        x("INSERT INTO categories(name, position) VALUES (?, 1)", ("🤖 Ai-Сервисы",))
        x("INSERT INTO categories(name, position) VALUES (?, 2)", ("📱 Физ. номера",))


# ---------- settings ----------
_cache = {}


def get_setting(key, default=None):
    if key not in _cache:
        r = q1("SELECT value FROM settings WHERE key=?", (key,))
        _cache[key] = r["value"] if r else None
    v = _cache[key]
    return default if v is None else v


def set_setting(key, value):
    if value is None:
        x("DELETE FROM settings WHERE key=?", (key,))
    else:
        x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
          (key, str(value)))
    _cache[key] = None if value is None else str(value)


# ---------- users ----------
def get_user(uid):
    return q1("SELECT * FROM users WHERE id=?", (uid,))


def create_user(uid, username, first_name, lang):
    x("INSERT OR IGNORE INTO users(id, username, first_name, lang, joined) VALUES (?,?,?,?,?)",
      (uid, username, first_name, lang, now()))


def update_user(uid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE users SET {sets} WHERE id=?", (*kw.values(), uid))


def add_balance(uid, amount):
    x("UPDATE users SET balance=ROUND(balance+?, 2) WHERE id=?", (amount, uid))


def add_ref_balance(uid, amount):
    x("UPDATE users SET ref_balance=ROUND(ref_balance+?, 2), ref_earned=ROUND(ref_earned+?, 2) WHERE id=?",
      (amount, amount, uid))


def all_user_ids():
    return [r[0] for r in q("SELECT id FROM users WHERE banned=0")]


def all_users():
    return q("SELECT * FROM users ORDER BY joined DESC")


def count_refs(uid):
    return val("SELECT COUNT(*) FROM users WHERE referrer_id=?", (uid,))


def count_refs_bought(uid):
    return val("""SELECT COUNT(DISTINCT u.id) FROM users u
                  JOIN orders o ON o.user_id=u.id AND o.status IN ('done','manual')
                  WHERE u.referrer_id=?""", (uid,))


# ---------- categories ----------
def categories():
    return q("SELECT * FROM categories ORDER BY position, id")


def category(cid):
    return q1("SELECT * FROM categories WHERE id=?", (cid,))


def add_category(name, emoji_id=None):
    pos = (val("SELECT MAX(position) FROM categories") or 0) + 1
    return x("INSERT INTO categories(name, emoji_id, position) VALUES (?,?,?)", (name, emoji_id, pos))


def update_category(cid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE categories SET {sets} WHERE id=?", (*kw.values(), cid))


def delete_category(cid):
    x("DELETE FROM categories WHERE id=?", (cid,))


def count_in_category(cid, only_active=True):
    return val("SELECT COUNT(*) FROM products WHERE category_id=?" + (" AND active=1" if only_active else ""), (cid,))


# ---------- products ----------
def product(pid):
    return q1("SELECT * FROM products WHERE id=?", (pid,))


def all_products():
    return q("SELECT * FROM products ORDER BY category_id, id")


def add_product(cid, name, description, price, kind, emoji_id=None):
    return x("INSERT INTO products(category_id, name, description, price, kind, created, emoji_id) VALUES (?,?,?,?,?,?,?)",
             (cid, name, description, price, kind, now(), emoji_id))


def update_product(pid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE products SET {sets} WHERE id=?", (*kw.values(), pid))


def delete_product(pid):
    x("DELETE FROM products WHERE id=?", (pid,))
    x("DELETE FROM items WHERE product_id=? AND sold=0", (pid,))
    x("DELETE FROM favorites WHERE product_id=?", (pid,))
    x("DELETE FROM views WHERE product_id=?", (pid,))
    x("DELETE FROM notify WHERE product_id=?", (pid,))


def stock(pid):
    p = product(pid)
    if p and p["kind"] == "ext":  # товар внешнего магазина: остаток берём из последней синхронизации
        return max(p["ext_stock"] or 0, 0)
    return val("SELECT COUNT(*) FROM items WHERE product_id=? AND sold=0", (pid,))


def unlimited(p):
    """Товар без счётчика остатка: ручная выдача или внешний магазин, не сообщивший остаток (ext_stock < 0)."""
    return p["kind"] == "manual" or (p["kind"] == "ext" and (p["ext_stock"] or 0) < 0)


# ---------- внешние магазины (API) ----------
def ext_shops():
    return q("SELECT * FROM ext_shops ORDER BY id")


def ext_shop(sid):
    return q1("SELECT * FROM ext_shops WHERE id=?", (sid,))


def add_ext_shop(name, base_url, api_key, markup):
    return x("INSERT INTO ext_shops(name, base_url, api_key, markup, created) VALUES (?,?,?,?,?)",
             (name, base_url, api_key, markup, now()))


def update_ext_shop(sid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE ext_shops SET {sets} WHERE id=?", (*kw.values(), sid))


def delete_ext_shop(sid):
    for r in q("SELECT id FROM products WHERE ext_shop=?", (sid,)):
        delete_product(r["id"])
    shop = ext_shop(sid)
    x("DELETE FROM ext_shops WHERE id=?", (sid,))
    if shop and shop["category_id"] and not count_in_category(shop["category_id"], False):
        delete_category(shop["category_id"])


def ext_products(sid):
    return q("SELECT * FROM products WHERE ext_shop=? ORDER BY id", (sid,))


def add_ext_product(shop, cid, ext_pid, name, description, cost, price, stock_n):
    return x("""INSERT INTO products(category_id, name, description, price, kind, created, ext_shop, ext_pid, ext_price, ext_stock)
                VALUES (?,?,?,?, 'ext', ?,?,?,?,?)""",
             (cid, name, description, price, now(), shop, str(ext_pid), cost, stock_n))


def suppliers_cid():
    """Категория «Поставщики» (создаётся при первом обращении). Поставщики — это товары этой категории."""
    cid = get_setting("suppliers_cid")
    if cid and category(int(cid)):
        return int(cid)
    cid = add_category("🏭 Поставщики")
    set_setting("suppliers_cid", cid)
    return cid


def products_by(kind, uid=None, query=None):
    """Как _products_by, но поставщики не попадают в общие подборки (хиты, скидки, новинки, поиск)."""
    res = _products_by(kind, uid, query)
    if kind in ("hits", "disc", "new", "srch"):
        sup = suppliers_cid()
        res = [p for p in res if p["category_id"] != sup]
    return res


def _products_by(kind, uid=None, query=None):
    if kind.startswith("c") and kind[1:].isdigit():
        return q("SELECT * FROM products WHERE active=1 AND category_id=? ORDER BY id", (int(kind[1:]),))
    if kind == "hits":
        return q("""SELECT p.*, COUNT(o.id) AS cnt FROM products p
                    JOIN orders o ON o.product_id=p.id AND o.status IN ('done','manual')
                    WHERE p.active=1 GROUP BY p.id ORDER BY cnt DESC, p.id DESC LIMIT 20""")
    if kind == "disc":
        return q("SELECT * FROM products WHERE active=1 AND old_price>price ORDER BY id DESC")
    if kind == "new":
        return q("SELECT * FROM products WHERE active=1 ORDER BY id DESC LIMIT 20")
    if kind == "recent":
        return q("""SELECT p.* FROM views v JOIN products p ON p.id=v.product_id
                    WHERE v.user_id=? AND p.active=1 ORDER BY v.ts DESC LIMIT 20""", (uid,))
    if kind in ("fav", "pfav"):
        return q("""SELECT p.* FROM favorites f JOIN products p ON p.id=f.product_id
                    WHERE f.user_id=? AND p.active=1 ORDER BY f.rowid DESC""", (uid,))
    if kind == "srch":
        ql = (query or "").lower()
        return [p for p in q("SELECT * FROM products WHERE active=1 ORDER BY id DESC")
                if ql and (ql in (p["name"] or "").lower() or ql in (p["description"] or "").lower())]
    return []


# ---------- items (аккаунты / номера) ----------
def add_items(pid, contents):
    conn.executemany("INSERT INTO items(product_id, content) VALUES (?, ?)", [(pid, c) for c in contents])
    conn.commit()
    return len(contents)


def take_items(pid, oid, qty=1):
    """Забирает qty непроданных позиций со склада. Если их не хватает — не берёт ничего и возвращает None."""
    rows = q("SELECT id, content FROM items WHERE product_id=? AND sold=0 ORDER BY id LIMIT ?", (pid, qty))
    if len(rows) < qty:
        return None
    conn.executemany("UPDATE items SET sold=1, order_id=? WHERE id=?", [(oid, r["id"]) for r in rows])
    conn.commit()
    return [r["content"] for r in rows]


def clear_stock(pid):
    x("DELETE FROM items WHERE product_id=? AND sold=0", (pid,))


# ---------- orders ----------
def create_order(uid, p, price, method, status, promo_code=None, qty=1):
    name = p["name"] if qty == 1 else f"{p['name']} × {qty}"
    return x("""INSERT INTO orders(user_id, product_id, product_name, price, method, status, promo_code, created, qty)
                VALUES (?,?,?,?,?,?,?,?,?)""", (uid, p["id"], name, price, method, status, promo_code, now(), qty))


def order(oid):
    return q1("SELECT * FROM orders WHERE id=?", (oid,))


def set_order(oid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE orders SET {sets} WHERE id=?", (*kw.values(), oid))


VISIBLE = "status NOT IN ('wait_pay','canceled')"


def last_wait_pay(uid):
    """Последний заказ пользователя, ожидающий чек (за последние сутки)."""
    return q1("""SELECT * FROM orders WHERE user_id=? AND status='wait_pay'
                 AND created >= datetime('now','localtime','-1 day') ORDER BY id DESC LIMIT 1""", (uid,))


def user_orders(uid):
    return q(f"SELECT * FROM orders WHERE user_id=? AND {VISIBLE} ORDER BY id DESC", (uid,))


def count_user_orders(uid):
    return val(f"SELECT COUNT(*) FROM orders WHERE user_id=? AND {VISIBLE}", (uid,))


def user_spent(uid):
    return val("SELECT COALESCE(SUM(price),0) FROM orders WHERE user_id=? AND status IN ('done','manual')", (uid,))


# ---------- favorites / views / notify ----------
def is_fav(uid, pid):
    return bool(q1("SELECT 1 FROM favorites WHERE user_id=? AND product_id=?", (uid, pid)))


def toggle_fav(uid, pid):
    if is_fav(uid, pid):
        x("DELETE FROM favorites WHERE user_id=? AND product_id=?", (uid, pid))
        return False
    x("INSERT OR IGNORE INTO favorites(user_id, product_id) VALUES (?,?)", (uid, pid))
    return True


def add_view(uid, pid):
    x("INSERT OR REPLACE INTO views(user_id, product_id, ts) VALUES (?,?,?)", (uid, pid, now()))


def add_notify(uid, pid):
    x("INSERT OR IGNORE INTO notify(user_id, product_id) VALUES (?,?)", (uid, pid))


def pop_notify(pid):
    ids = [r[0] for r in q("SELECT user_id FROM notify WHERE product_id=?", (pid,))]
    x("DELETE FROM notify WHERE product_id=?", (pid,))
    return ids


# ---------- promos ----------
def promo(code):
    return q1("SELECT * FROM promos WHERE code=? COLLATE NOCASE", (code,))


def promos():
    return q("SELECT * FROM promos ORDER BY created DESC")


def add_promo(code, percent, max_uses):
    x("INSERT OR REPLACE INTO promos(code, percent, max_uses, used, created) VALUES (?,?,?,0,?)",
      (code, percent, max_uses, now()))


def delete_promo(code):
    x("DELETE FROM promos WHERE code=?", (code,))


def promo_used_by(code, uid):
    return bool(q1("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, uid)))


def use_promo(code, uid):
    x("INSERT OR IGNORE INTO promo_uses(code, user_id) VALUES (?,?)", (code, uid))
    x("UPDATE promos SET used=used+1 WHERE code=?", (code,))


# ---------- withdrawals ----------
def create_withdrawal(uid, amount):
    return x("INSERT INTO withdrawals(user_id, amount, status, created) VALUES (?,?,'pending',?)", (uid, amount, now()))


def withdrawal(wid):
    return q1("SELECT * FROM withdrawals WHERE id=?", (wid,))


def set_withdrawal(wid, status):
    x("UPDATE withdrawals SET status=? WHERE id=?", (status, wid))


# ---------- обязательная подписка ----------
def channels():
    return q("SELECT * FROM channels ORDER BY id")


def channel(cid):
    return q1("SELECT * FROM channels WHERE id=?", (cid,))


def add_channel(chat_id, title, url):
    x("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    return x("INSERT INTO channels(chat_id, title, url) VALUES (?,?,?)", (chat_id, title, url))


def delete_channel(cid):
    x("DELETE FROM channels WHERE id=?", (cid,))


# ---------- custom buttons ----------
def custom_buttons():
    return q("SELECT * FROM custom_buttons ORDER BY id")


def add_custom_button(text, url, emoji_id):
    x("INSERT INTO custom_buttons(text, url, emoji_id) VALUES (?,?,?)", (text, url, emoji_id))


def delete_custom_button(bid):
    x("DELETE FROM custom_buttons WHERE id=?", (bid,))


# ---------- stats ----------
def stats():
    today = "date('now','localtime')"
    week = "date('now','localtime','-7 days')"
    paid = "status IN ('done','manual')"
    return {
        "users": val("SELECT COUNT(*) FROM users"),
        "users_today": val(f"SELECT COUNT(*) FROM users WHERE joined >= {today}"),
        "users_week": val(f"SELECT COUNT(*) FROM users WHERE joined >= {week}"),
        "banned": val("SELECT COUNT(*) FROM users WHERE banned=1"),
        "orders": val(f"SELECT COUNT(*) FROM orders WHERE {paid}"),
        "orders_today": val(f"SELECT COUNT(*) FROM orders WHERE {paid} AND created >= {today}"),
        "rev": val(f"SELECT COALESCE(SUM(price),0) FROM orders WHERE {paid}"),
        "rev_today": val(f"SELECT COALESCE(SUM(price),0) FROM orders WHERE {paid} AND created >= {today}"),
        "rev_week": val(f"SELECT COALESCE(SUM(price),0) FROM orders WHERE {paid} AND created >= {week}"),
        "pending": val("SELECT COUNT(*) FROM orders WHERE status='pending'"),
        "manual": val("SELECT COUNT(*) FROM orders WHERE status='manual'"),
        "products": val("SELECT COUNT(*) FROM products"),
        "stock": val("SELECT COUNT(*) FROM items WHERE sold=0"),
        "sold_items": val("SELECT COUNT(*) FROM items WHERE sold=1"),
        "balances": val("SELECT COALESCE(SUM(balance),0) FROM users"),
        "wd_pending": val("SELECT COUNT(*) FROM withdrawals WHERE status='pending'"),
        "top": q1(f"""SELECT product_name, COUNT(*) c FROM orders WHERE {paid}
                      GROUP BY product_id ORDER BY c DESC LIMIT 1"""),
    }
