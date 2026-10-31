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
CREATE TABLE IF NOT EXISTS hosted_bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    status TEXT,
    price REAL,
    receipt TEXT,
    token TEXT,
    tg_id INTEGER,
    username TEXT,
    shop_name TEXT,
    created TEXT,
    started TEXT
);
CREATE TABLE IF NOT EXISTS codex (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    status TEXT,
    method TEXT,
    price REAL,
    stars INTEGER,
    receipt TEXT,
    act_id TEXT,
    number TEXT,
    code TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    status TEXT,
    created TEXT,
    updated TEXT,
    closed_by INTEGER
);
CREATE TABLE IF NOT EXISTS ticket_msgs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    sender TEXT,
    admin_id INTEGER,
    text TEXT,
    file_id TEXT,
    kind TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS topups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    method TEXT,
    status TEXT,
    receipt TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS crypto_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,          -- order / topup
    ref_id INTEGER,     -- id заказа или пополнения
    user_id INTEGER,
    method TEXT,        -- cryptobot / xrocket
    ext_id TEXT,
    url TEXT,
    amount REAL,        -- сумма в рублях
    status TEXT,        -- pending / paid / expired
    created INTEGER
);
CREATE INDEX IF NOT EXISTS idx_items_prod ON items(product_id, sold);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_tmsg ON ticket_msgs(ticket_id);
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
                            ("orders", "qty", "INTEGER DEFAULT 1"),
                            ("products", "photo", "TEXT"),
                            ("products", "media_type", "TEXT"),      # photo / video / animation
                            ("categories", "photo", "TEXT"),
                            ("categories", "media_type", "TEXT"),
                            ("users", "deposited", "REAL DEFAULT 0"),  # сколько реальных денег принёс (для статуса)
                            ("users", "bonus_at", "TEXT"),            # когда забирал ежедневный бонус
                            ("products", "soldout", "INTEGER DEFAULT 0"),   # админ пометил «нет в наличии»
                            ("products", "no_stars", "INTEGER DEFAULT 0"),  # оплата звёздами для товара выключена
                            ("products", "min_qty", "INTEGER DEFAULT 0"),   # >0 — покупка по количеству, от N шт.
                            ("products", "restock_text", "TEXT")):          # свой текст рассылки о пополнении
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()
    if get_setting("mig_deposited") is None:
        # статус считается по реальным деньгам: прошлые оплаты по СБП и звёздами тоже засчитываем
        x("""UPDATE users SET deposited = COALESCE((SELECT SUM(price) FROM orders o WHERE o.user_id=users.id
             AND o.method IN ('sbp','stars') AND o.status IN ('done','manual')), 0)""")
        set_setting("mig_deposited", "1")


def init():
    conn.executescript(SCHEMA)
    _migrate()
    if not val("SELECT COUNT(*) FROM categories"):
        x("INSERT INTO categories(name, position) VALUES (?, 1)", ("🤖 Ai-Сервисы",))
        x("INSERT INTO categories(name, position) VALUES (?, 2)", ("📱 Физ. номера",))


# ---------- бэкап базы ----------
def backup_bytes():
    """Полная копия базы (товары, пользователи, оформление) в виде файла .db."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(path)
        conn.backup(dst)
        dst.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def check_backup(path):
    """None — файл подходит для восстановления, иначе текст ошибки."""
    try:
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        names = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        src.close()
    except sqlite3.DatabaseError:
        return "это не файл базы SQLite"
    if not {"users", "settings", "products"} <= names:
        return "в файле нет таблиц бота (users, settings, products)"
    return None


def restore_from(path):
    """Заменяет текущую базу содержимым файла (после check_backup)."""
    src = sqlite3.connect(path)
    src.backup(conn)
    src.close()
    _cache.clear()
    conn.executescript(SCHEMA)
    _migrate()


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
    set_infinite(pid, None)


def stock(pid):
    p = product(pid)
    if p and p["kind"] == "ext":  # товар внешнего магазина: остаток берём из последней синхронизации
        return max(p["ext_stock"] or 0, 0)
    return val("SELECT COUNT(*) FROM items WHERE product_id=? AND sold=0", (pid,))


def dec_ext_stock(pid, n):
    """После продажи товара внешнего магазина уменьшаем известный остаток (-1 «не сообщает» не трогаем)."""
    x("UPDATE products SET ext_stock=MAX(ext_stock-?, 0) WHERE id=? AND ext_stock>0", (n, pid))


def inf_content(pid):
    """Содержимое «бесконечного» товара (одно и то же выдаётся каждому покупателю) или None."""
    return get_setting(f"inf:{pid}") or None


def set_infinite(pid, content):
    """Включает бесконечную выдачу content для товара; None — выключает."""
    set_setting(f"inf:{pid}", content or None)


def unlimited(p):
    """Товар без счётчика остатка: ручная выдача, бесконечный товар или внешний магазин без остатка (ext_stock < 0)."""
    return (p["kind"] == "manual" or (p["kind"] == "ext" and (p["ext_stock"] or 0) < 0)
            or (p["kind"] == "auto" and bool(inf_content(p["id"]))))


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
    inf = inf_content(pid)
    if inf:  # бесконечный товар: склад не расходуется
        return [inf] * qty
    rows = q("SELECT id, content FROM items WHERE product_id=? AND sold=0 ORDER BY id LIMIT ?", (pid, qty))
    if len(rows) < qty:
        return None
    conn.executemany("UPDATE items SET sold=1, order_id=? WHERE id=?", [(oid, r["id"]) for r in rows])
    conn.commit()
    return [r["content"] for r in rows]


def clear_stock(pid):
    x("DELETE FROM items WHERE product_id=? AND sold=0", (pid,))
    set_infinite(pid, None)


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
    return q1("""SELECT * FROM orders WHERE user_id=? AND status='wait_pay' AND method='sbp'
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


