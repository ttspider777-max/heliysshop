import time

import aiosqlite

import config

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, is_premium INTEGER DEFAULT 0,
    balance INTEGER DEFAULT 0, sub_until INTEGER DEFAULT 0, banned INTEGER DEFAULT 0,
    referrer_id INTEGER, ref_earned INTEGER DEFAULT 0, total_sent INTEGER DEFAULT 0, created_at INTEGER);
CREATE TABLE IF NOT EXISTS accounts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tg_id INTEGER UNIQUE, phone TEXT,
    name TEXT, username TEXT, session TEXT, alive INTEGER DEFAULT 1, created_at INTEGER);
CREATE TABLE IF NOT EXISTS mailings(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, account_id INTEGER, text TEXT,
    interval_min INTEGER, status TEXT DEFAULT 'active', sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0,
    next_run INTEGER DEFAULT 0, last_run INTEGER DEFAULT 0, created_at INTEGER);
CREATE TABLE IF NOT EXISTS mailing_chats(
    mailing_id INTEGER, chat_id INTEGER, kind TEXT, access_hash INTEGER, title TEXT,
    active INTEGER DEFAULT 1, error TEXT, PRIMARY KEY(mailing_id, chat_id));
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, method TEXT, ext_id TEXT, hlx INTEGER,
    rub INTEGER, status TEXT DEFAULT 'pending', url TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS transactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, kind TEXT, note TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS channels(chat_id INTEGER PRIMARY KEY, title TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS stats_daily(
    user_id INTEGER, day TEXT, sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, rounds INTEGER DEFAULT 0,
    joined INTEGER DEFAULT 0, PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS drafts(
    user_id INTEGER PRIMARY KEY, text TEXT, entities TEXT, file_id TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS joins(
    id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, target TEXT, chat_id INTEGER, created_at INTEGER);
"""

# новые колонки для уже существующей базы
MIGRATIONS = [
    ("mailings", "media", "TEXT"),            # имя файла фото в DATA_DIR/media
    ("mailings", "entities", "TEXT"),         # JSON: форматирование и премиум-эмодзи поста
    ("mailings", "autojoin", "INTEGER DEFAULT 0"),
    ("mailings", "rounds", "INTEGER DEFAULT 0"),
    ("mailings", "joined", "INTEGER DEFAULT 0"),
]

DEFAULT_SETTINGS = {
    "greeting": (
        "<b>Heliys AutoPosting</b>\n\n"
        "Привет, {name}! Здесь можно настроить автопостинг от своего аккаунта: "
        "подключите аккаунт, выберите чаты и запустите рассылку по расписанию."
    ),
    "btn_app_text": "Открыть приложение",
    "btn_app_emoji": "",
    "btn_support_text": "Поддержка",
    "btn_support_emoji": "",
    "btn_docs_text": "Документы",
    "btn_docs_emoji": "",
    "mailing_requires_sub": "0",
}


async def init():
    global _db
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    for table, col, ddl in MIGRATIONS:
        cur = await _db.execute(f"PRAGMA table_info({table})")
        if col not in [r[1] for r in await cur.fetchall()]:
            await _db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    await _db.commit()


async def one(sql, *args):
    cur = await _db.execute(sql, args)
    row = await cur.fetchone()
    return dict(row) if row else None


async def all(sql, *args):
    cur = await _db.execute(sql, args)
    return [dict(r) for r in await cur.fetchall()]


async def run(sql, *args):
    cur = await _db.execute(sql, args)
    await _db.commit()
    return cur


# ---------- settings ----------

async def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    for row in await all("SELECT key, value FROM settings"):
        s[row["key"]] = row["value"]
    return s


async def set_setting(key, value):
    await run("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              key, value)


async def reset_setting(key):
    await run("DELETE FROM settings WHERE key=?", key)


# ---------- users ----------

async def get_user(user_id):
    return await one("SELECT * FROM users WHERE id=?", user_id)


async def upsert_user(user_id, username, first_name, is_premium):
    """Возвращает (user, is_new)."""
    user = await get_user(user_id)
    if user:
        await run("UPDATE users SET username=?, first_name=?, is_premium=? WHERE id=?",
                  username, first_name, int(bool(is_premium)), user_id)
        user.update(username=username, first_name=first_name, is_premium=int(bool(is_premium)))
        return user, False
    await run("INSERT INTO users(id, username, first_name, is_premium, created_at) VALUES(?,?,?,?,?)",
              user_id, username, first_name, int(bool(is_premium)), int(time.time()))
    return await get_user(user_id), True


def sub_active(user) -> bool:
    return user["sub_until"] > time.time()


def plan(user) -> dict:
    """Лимиты тарифа пользователя: Pro (если куплен) или Free."""
    return config.PRO if sub_active(user) else config.FREE


def acc_limit(user) -> int:
    return plan(user)["accounts"]


# ---------- статистика ----------

def day(ts=None) -> str:
    """Дата по Москве: так «сегодня» в статистике совпадает с днём пользователя."""
    return time.strftime("%Y-%m-%d", time.gmtime((ts or time.time()) + config.TZ_OFFSET))


async def add_stats(user_id, sent=0, failed=0, rounds=0, joined=0):
    await run("INSERT INTO stats_daily(user_id, day, sent, failed, rounds, joined) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(user_id, day) DO UPDATE SET sent=sent+excluded.sent, failed=failed+excluded.failed, "
              "rounds=rounds+excluded.rounds, joined=joined+excluded.joined",
              user_id, day(), sent, failed, rounds, joined)


async def stats_summary(user_id=None) -> dict:
    """Сегодня / вчера / 7 дней / всё время. user_id=None — по всему сервису."""
    where, args = ("WHERE user_id=?", [user_id]) if user_id else ("", [])
    cond = "AND" if where else "WHERE"
    cols = "COALESCE(SUM(sent),0) sent, COALESCE(SUM(failed),0) failed, " \
           "COALESCE(SUM(rounds),0) rounds, COALESCE(SUM(joined),0) joined"
    today, yesterday = day(), day(time.time() - 86400)
    week = day(time.time() - 6 * 86400)
    res = {
        "today": await one(f"SELECT {cols} FROM stats_daily {where} {cond} day=?", *args, today),
        "yesterday": await one(f"SELECT {cols} FROM stats_daily {where} {cond} day=?", *args, yesterday),
        "week": await one(f"SELECT {cols} FROM stats_daily {where} {cond} day>=?", *args, week),
        "total": await one(f"SELECT {cols} FROM stats_daily {where}", *args),
    }
    # до этой версии по дням не считали — «всего отправлено» берём из общего счётчика
    old = await one("SELECT COALESCE(SUM(total_sent),0) s FROM users" + (" WHERE id=?" if user_id else ""), *args)
    res["total"]["sent"] = max(res["total"]["sent"], old["s"])
    return res


async def add_balance(user_id, amount, kind, note=""):
    await run("UPDATE users SET balance = MAX(0, balance + ?) WHERE id=?", amount, user_id)
    await run("INSERT INTO transactions(user_id, amount, kind, note, created_at) VALUES(?,?,?,?,?)",
              user_id, amount, kind, note, int(time.time()))


async def add_sub_days(user_id, days):
    user = await get_user(user_id)
    until = max(user["sub_until"], int(time.time())) + days * 86400
    await run("UPDATE users SET sub_until=? WHERE id=?", until, user_id)
    return until


async def set_referrer(user_id, referrer_id):
    """Привязывает реферера и начисляет ему бонус. Вызывается только для новых пользователей."""
    if referrer_id == user_id or not await get_user(referrer_id):
        return False
    await run("UPDATE users SET referrer_id=? WHERE id=?", referrer_id, user_id)
    await add_balance(referrer_id, config.REF_BONUS, "ref", "Бонус за приглашённого")
    await run("UPDATE users SET ref_earned = ref_earned + ? WHERE id=?", config.REF_BONUS, referrer_id)
    return True