def consume_promo(uid):
    """Промокод действует на один заказ: снимаем его с пользователя в момент оформления."""
    x("UPDATE users SET promo_code=NULL, promo_percent=0 WHERE id=?", (uid,))


def restore_promo(o):
    """Заказ отменён / отклонён / деньги вернули — возвращаем покупателю его промокод."""
    if not o or not o["promo_code"]:
        return
    u = get_user(o["user_id"])
    p = promo(o["promo_code"])
    if u and p and not u["promo_percent"]:
        update_user(o["user_id"], promo_code=p["code"], promo_percent=p["percent"])


def release_promo_orders(uid):
    """Неоплаченные заказы со скидкой (чек ещё не отправлен) отменяем и возвращаем промокод,
    чтобы скидкой нельзя было воспользоваться в двух заказах сразу."""
    for o in q("SELECT * FROM orders WHERE user_id=? AND status='wait_pay' AND promo_code IS NOT NULL", (uid,)):
        set_order(o["id"], status="canceled")
        restore_promo(o)


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


# ---------- боты клиентов («🤖 Создать своего бота») ----------
# Статусы: wait_pay — ждём оплату, pending — чек на проверке, wait_token — оплачено, ждём токен,
# running — работает, stopped — остановлен админом, failed — упал (например, токен отозван),
# rejected — оплату отклонили, canceled — покупатель отменил, deleted — удалён админом.
def create_hosted(uid, price):
    return x("INSERT INTO hosted_bots(user_id, status, price, created) VALUES (?, 'wait_pay', ?, ?)", (uid, price, now()))


def hosted(bid):
    return q1("SELECT * FROM hosted_bots WHERE id=?", (bid,))


def set_hosted(bid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE hosted_bots SET {sets} WHERE id=?", (*kw.values(), bid))


def user_hosted(uid):
    return q("""SELECT * FROM hosted_bots WHERE user_id=? AND status NOT IN ('wait_pay','canceled','deleted')
                ORDER BY id DESC""", (uid,))


def hosted_wait_pay(uid):
    """Последняя заявка на бота, ожидающая чек (за последние сутки)."""
    return q1("""SELECT * FROM hosted_bots WHERE user_id=? AND status='wait_pay'
                 AND created >= datetime('now','localtime','-1 day') ORDER BY id DESC LIMIT 1""", (uid,))


def hosted_wait_token(uid):
    return q1("SELECT * FROM hosted_bots WHERE user_id=? AND status='wait_token' ORDER BY id LIMIT 1", (uid,))


def hosted_by_tg(tg_id):
    """Бот с этим Telegram-ID, который уже стоит на хосте (чтобы один токен не запускали дважды)."""
    return q1("SELECT * FROM hosted_bots WHERE tg_id=? AND status IN ('running','stopped','failed')", (tg_id,))


def hosted_running():
    return q("SELECT * FROM hosted_bots WHERE status='running' ORDER BY id")


def hosted_list():
    return q("""SELECT * FROM hosted_bots WHERE status NOT IN ('wait_pay','canceled','deleted')
                ORDER BY id DESC LIMIT 60""")


def hosted_owner_ids():
    return [r[0] for r in q("SELECT DISTINCT user_id FROM hosted_bots WHERE status IN ('running','stopped','failed')")]


# ---------- «🔐 Верификация Codex» ----------
# Статусы: wait_pay — ждём оплату, pending — чек на проверке, paid — оплачено, номер ещё не выдан,
# active — номер выдан, ждём код, code — код выдан, done — подтверждено, canceled — отменено покупателем,
# rejected — оплату отклонили, refunded — номер не получили, деньги на балансе.
def create_codex(uid, method, price, stars, status="wait_pay"):
    return x("INSERT INTO codex(user_id, status, method, price, stars, created) VALUES (?,?,?,?,?,?)",
             (uid, status, method, price, stars, now()))


def codex(vid):
    return q1("SELECT * FROM codex WHERE id=?", (vid,))


def set_codex(vid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE codex SET {sets} WHERE id=?", (*kw.values(), vid))


def codex_active(uid):
    """Выданный номер, по которому верификация ещё не закончена."""
    return q1("SELECT * FROM codex WHERE user_id=? AND status IN ('active','code') ORDER BY id DESC LIMIT 1", (uid,))


def codex_wait_pay(uid):
    return q1("""SELECT * FROM codex WHERE user_id=? AND status='wait_pay' AND method='sbp'
                 AND created >= datetime('now','localtime','-1 day') ORDER BY id DESC LIMIT 1""", (uid,))


# ---------- поддержка (обращения) ----------
# Статусы: open — ждёт ответа админа, answered — админ ответил, closed — закрыто, rejected — отклонено.
def create_ticket(uid):
    return x("INSERT INTO tickets(user_id, status, created, updated) VALUES (?, 'open', ?, ?)", (uid, now(), now()))


def ticket(tid):
    return q1("SELECT * FROM tickets WHERE id=?", (tid,))


def set_ticket(tid, **kw):
    kw.setdefault("updated", now())
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE tickets SET {sets} WHERE id=?", (*kw.values(), tid))


def user_active_ticket(uid):
    return q1("SELECT * FROM tickets WHERE user_id=? AND status IN ('open','answered') ORDER BY id DESC LIMIT 1", (uid,))


def add_ticket_msg(tid, sender, text, file_id=None, kind=None, admin_id=None):
    return x("INSERT INTO ticket_msgs(ticket_id, sender, admin_id, text, file_id, kind, created) VALUES (?,?,?,?,?,?,?)",
             (tid, sender, admin_id, text, file_id, kind, now()))


def ticket_msgs(tid):
    return q("SELECT * FROM ticket_msgs WHERE ticket_id=? ORDER BY id", (tid,))


def tickets_list(statuses, limit=50):
    marks = ",".join("?" * len(statuses))
    return q(f"SELECT * FROM tickets WHERE status IN ({marks}) ORDER BY updated DESC LIMIT ?", (*statuses, limit))


def user_tickets(uid, limit=10):
    return q("SELECT * FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))


# ---------- пополнение баланса ----------
def create_topup(uid, amount, method, status="wait_pay"):
    return x("INSERT INTO topups(user_id, amount, method, status, created) VALUES (?,?,?,?,?)",
             (uid, amount, method, status, now()))


def topup(tid):
    return q1("SELECT * FROM topups WHERE id=?", (tid,))


def set_topup(tid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    x(f"UPDATE topups SET {sets} WHERE id=?", (*kw.values(), tid))


def topup_wait_pay(uid):
    return q1("""SELECT * FROM topups WHERE user_id=? AND status='wait_pay' AND method='sbp'
                 AND created >= datetime('now','localtime','-1 day') ORDER BY id DESC LIMIT 1""", (uid,))


def add_deposited(uid, amount):
    """Реальные деньги покупателя (пополнения, оплаты по СБП и звёздами) — от них зависит статус."""
    x("UPDATE users SET deposited=ROUND(COALESCE(deposited,0)+?, 2) WHERE id=?", (amount, uid))


def latest_wait_kind(uid):
    """Что ждёт чек от покупателя: order / codex / hosted / topup (самая свежая заявка) или None.
    Нужен, чтобы чек, присланный без «Я оплатил», попал в нужный раздел."""
    found = [(r["created"], kind) for kind, r in (("order", last_wait_pay(uid)), ("codex", codex_wait_pay(uid)),
                                                   ("hosted", hosted_wait_pay(uid)), ("topup", topup_wait_pay(uid))) if r]
    return max(found)[1] if found else None


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
        "bots_pending": val("SELECT COUNT(*) FROM hosted_bots WHERE status='pending'"),
        "bots_running": val("SELECT COUNT(*) FROM hosted_bots WHERE status='running'"),
        "tickets": val("SELECT COUNT(*) FROM tickets WHERE status='open'"),
        "topups_pending": val("SELECT COUNT(*) FROM topups WHERE status='pending'"),
        "topups_sum": val("SELECT COALESCE(SUM(amount),0) FROM topups WHERE status='done'"),
        "top": q1(f"""SELECT product_name, COUNT(*) c FROM orders WHERE {paid}
                      GROUP BY product_id ORDER BY c DESC LIMIT 1"""),
    }
