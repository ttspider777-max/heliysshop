"""Конструктор: настройки, тексты, кнопки, пользователи, пополнения и черновики магазинов.

Всё хранится в основной базе (db.py): настройки — в таблице settings с префиксом «c:», поэтому тексты,
кнопки и оформление, которые админ поменял в /admin конструктора, переживают обновления кода.
"""
import html
import json
import os
import re

import appcfg
import config
import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS ctor_users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance REAL DEFAULT 0,
    joined TEXT,
    banned INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ctor_topups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    status TEXT,
    receipt TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS ctor_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    kind TEXT,          -- create (новый магазин) / buy (пробный -> навсегда)
    bot_id INTEGER,     -- для buy: id магазина
    method TEXT,        -- stars / cryptobot / xrocket / sbp / balance
    amount REAL,        -- ₽
    stars INTEGER,
    status TEXT,        -- wait / pending (чек на проверке) / paid / rejected / canceled
    receipt TEXT,
    inv_id INTEGER,     -- счёт крипты (crypto_invoices.id)
    data TEXT,          -- снимок данных мастера на момент оплаты
    created TEXT
);
CREATE TABLE IF NOT EXISTS ctor_drafts (
    user_id INTEGER PRIMARY KEY,
    data TEXT,
    step TEXT,
    updated TEXT
);
CREATE TABLE IF NOT EXISTS ctor_promos (
    code TEXT PRIMARY KEY,   -- в верхнем регистре
    kind TEXT,               -- percent (скидка %) / rub (скидка ₽) / days (+дни пробного)
    value REAL,
    max_uses INTEGER DEFAULT 0,  -- 0 — без лимита
    used INTEGER DEFAULT 0,
    until TEXT,              -- до какого момента действует (NULL — бессрочно)
    created TEXT
);
CREATE TABLE IF NOT EXISTS ctor_promo_uses (code TEXT, user_id INTEGER, ts TEXT, PRIMARY KEY (code, user_id));
CREATE TABLE IF NOT EXISTS ctor_partners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,         -- кому платим (админ канала)
    code TEXT UNIQUE,        -- ссылка t.me/<бот>?start=p_<code>
    name TEXT,
    reward REAL,             -- ₽ за каждого нового покупателя
    earned REAL DEFAULT 0,
    paid_out REAL DEFAULT 0,
    created TEXT
);
CREATE TABLE IF NOT EXISTS ctor_chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    sender TEXT,             -- user / admin
    text TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS ctor_kicks (
    user_id INTEGER,              -- удалён из чата, потому что кончилась подписка (ctor/groups.py)
    chat_id INTEGER,
    kicked_at TEXT,
    restored TEXT                 -- когда вернули после продления
);
CREATE TABLE IF NOT EXISTS ctor_groups (
    chat_id INTEGER PRIMARY KEY,  -- групповой чат, куда добавили конструктор (ctor/groups.py)
    title TEXT,
    added TEXT,
    active INTEGER DEFAULT 1
);
"""


def init():
    db.conn.executescript(SCHEMA)
    for table, col, ddl in (
            ("hosted_bots", "source", "TEXT"),       # 'ctor' — магазин создан через конструктор
            ("hosted_bots", "cfg", "TEXT"),          # данные мастера
            ("hosted_bots", "reminded", "TEXT"),     # какие напоминания о пробном уже отправлены (JSON)
            ("ctor_payments", "promo", "TEXT"),      # промокод, со скидкой по которому выставлен счёт
            ("ctor_payments", "tariff", "TEXT"),     # тариф (start/medium/pro/vip) или ключ дополнения
            ("hosted_bots", "plan", "TEXT"),         # trial / start / medium / pro / vip (NULL у старых — pro)
            ("hosted_bots", "verified", "INTEGER DEFAULT 0"),  # получил «Проверенный магазин»
            ("hosted_bots", "no_app", "INTEGER DEFAULT 0"),    # магазин без мини-приложения (только кнопки в чате)
            ("hosted_bots", "no_mkbot", "INTEGER DEFAULT 0"),  # владелец конструктора скрыл «Создать своего бота»
            ("hosted_bots", "ban_stopped", "INTEGER DEFAULT 0"),  # остановлен из-за бана владельца — запустить при разбане
            ("ctor_users", "ban_reason", "TEXT"),              # 'illegal' — забанен за незаконный бот
            ("hosted_bots", "lastday_tag", "TEXT"),            # за какой пробный уже выдан промокод последнего дня
            ("hosted_bots", "report_at", "TEXT"),              # когда отправлен еженедельный отчёт
            ("ctor_users", "partner_id", "INTEGER"),           # пришёл по ссылке партнёра
            ("ctor_users", "partner_paid", "INTEGER DEFAULT 0"),  # партнёру уже заплатили за этого покупателя
            ("ctor_users", "app_opened", "TEXT"),              # когда впервые открыл мини-приложение
            ("ctor_users", "push_sent", "INTEGER DEFAULT 0"),  # пуш «открой приложение» уже отправлен
            ("ctor_users", "referrer_id", "INTEGER"),          # кто пригласил
            ("ctor_users", "ref_earned", "REAL DEFAULT 0"),    # сколько заработал на рефералах
            ("ctor_users", "promo", "TEXT"),                   # введённый промокод, ждёт оплаты
            ("ctor_users", "autobuy", "INTEGER DEFAULT 1")):   # покупать пробных ботов с баланса сам
        cols = [r["name"] for r in db.conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            db.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    db.conn.commit()
    # 02.11.2026: напоминания за 7, 4, 3 дня и дальше каждый день. Старое стандартное значение заменяю,
    # своё значение админа не трогаю.
    if re.sub(r"\s", "", get("remind_days") or "") == "7,3,2,1":
        put("remind_days", None)
    # 03.11.2026: новогодняя тема включена по умолчанию; магазины читают этот ключ из базы конструктора
    if get("ny") is None:
        put("ny", "1")


# ======================= настройки =======================
def get(key, default=None):
    return db.get_setting("c:" + key, default)


def put(key, value):
    db.set_setting("c:" + key, value)


def token():
    """Токен конструктора. Отдельный бот на BotHost: его BOT_TOKEN (config.CTOR_MODE)."""
    if config.CTOR_MODE:
        return config.BOT_TOKEN
    return (get("token") or os.getenv("CONSTRUCTOR_TOKEN") or "").strip()


def price():
    try:
        return max(float(get("price", db.get_setting("bot_price", config.BOT_PRICE))), 0)
    except (TypeError, ValueError):
        return float(config.BOT_PRICE)


def trial_days():
    try:
        return max(int(float(get("trial_days", 3))), 0)
    except (TypeError, ValueError):
        return 3


def sbp():
    return get("sbp") or db.get_setting("sbp_details", config.SBP_DETAILS)


def support_url():
    return get("support_url") or db.get_setting("support_url") or config.SUPPORT_URL


def curator():
    """Личный куратор владельцев магазинов (/admin → 👨‍💼 Куратор). По умолчанию — поддержка."""
    return get("curator") or support_url()


def stars_price():
    """Цена в звёздах (⭐). /admin → 💳 Оплата → «Цена в звёздах»; 0/пусто — по курсу из цены в ₽."""
    try:
        own = int(float(get("stars_price") or 0))
    except (TypeError, ValueError):
        own = 0
    if own > 0:
        return own
    try:
        rate = float(db.get_setting("star_rate", config.STAR_RATE) or config.STAR_RATE)
    except (TypeError, ValueError):
        rate = config.STAR_RATE
    import math
    return max(int(math.ceil(price() / max(rate, 0.01))), 1)


def stars_for(amount):
    """Цена в звёздах для любой суммы (тариф, скидка): пропорционально цене Pro в звёздах."""
    import math
    base = price()
    if base <= 0:
        try:
            rate = float(db.get_setting("star_rate", config.STAR_RATE) or config.STAR_RATE)
        except (TypeError, ValueError):
            rate = config.STAR_RATE
        return max(int(math.ceil(amount / max(rate, 0.01))), 1)
    if abs(amount - base) < 0.01:
        return stars_price()
    return max(int(math.ceil(stars_price() * amount / base)), 1)


# ======================= тарифы =======================
# ключ -> (название, дней (0 — навсегда), цена по умолчанию). Цена Pro — это «💰 Цена» (core.price()).
TARIFFS = {
    "start": ("🚀 Start", 30, 99),
    "medium": ("⚡ Medium", 90, 200),
    "pro": ("💎 Pro", 0, 300),
    "vip": ("👑 VIP", 0, 750),
}


def tariff_price(key):
    if key == "pro":
        return price()
    try:
        return max(float(get("tp:" + key, TARIFFS[key][2])), 0)
    except (TypeError, ValueError, KeyError):
        return float(TARIFFS.get(key, ("", 0, 0))[2])


def tariff_days(key):
    return TARIFFS.get(key, ("", 0, 0))[1]


def tariff_on(key):
    return key in TARIFFS and get("toff:" + key) != "1"


def tariffs_on():
    return [k for k in TARIFFS if tariff_on(k)]


def tariff_name(key):
    return TARIFFS.get(key, (key or "—",))[0]


def tariff_period(key):
    d = tariff_days(key)
    return f"{d} {days_word(d)}" if d else "навсегда"


def min_tariff_price():
    prices = [tariff_price(k) for k in tariffs_on()]
    return min(prices) if prices else price()


def bot_plan(b):
    """Тариф магазина: trial / start / medium / pro / vip."""
    p = b["plan"] if "plan" in b.keys() else None
    if p:
        return p
    return "trial" if b["trial_until"] else "pro"


def plan_line(b):
    """«🚀 Start до 01.12 18:00» / «🎁 пробный до …» / «💎 Pro · навсегда»."""
    from handlers import builder
    p = bot_plan(b)
    if p == "trial":
        return f"🎁 пробный до {builder.fmt_until(b['trial_until'])}" if b["trial_until"] else "🎁 пробный"
    if b["trial_until"]:
        return f"{tariff_name(p)} до {builder.fmt_until(b['trial_until'])}"
    return f"{tariff_name(p)} · навсегда"


def plan_what(b):
    """Для напоминаний: «пробного периода» / «тарифа 🚀 Start»."""
    p = bot_plan(b)
    return "пробного периода" if p == "trial" else f"тарифа {tariff_name(p)}"


# ======================= дополнения =======================
ADDONS = {
    "ads": ("📣 Реклама в нашем канале", 150),
    "fill": ("📦 Заливка 50 товаров куратором", 250),
}


def addon_price(key):
    try:
        return max(float(get("ap:" + key, ADDONS[key][1])), 0)
    except (TypeError, ValueError, KeyError):
        return float(ADDONS.get(key, ("", 0))[1])


def addon_on(key):
    return key in ADDONS and get("aoff:" + key) != "1"


# ======================= курс, FAQ (JSON-списки в настройках) =======================
def jget(key, default):
    raw = get(key)
    if not raw:
        return [dict(x) for x in default]
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else [dict(x) for x in default]
    except ValueError:
        return [dict(x) for x in default]


def jput(key, value):
    put(key, json.dumps(value, ensure_ascii=False))


COURSE = [
    {"t": "Урок 1. Что продавать в Telegram",
     "x": "📚 <b>Урок 1 из 5. Что продавать в Telegram</b>\n\nЛучше всего продаются цифровые товары: их не нужно "
          "отправлять почтой, а выдать можно за секунду.\n\n<blockquote>• аккаунты (игры, соцсети)\n• подписки и ключи "
          "(Spotify, Windows, Discord Nitro)\n• AI-сервисы (ChatGPT, Midjourney)\n• номера для регистрации\n"
          "• услуги: дизайн, монтаж, консультации</blockquote>\n\n💡 Начни с того, в чём разбираешься сам — так проще "
          "отвечать покупателям и находить поставщиков."},
    {"t": "Урок 2. Где брать товар",
     "x": "📚 <b>Урок 2 из 5. Где брать товар</b>\n\n<blockquote>• оптовые магазины и поставщики в Telegram — "
          "покупаешь дешевле, продаёшь с наценкой 20–50%\n• свои товары и услуги\n• перепродажа по API: магазин сам "
          "заказывает товар у поставщика, когда покупатель оплатил</blockquote>\n\n💡 Сначала купи 1–2 позиции у "
          "поставщика сам — проверишь качество и скорость."},
    {"t": "Урок 3. Как поставить цену",
     "x": "📚 <b>Урок 3 из 5. Как поставить цену</b>\n\nПосмотри цены у 3–5 конкурентов и встань чуть ниже среднего "
          "или на уровне — но с лучшим сервисом.\n\n<blockquote>• автовыдача 24/7 — уже преимущество\n"
          "• скидка за первую покупку или промокод\n• «старая цена» зачёркнутой — покупатель видит выгоду</blockquote>"},
    {"t": "Урок 4. Где найти первых покупателей",
     "x": "📚 <b>Урок 4 из 5. Первые покупатели</b>\n\n<blockquote>• свой канал + реклама у похожих каналов\n"
          "• тематические чаты (без спама — полезный пост и ссылка)\n• TikTok / Shorts: короткие ролики «как купить X "
          "дешевле»\n• реферальная программа: покупатели приводят друзей за процент</blockquote>\n\n💡 Первые 10 "
          "продаж — самые трудные. Дальше работают отзывы и сарафанное радио."},
    {"t": "Урок 5. Запусти свой магазин",
     "x": "📚 <b>Урок 5 из 5. Пора запускать</b>\n\nТы знаешь, что продавать, где брать товар, как поставить цену и "
          "найти покупателей. Осталось самое простое — магазин.\n\n<blockquote>✨ мини-приложение и автовыдача 24/7\n"
          "💳 оплата СБП, звёздами и криптой\n👨‍💼 личный куратор поможет с настройкой</blockquote>\n\n"
          "🚀 Создай свой магазин за 5 минут 👇"},
]

FAQ = [
    {"q": "Сколько стоит магазин?", "a": "Start — 99₽ на 30 дней, Medium — 200₽ на 90 дней, Pro — 300₽ навсегда, "
                                        "VIP — 750₽ навсегда + исходный код. Есть бесплатный пробный период."},
    {"q": "Нужно ли уметь программировать?", "a": "Нет. Выбираешь цвет, стиль, название и присылаешь токен из "
                                                  "@BotFather — магазин запускается сам."},
    {"q": "Где взять токен бота?", "a": "Открой @BotFather → /newbot → придумай имя и username на «bot» → скопируй "
                                        "токен вида 123456:AAH… и пришли его конструктору."},
    {"q": "Как покупатели будут платить?", "a": "СБП (по чеку), звёздами Telegram, CryptoBot и xRocket. Реквизиты "
                                                "указываешь в /admin своего бота."},
    {"q": "Что будет, когда закончится тариф?", "a": "Бот выключится, но товары, покупатели и настройки сохранятся. "
                                                     "Продлишь — он сразу заработает."},
    {"q": "Можно ли продлить автоматически?", "a": "Да: пополни баланс конструктора — бот продлится сам перед концом "
                                                   "срока (автопродление включается в «Мои боты»)."},
    {"q": "Что входит в VIP?", "a": "Магазин навсегда + полный исходный код конструктора и магазина с инструкцией по "
                                    "запуску — сможешь продавать магазины под своим брендом."},
    {"q": "Кто поможет с настройкой?", "a": "Личный куратор: поможет с товарами, рекламным текстом и оформлением. "
                                            "Напиши в чат с куратором в приложении."},
]


# ======================= партнёры =======================
def partner(pid):
    return db.q1("SELECT * FROM ctor_partners WHERE id=?", (pid,))


def partner_by_code(code):
    return db.q1("SELECT * FROM ctor_partners WHERE code=?", ((code or "").lower(),))


def partner_of(uid):
    return db.q1("SELECT * FROM ctor_partners WHERE user_id=? ORDER BY id LIMIT 1", (uid,))


def set_partner(uid, code):
    """Пришёл по ссылке партнёра: только один раз и только если ещё не пришёл по реферальной ссылке."""
    p = partner_by_code(code)
    u = user(uid)
    if not p or not u or u["partner_id"] or u["referrer_id"] or p["user_id"] == uid:
        return None
    if db.val("SELECT COUNT(*) FROM ctor_payments WHERE user_id=? AND status='paid'", (uid,)):
        return None
    db.x("UPDATE ctor_users SET partner_id=? WHERE id=? AND partner_id IS NULL", (p["id"], uid))
    return p


def partner_reward(pay):
    """Первая оплата покупателя партнёра -> партнёру его фиксированная сумма. -> (партнёр, сумма) или None."""
    if (pay["amount"] or 0) <= 0 or pay["kind"] == "addon":
        return None
    cur = db.conn.execute("UPDATE ctor_users SET partner_paid=1 WHERE id=? AND partner_id IS NOT NULL "
                          "AND partner_paid=0", (pay["user_id"],))
    db.conn.commit()
    if not cur.rowcount:
        return None
    p = partner(user(pay["user_id"])["partner_id"])
    if not p:
        return None
    db.x("UPDATE ctor_partners SET earned=ROUND(earned+?, 2) WHERE id=?", (p["reward"], p["id"]))
    return partner(p["id"]), p["reward"]


def partner_stats(p):
    users = db.val("SELECT COUNT(*) FROM ctor_users WHERE partner_id=?", (p["id"],)) or 0
    buyers = db.val("SELECT COUNT(*) FROM ctor_users WHERE partner_id=? AND partner_paid=1", (p["id"],)) or 0
    return users, buyers, round((p["earned"] or 0) - (p["paid_out"] or 0), 2)


# ======================= чат с куратором =======================
def chat_add(uid, sender, text):
    return db.x("INSERT INTO ctor_chat(user_id, sender, text, created) VALUES (?,?,?,?)",
                (uid, sender, text[:2000], db.now()))


def chat_list(uid, limit=60):
    rows = db.q("SELECT * FROM ctor_chat WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
    return list(reversed(rows))


def pay_on(method):
    """Способ оплаты включён (звёзды и СБП — переключатели в /admin, крипта — когда вставлен API-токен)."""
    if method in ("cryptobot", "xrocket"):
        import crypto
        return crypto.enabled(method)
    return get("pay_off:" + method) != "1"


def pay_methods():
    return [m for m in ("stars", "cryptobot", "xrocket", "sbp") if pay_on(m)]


PAY_NAMES = {"stars": "Звёзды", "cryptobot": "CryptoBot", "xrocket": "xRocket", "sbp": "СБП", "balance": "Баланс"}


def payment(pid):
    return db.q1("SELECT * FROM ctor_payments WHERE id=?", (pid,))


def create_payment(uid, kind, method, amount, stars=0, bot_id=None, data=None):
    db.x("UPDATE ctor_payments SET status='canceled' WHERE user_id=? AND kind=? AND status='wait' "
         "AND COALESCE(bot_id, 0)=?", (uid, kind, bot_id or 0))
    return db.x("INSERT INTO ctor_payments(user_id, kind, bot_id, method, amount, stars, status, data, created) "
                "VALUES (?,?,?,?,?,?, 'wait', ?, ?)",
                (uid, kind, bot_id, method, amount, stars, json.dumps(data or {}, ensure_ascii=False), db.now()))


def set_payment(pid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    db.x(f"UPDATE ctor_payments SET {sets} WHERE id=?", (*kw.values(), pid))


def mark_paid(pid, receipt=None):
    """Атомарно: wait/pending -> paid. -> True, если именно этот вызов провёл оплату."""
    cur = db.conn.execute("UPDATE ctor_payments SET status='paid', receipt=COALESCE(?, receipt) "
                          "WHERE id=? AND status IN ('wait','pending')", (receipt, pid))
    db.conn.commit()
    return cur.rowcount == 1


def flag_on(key):
    """Переключатель в /admin: по умолчанию включён, «0» — выключен."""
    return get(key) != "0"


# ======================= рефералы =======================
def ref_percent():
    """Сколько % от каждой оплаты друга получает пригласивший (/admin → 🤝 Рефералы). 0 — программа выключена."""
    try:
        return min(max(float(get("ref_percent", 15)), 0), 100)
    except (TypeError, ValueError):
        return 15.0


def ref_link(uid):
    from ctor import bot as cbot
    u = cbot.username()
    return f"https://t.me/{u}?start=r{uid}" if u else ""


def set_referrer(uid, ref_id):
    """Запоминает пригласившего: только один раз, не себя и только пока человек ничего не создал и не оплатил."""
    if ref_id == uid or ref_percent() <= 0:
        return False
    u, r = user(uid), user(ref_id)
    if not u or not r or u["referrer_id"]:
        return False
    if db.val("SELECT COUNT(*) FROM hosted_bots WHERE user_id=? AND tg_id IS NOT NULL", (uid,)) or \
            db.val("SELECT COUNT(*) FROM ctor_payments WHERE user_id=? AND status='paid'", (uid,)):
        return False
    if r["referrer_id"] == uid:  # двое не могут пригласить друг друга
        return False
    db.x("UPDATE ctor_users SET referrer_id=? WHERE id=? AND referrer_id IS NULL", (ref_id, uid))
    return True


def ref_stats(uid):
    """-> (приглашено, из них с оплатой, заработано)."""
    invited = db.val("SELECT COUNT(*) FROM ctor_users WHERE referrer_id=?", (uid,)) or 0
    paid = db.val("SELECT COUNT(DISTINCT p.user_id) FROM ctor_payments p JOIN ctor_users u ON u.id=p.user_id "
                  "WHERE u.referrer_id=? AND p.status='paid' AND p.amount>0", (uid,)) or 0
    u = user(uid)
    return invited, paid, round((u["ref_earned"] if u else 0) or 0, 2)


def ref_reward(p):
    """Начисляет пригласившему его % от оплаты. -> (id пригласившего, сумма) или None."""
    u = user(p["user_id"])
    if not u or not u["referrer_id"] or (p["amount"] or 0) <= 0:
        return None
    reward = round(p["amount"] * ref_percent() / 100, 2)
    if reward <= 0 or not user(u["referrer_id"]):
        return None
    db.x("UPDATE ctor_users SET balance=ROUND(balance+?, 2), ref_earned=ROUND(COALESCE(ref_earned,0)+?, 2) "
         "WHERE id=?", (reward, reward, u["referrer_id"]))
    return u["referrer_id"], reward


# ======================= промокоды =======================
PROMO_RE = re.compile(r"^[A-Za-z0-9_\-]{3,24}$")
PROMO_KINDS = {"percent": "скидка %", "rub": "скидка ₽", "days": "+дни пробного"}


def promo(code):
    return db.q1("SELECT * FROM ctor_promos WHERE code=?", ((code or "").strip().upper(),))


def promo_label(p):
    v = p["value"]
    n = int(v) if v == int(v) else v
    if p["kind"] == "percent":
        return f"−{n}%"
    if p["kind"] == "rub":
        return f"−{money(v)}"
    return f"+{n} {days_word(n)} пробного"


def promo_check(code, uid):
    """-> (промокод, None) или (None, текст ошибки)."""
    p = promo(code)
    if not p:
        return None, "not_found"
    if p["until"] and p["until"] <= db.now():
        return None, "expired"
    if p["max_uses"] and p["used"] >= p["max_uses"]:
        return None, "expired"
    if db.q1("SELECT 1 FROM ctor_promo_uses WHERE code=? AND user_id=?", (p["code"], uid)):
        return None, "used"
    return p, None


def active_promo(uid):
    """Введённый, но ещё не использованный промокод человека (если всё ещё действует)."""
    u = user(uid)
    if not u or not u["promo"]:
        return None
    p, _ = promo_check(u["promo"], uid)
    return p


def set_user_promo(uid, code):
    db.x("UPDATE ctor_users SET promo=? WHERE id=?", (code, uid))


def use_promo(code, uid):
    """Промокод израсходован этим человеком (после оплаты или продления пробного)."""
    cur = db.conn.execute("INSERT OR IGNORE INTO ctor_promo_uses(code, user_id, ts) VALUES (?, ?, ?)",
                          (code, uid, db.now()))
    if cur.rowcount:
        db.conn.execute("UPDATE ctor_promos SET used=used+1 WHERE code=?", (code,))
    db.conn.execute("UPDATE ctor_users SET promo=NULL WHERE id=? AND promo=?", (uid, code))
    db.conn.commit()


def final_price(uid, tariff="pro"):
    """Цена тарифа для человека с учётом введённого промокода. -> (сумма ₽, промокод или None)."""
    base = tariff_price(tariff)
    p = active_promo(uid)
    if not p or p["kind"] == "days":
        return base, None
    if p["kind"] == "percent":
        amount = base * (100 - min(max(p["value"], 0), 100)) / 100
    else:
        amount = base - p["value"]
    return round(max(amount, 0), 2), p


def promo_days(uid):
    """Сколько дней пробного добавляет введённый промокод (0 — нет такого промокода)."""
    p = active_promo(uid)
    return int(p["value"]) if p and p["kind"] == "days" else 0


def topup_min():
    try:
        return max(float(get("topup_min", 50)), 1)
    except (TypeError, ValueError):
        return 50.0


def money(v):
    v = round(float(v or 0), 2)
    return (f"{int(v)}" if v == int(v) else f"{v:.2f}") + "₽"


def days_word(n):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "дня"
    return "дней"


# ======================= цвета и стили =======================
# ключ -> (название, акцентный цвет мини-приложения, цвет кружка в выборе)
COLORS = {
    "red": ("Красный", "#ef4444", "#ef4444"),
    "blue": ("Синий", "#3b82f6", "#3b82f6"),
    "green": ("Зелёный", "#22c55e", "#22c55e"),
    "purple": ("Фиолетовый", "#8b5cf6", "#8b5cf6"),
    # чёрный акцент на тёмном фоне не виден — «чёрная» витрина: чёрный фон и светлые кнопки
    "black": ("Чёрный", "#e4e4e7", "#111111"),
    "orange": ("Оранжевый", "#f97316", "#f97316"),
}
COLOR_EMOJI = {"red": "🔴", "blue": "🔵", "green": "🟢", "purple": "🟣", "black": "⚫", "orange": "🟠"}
HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def norm_hex(text):
    m = HEX_RE.match((text or "").strip())
    return "#" + m.group(1).lower() if m else None


def styles():
    """Стили витрины = сезонные стили магазина: ключ -> (название с эмодзи, акцент сезона)."""
    return {k: (v[0], v[3]) for k, v in appcfg.SEASONS.items()}


def color_label(d):
    key = d.get("color")
    if key in COLORS:
        return f"{COLOR_EMOJI[key]} {COLORS[key][0]}"
    return f"🎨 Свой цвет {d.get('hex') or ''}".strip()


def color_hex(d):
    key = d.get("color")
    return COLORS[key][1] if key in COLORS else (d.get("hex") or "#8b5cf6")


def style_label(d):
    s = styles().get(d.get("style") or "none")
    return s[0] if s else "—"


# ======================= тексты бота =======================
# {name} — имя, {balance} — баланс, {bots} — сколько у человека ботов, {price} — цена, {days} — дней пробного
TEXTS = {
    "welcome": ("👋 Приветствие", (
        "🏗 <b>heliys конструктор</b>\n"
        "Свой магазин в Telegram за 5 минут — такой же, как @heliys_shop_bot\n\n"
        "<blockquote>👋 Привет, <b>{name}</b>!\n🤖 Твоих ботов: <b>{bots}</b></blockquote>\n"
        "✨ Мини-приложение, автовыдача товаров, оплата СБП / звёздами / криптой, поддержка и админка — всё уже внутри.\n\n"
        "👨‍💼 <b>У тебя будет личный куратор</b> — поможет с рекламным текстом, товарами, оформлением и "
        "первыми продажами.\n\n"
        "{trial}👇 Жми «Открыть приложение»")),
    "trial_line": ("🎁 Строка про пробный период", "🎁 Пробный период — <b>{days}</b> бесплатно. Тарифы — от {min} "
                                                   "(звёзды, крипта, СБП).\n\n"),
    "price_line": ("💰 Строка про цену (без пробного)", "💳 Магазин — от <b>{min}</b>: Start, Medium, Pro "
                                                       "или VIP (звёзды, крипта, СБП).\n\n"),
    "step_mode": ("🧭 Шаг 0 — с мини-приложением или без", (
        "🧭 <b>Какой бот тебе нужен?</b>\n\n<blockquote>📱 <b>С мини-приложением</b> — красивая витрина внутри Telegram: "
        "карточки товаров, поиск, избранное, свой цвет и стиль.\n\n💬 <b>Без мини-приложения</b> — классический бот: "
        "каталог и покупка кнопками прямо в чате. Проще и быстрее в настройке.</blockquote>\n\n"
        "<i>Всё остальное одинаково: автовыдача, оплата, поддержка, админка.</i>")),
    "step_color": ("🎨 Шаг 1 — цвет (в чате)", "🎨 <b>Шаг 1 из 7 — цвет витрины</b>\n\nВыбери основной цвет мини-приложения "
                                                "или введи свой:"),
    "step_hex": ("🎨 Ввод своего цвета", "🎨 Пришли цвет в формате <code>#ff7a1a</code>.\n\n"
                                         "Подобрать цвет можно тут: https://htmlcolorcodes.com"),
    "step_style": ("🎭 Шаг 2 — стиль", "🎭 <b>Шаг 2 из 7 — стиль витрины</b>\n\nСтиль добавляет анимацию и значок на "
                                       "главную карточку магазина:"),
    "step_title": ("🏷 Шаг 3 — заголовок", "🏷 <b>Шаг 3 из 7 — заголовок витрины</b>\n\nНапиши название магазина — его "
                                           "увидят на главной карточке мини-приложения (до 40 символов).\n\n"
                                           "Например: <code>Snow Shop</code>, <code>Neon Store</code>"),
    "step_desc": ("📝 Шаг 4 — описание", "📝 <b>Шаг 4 из 7 — описание витрины</b>\n\nКоротко: что ты продаёшь и чем "
                                         "ты лучше (до 200 символов). Напиши своё или выбери вариант ниже 👇"),
    "step_welcome": ("👋 Шаг 5 — приветствие", (
        "👋 <b>Шаг 5 из 7 — приветствие бота</b>\n\nПришли сообщение, которое покупатели увидят после /start.\n\n"
        "<blockquote>• можно с <b>премиум-эмодзи</b> и форматированием\n• можно прикрепить <b>фото</b>, видео или GIF\n"
        "• <code>{name}</code> — имя покупателя, <code>{balance}</code> — его баланс</blockquote>\n\n"
        "Или возьми готовое 👇")),
    "step_support": ("💬 Шаг 6 — поддержка", (
        "💬 <b>Шаг 6 из 7 — поддержка</b>\n\nКуда писать покупателям, если что-то пошло не так? Пришли свой "
        "<code>@username</code> или ссылку.\n\n<i>Обращения внутри бота (тикеты) работают в любом случае.</i>")),
    "step_token": ("🔑 Шаг 7 — токен (инструкция)", (
        "🔑 <b>Шаг 7 из 7 — токен бота</b>\n\nСоздай бота в @BotFather и пришли сюда его токен:\n"
        "<blockquote>1. Открой @BotFather и нажми <b>Start</b>\n"
        "2. Отправь команду <code>/newbot</code>\n"
        "3. Напиши имя бота — например, <i>Snow Shop</i>\n"
        "4. Придумай username, он должен заканчиваться на <code>bot</code> — например, <i>snowshop_bot</i>\n"
        "5. BotFather пришлёт токен вида <code>123456789:AAH...</code> — скопируй и отправь его сюда</blockquote>\n\n"
        "🔒 Сообщение с токеном я сразу удалю из чата.")),
    "checking": ("⏳ Проверка токена", "⏳ Проверяю токен…"),
    "token_format": ("❌ Токен: неверный формат", "❌ Это не похоже на токен. Он выглядит так: "
                                                  "<code>123456789:AAH...</code> — скопируй его из @BotFather целиком."),
    "token_invalid": ("❌ Токен: Telegram не принял", "❌ Telegram не принял этот токен. Проверь, что скопировал его "
                                                      "целиком, или выпусти новый в @BotFather (/token)."),
    "token_network": ("❌ Токен: нет связи", "⚠️ Не получилось связаться с Telegram. Попробуй отправить токен ещё раз "
                                             "через минуту."),
    "token_taken": ("❌ Токен: бот уже занят", "❌ Этот бот уже подключён к другому магазину. Создай нового бота в "
                                               "@BotFather."),
    "token_ok": ("✅ Токен принят", "✅ Бот @{username} найден!"),
    "summary": ("🧾 Проверь данные магазина", "🧾 <b>Проверь данные магазина</b>"),
    "pay_trial": ("🎁 Оплата: бесплатно", "🎁 <b>{days} бесплатно</b>, потом тариф от {min}"),
    "pay_price": ("💰 Оплата в итогах", "💳 <b>{price}</b> или <b>{stars} ⭐</b> — оплата звёздами, криптой или по СБП "
                                        "на следующем шаге"),
    "edit_menu": ("✏️ Что изменить", "✏️ <b>Что изменить?</b>"),
    "pay_choose": ("💳 Выбор оплаты (новый магазин)", (
        "💳 <b>Оплата магазина — {tariff}</b>\n\nСтоимость: <b>{price}</b> или <b>{stars} ⭐</b> · {period}.\n"
        "{trial}Выбери способ оплаты 👇")),
    "pay_choose_buy": ("💳 Выбор оплаты (купить пробный)", (
        "💳 <b>@{username} — {tariff}</b>\n\nСтоимость: <b>{price}</b> или <b>{stars} ⭐</b> · {period}.\n"
        "Выбери способ оплаты 👇")),
    "pay_trial_line": ("🎁 Строка о пробном в выборе оплаты", "🎁 Или возьми <b>пробный период на {days}</b> — бесплатно.\n\n"),
    "pay_none": ("⚠️ Нет способов оплаты", "⚠️ Оплата сейчас недоступна — напиши в поддержку."),
    "stars_title": ("⭐ Счёт звёздами — название", "Магазин в Telegram"),
    "stars_desc": ("⭐ Счёт звёздами — описание", "Свой магазин на базе heliys shop"),
    "pay_crypto": ("💎 Счёт в крипте", (
        "💎 <b>Счёт {service}</b> на <b>{price}</b>{extra}\n\nОплати по кнопке ниже и вернись сюда — "
        "магазин создастся автоматически (проверка раз в 20 секунд или кнопкой).")),
    "pay_crypto_wait": ("💎 Крипта ещё не пришла", "Оплата ещё не пришла — подожди минуту и проверь снова."),
    "pay_crypto_expired": ("💎 Счёт истёк", "Счёт истёк — выбери оплату заново."),
    "pay_sbp": ("💳 Оплата по СБП — реквизиты", (
        "💳 <b>Оплата по СБП — заявка #{id}</b>\n\nПереведи <b>{price}</b> по реквизитам:\n{details}\n\n"
        "После оплаты нажми «Я оплатил» и пришли чек.")),
    "pay_receipt": ("🧾 Скинь чек", "🧾 Скинь скриншот или файл чека одним сообщением:"),
    "pay_receipt_sent": ("🔎 Чек на проверке", "🔎 Чек отправлен на проверку. Как только администратор подтвердит "
                                              "оплату — я сразу создам твой магазин."),
    "pay_receipt_sent_buy": ("🔎 Чек на проверке (покупка)", "🔎 Чек отправлен на проверку. Как только администратор "
                                                            "подтвердит оплату — бот станет бессрочным."),
    "pay_rejected": ("❌ Заявка отклонена", "❌ <b>Твоя заявка #{id} отклонена.</b>\n\nОплата не подтвердилась. "
                                           "Если это ошибка — напиши в поддержку и приложи чек."),
    "pay_ok": ("✅ Оплата получена", "✅ <b>Оплата получена!</b> Создаю твой магазин…"),
    "pay_canceled": ("❌ Оплата отменена", "Оплата отменена."),
    "no_money": ("💸 Не хватает денег", "💸 <b>Не хватает на балансе</b>\n\nСоздание бота стоит <b>{price}</b>, "
                                        "на балансе <b>{balance}</b>. Пополни баланс — и вернись к созданию, "
                                        "все данные магазина сохранены."),
    "creating": ("⏳ Создаю магазин", "⏳ Создаю магазин и запускаю бота…"),
    "created": ("✅ Магазин создан", (
        "🎉 <b>Магазин создан!</b>\n\nТвой бот @{username} уже работает.\n\n<blockquote>"
        "1. Открой бота и отправь /admin\n2. Добавь категории и товары: 🛍 Товары и склад\n"
        "3. Укажи реквизиты для оплаты: ⚙️ Настройки\n4. Поменяй тексты, кнопки и премиум-эмодзи: ✏️ Оформление</blockquote>"
        "{trial}")),
    "created_trial": ("🎁 Строка о пробном после создания", "\n\n<b>{plan}</b>. Продлить или выбрать тариф можно "
                                                            "в «🧾 Мои боты»."),
    "curator_msg": ("👨‍💼 Сообщение о кураторе после создания", (
        "👨‍💼 <b>Напиши своему куратору</b>\n\nЗа тобой закреплён личный куратор: {curator}\n\n<blockquote>"
        "• составит рекламный текст и описание магазина\n• подскажет, какие товары добавить и по какой цене\n"
        "• поможет с оформлением, премиум-эмодзи и настройкой оплаты</blockquote>\n\n"
        "Напиши ему прямо сейчас — укажи своего бота @{username}, и он подключится 👇")),
    "create_fail": ("⚠️ Бот не запустился", "⚠️ Бот @{username} создан, но не запустился. Мы уже получили "
                                             "уведомление и разберёмся — или напиши в поддержку."),
    "busy": ("⏳ Уже создаётся", "⏳ Магазин уже создаётся, подожди пару секунд…"),
    "no_draft": ("🤷 Нет данных мастера", "🤷 Данные магазина не найдены — начни создание заново."),
    "bots_head": ("🧾 Мои боты — заголовок", "🧾 <b>Мои боты</b>"),
    "no_bots": ("🧾 Мои боты — пусто", "🧾 <b>Мои боты</b>\n\nУ тебя пока нет ботов. Создай первый — это 5 минут 👇"),
    "topup_ask": ("💳 Пополнение — сумма", "💳 <b>Пополнение баланса</b>\n\nВыбери сумму или отправь свою "
                                           "(от {min}):"),
    "topup_pay": ("💳 Пополнение — реквизиты", (
        "💳 <b>Пополнение на {amount}</b>\n\nПереведи <b>{amount}</b> по СБП:\n{details}\n\n"
        "После оплаты нажми «Я оплатил» и пришли скриншот чека.")),
    "topup_receipt": ("🧾 Пришли чек", "🧾 Пришли скриншот или файл чека одним сообщением:"),
    "topup_need_receipt": ("🧾 Нужен чек", "Нужен скриншот или файл чека 🧾"),
    "topup_sent": ("🔎 Чек отправлен", "🔎 Чек отправлен на проверку. Как только админ подтвердит — баланс пополнится, "
                                       "я напишу."),
    "topup_ok": ("✅ Баланс пополнен", "✅ Баланс пополнен на <b>{amount}</b>. Сейчас: <b>{balance}</b>"),
    "topup_no": ("❌ Чек отклонён", "❌ Пополнение на {amount} отклонено. Если это ошибка — напиши в поддержку."),
    "support": ("💬 Поддержка", "💬 <b>Поддержка</b>\n\nПо любым вопросам пиши: {link}"),
    "bought": ("♾ Бот куплен", "✅ Оплачено! @{username}: <b>{plan}</b>. Спасибо!"),
    "trial_soon": ("⏰ Пробный скоро закончится", "⏰ Пробный период бота @{username} закончится <b>{until}</b>.\n\n"
                                                 "Купи тариф (от {price}), чтобы магазин не выключился."),
    "trial_over": ("⌛ Пробный закончился", "⌛ Пробный период бота @{username} закончился — бот выключен. Товары и "
                                           "настройки сохранены: купи тариф от {price}, и он сразу заработает."),
    "failed": ("⚠️ Бот упал", "⚠️ Бот @{username} перестал работать — скорее всего, токен отозвали в @BotFather. "
                             "Открой «🧾 Мои боты» и пришли новый токен."),
    "retoken": ("🔑 Новый токен для бота", "🔑 Пришли новый токен бота @{username} из @BotFather (/token)."),
    "retoken_other": ("❌ Токен от другого бота", "❌ Это токен другого бота. Нужен токен именно @{username}."),
    "retoken_ok": ("✅ Бот снова работает", "✅ Бот @{username} снова работает."),
    # ---------- шаблоны ----------
    "step_template": ("🧩 Шаг «Готовый набор товаров»", (
        "🧩 <b>Готовый набор товаров</b>\n\nЧто будешь продавать? Я сразу добавлю категории и примеры товаров — "
        "цены, описания и остатки потом поменяешь в /admin своего бота.\n\n"
        "<i>Примеры товаров создаются без остатка: покупатели увидят «нет в наличии», пока ты не загрузишь свои.</i>")),
    # ---------- рефералы ----------
    "ref": ("🤝 Рефералы — экран", (
        "🤝 <b>Приглашай друзей — получай {percent}</b>\n\nС каждой оплаты друга тебе на баланс приходит "
        "<b>{percent}</b>. Балансом можно оплатить своих ботов.\n\n<blockquote>"
        "👥 Пришли по ссылке: <b>{invited}</b>\n💳 Из них оплатили: <b>{paid}</b>\n💰 Заработано: <b>{earned}</b>"
        "</blockquote>\n\n🔗 Твоя ссылка:\n<code>{link}</code>")),
    "ref_joined": ("🤝 Пригласившему: друг пришёл", "👋 По твоей ссылке пришёл <b>{name}</b>. Когда он оплатит бота — "
                                                    "тебе придёт {percent} на баланс."),
    "ref_reward": ("🤝 Пригласившему: друг оплатил", "🤝 <b>{name}</b> оплатил бота — тебе <b>+{amount}</b> на баланс.\n"
                                                     "💰 Баланс: <b>{balance}</b>"),
    "ref_share": ("🤝 Текст для «Поделиться»", "Делаю свой магазин в Telegram за 5 минут — попробуй тоже 👇"),
    # ---------- промокоды ----------
    "promo_ask": ("🎟 Ввод промокода", "🎟 <b>Промокод</b>\n\nПришли промокод одним сообщением:"),
    "promo_ok": ("🎟 Промокод применён", "✅ Промокод <b>{code}</b> применён: <b>{label}</b>."),
    "promo_days_ok": ("🎟 Промокод: пробный продлён", "✅ Промокод <b>{code}</b>: пробный период @{username} продлён "
                                                       "до <b>{until}</b>."),
    "promo_days_saved": ("🎟 Промокод: дни при создании", "✅ Промокод <b>{code}</b>: <b>{label}</b> — добавлю их, "
                                                          "когда запустишь бота на пробном периоде."),
    "promo_not_found": ("🎟 Промокод не найден", "❌ Такого промокода нет. Проверь и пришли ещё раз:"),
    "promo_expired": ("🎟 Промокод закончился", "⌛ Этот промокод больше не действует."),
    "promo_used": ("🎟 Промокод уже использован", "Ты уже использовал этот промокод."),
    "promo_line": ("🎟 Строка о промокоде в оплате", "🎟 Промокод <b>{code}</b>: {label} — <s>{old}</s> → <b>{price}</b>\n"),
    # ---------- напоминания и автопокупка ----------
    "receipt_checking": ("🔎 Проверка чека", "🔎 Проверяю чек… Обычно это до минуты."),
    "ad_wait": ("🪄 Реклама: пишу", "🪄 Пишу 3 рекламных поста для @{username} по твоим товарам… Это около 20 секунд."),
    "ad_head": ("🪄 Реклама: заголовок", (
        "🪄 <b>Готово — 3 варианта рекламы для @{username}</b>\n\nСкопируй понравившийся и размести в каналах, "
        "чатах и у блогеров по теме. Лучше всего работают тематические чаты и взаимопиар с похожими магазинами.")),
    "ad_fail": ("🪄 Реклама: не получилось", "😔 Не получилось написать рекламу — попробуй через минуту."),
    "ad_limit": ("🪄 Реклама: лимит", "⏳ Новые варианты можно получить через минуту (и не больше 10 раз в сутки)."),
    "receipt_ai_rejected": ("❌ Чек не принят (нейросеть)", (
        "❌ <b>Чек не принят:</b> {reason}.\n\nЕсли это ошибка — напиши в поддержку, проверим вручную.")),
    "lastday_offer": ("🎁 Скидка в последний день пробного", (
        "🎁 <b>Последний день пробного — скидка {pct}% только для тебя</b>\n\nПробный период @{username} скоро "
        "закончится. Держи личный промокод <code>{code}</code> — он уже применён, действует <b>{hours} ч</b>.\n\n"
        "Например, Pro навсегда: <s>{old}</s> → <b>{price}</b>.\n\nУспей продлить — магазин продолжит работать без "
        "перерыва, товары и покупатели останутся.")),
    "weekly_report": ("📊 Еженедельный отчёт владельцу", (
        "📊 <b>Неделя магазина @{username}</b>\n\n<blockquote>{stats}</blockquote>\n\n{tip}")),
    "weekly_tip_zero": ("📊 Отчёт: совет, если продаж нет", (
        "💡 Продаж пока нет — напиши куратору: подскажем, где взять первых покупателей и как оформить витрину.")),
    "weekly_tip_ok": ("📊 Отчёт: если продажи есть", "🔥 Так держать! Пополни склад заранее, чтобы хиты не закончились."),
    "kicked_dm": ("🚪 Удалён из чата: подписка закончилась", (
        "🚪 <b>Подписка закончилась — доступ к чату закрыт</b>\n\nСрок твоего магазина истёк, поэтому я убрал тебя "
        "из чата:\n{chats}\n\n💳 Продли подписку — и я сразу пришлю ссылку, чтобы вернуться. Все товары, покупатели "
        "и настройки магазина сохранены.")),
    "restored_dm": ("✅ Возврат в чат после продления", (
        "✅ <b>Подписка продлена — доступ к чату снова открыт!</b>\n\nЖми кнопку ниже, чтобы вернуться. "
        "Ссылка одноразовая — только для тебя.")),
    "group_hello": ("💬 Приветствие в чате", (
        "👋 Привет! Я помогаю с магазинами из @{bot}.\n\nСпрашивайте прямо здесь — например, "
        "<i>«как добавить товар?»</i> или <i>«как подключить криптооплату?»</i> — отвечу сам.")),
    "remind_days": ("⏰ Напоминание: осталось N дней", "⏰ До конца {what} бота @{username} осталось <b>{left}</b> "
                                                      "(до {until}).\n\nПродли сейчас — от {price}, чтобы магазин "
                                                      "работал без перерыва."),
    "remind_3h": ("⏰ Напоминание за 3 часа", "⏰ <b>Через 3 часа</b> закончится срок {what} @{username} и бот "
                                             "выключится.\n\nПродли — от {price}. Товары и покупатели останутся на месте."),
    "remind_after": ("⌛ Напоминание после выключения", "⌛ Бот @{username} выключен уже <b>{days}</b>.\n\nВсе товары, "
                                                       "покупатели и настройки сохранены — продли от {price}, и он "
                                                       "сразу заработает."),
    "sub_soon": ("⏰ Тариф: остались сутки", "⏰ Срок {what} бота @{username} закончится <b>{until}</b>.\n\n"
                                            "Продли от {price}, чтобы магазин не выключился."),
    "sub_over": ("⌛ Тариф закончился", "⌛ Срок {what} бота @{username} закончился — бот выключен. Товары и настройки "
                                       "сохранены: продли от {price}, и он сразу заработает."),
    "autobuy_hint": ("🔁 Строка: продлю сам с баланса", "\n\n🔁 На балансе хватает — продлю ({tariff}) автоматически "
                                                       "перед концом срока."),
    "autobuy_need": ("🔁 Строка: пополни — продлю сам", "\n\n🔁 Пополни баланс ещё на <b>{need}</b> — и я продлю бота "
                                                       "сам ({tariff}), ничего нажимать не нужно."),
    "autobought": ("🔁 Автопродление выполнено", "🔁 <b>Автопродление</b>: списал {price} с баланса — @{username}: "
                                                "<b>{plan}</b>.\n💰 Остаток: <b>{balance}</b>"),
    "autobuy_info": ("🔁 Подсказка в «Мои боты»", "\n\n🔁 Автопродление: <b>{state}</b> — если на балансе хватает, бот "
                                                 "продлевается сам перед концом срока (пробный — тарифом Start) или "
                                                 "сразу после пополнения."),
    # ---------- тарифы ----------
    "tariffs_head": ("💎 Тарифы — заголовок", "💎 <b>Тарифы heliys конструктора</b>\n\nВо всех тарифах — полноценный "
                                              "магазин со всеми функциями. Разница только в сроке и бонусах."),
    "tariff_start": ("🚀 Описание тарифа Start", (
        "🚀 <b>Start — {price} за 30 дней</b>\n<i>Попробовать бизнес без вложений</i>\n<blockquote>"
        "✅ Полноценный магазин: мини-приложение, каталог, поиск, избранное\n✅ Автовыдача товаров 24/7\n"
        "✅ Оплата СБП, звёздами, CryptoBot и xRocket\n✅ Админ-панель: тексты, кнопки, премиум-эмодзи\n"
        "✅ Тикеты поддержки, рефералы и промокоды для покупателей\n✅ Доступ в чат владельцев магазинов\n"
        "✅ Продление в 1 клик или автоматически с баланса</blockquote>\n"
        "⏳ Не продлишь — бот выключится, но товары и покупатели сохранятся.")),
    "tariff_medium": ("⚡ Описание тарифа Medium", (
        "⚡ <b>Medium — {price} за 90 дней</b>\n<i>Выгоднее Start на треть — ~{month} в месяц</i>\n<blockquote>"
        "✅ Всё, что есть в Start\n✅ 3 месяца без мыслей о продлении\n✅ Помощь куратора с настройкой: товары, "
        "оформление, реквизиты\n✅ Экономия {save} по сравнению с тремя Start</blockquote>")),
    "tariff_pro": ("💎 Описание тарифа Pro", (
        "💎 <b>Pro — {price} навсегда</b>\n<i>Один платёж — магазин твой навсегда</i>\n<blockquote>"
        "✅ Всё, что есть в Medium\n♾ Никаких продлений и абонентской платы\n✅ Все будущие обновления магазина — "
        "бесплатно\n👨‍💼 Личный куратор: рекламный текст, подбор товаров и цен, первые продажи\n"
        "✅ Окупается уже через 3 месяца по сравнению со Start</blockquote>")),
    "tariff_vip": ("👑 Описание тарифа VIP", (
        "👑 <b>VIP — {price} навсегда + исходный код</b>\n<i>Свой конструктор магазинов под своим брендом</i>\n"
        "<blockquote>✅ Всё, что есть в Pro — магазин навсегда\n"
        "📦 <b>Полный исходный код</b> (Python, aiogram 3):\n"
        "   • бот-конструктор: мастер создания, тарифы, пробный период, оплата, рефералы, промокоды, партнёрка, "
        "админ-панель\n"
        "   • магазин heliys shop: автовыдача, мини-приложение, СБП / звёзды / CryptoBot / xRocket, тикеты, статусы, "
        "отзывы\n"
        "   • хостинг магазинов клиентов на одном сервере\n"
        "   • оба мини-приложения (витрина и конструктор)\n"
        "📄 Инструкция по запуску на хостинге за 15 минут\n"
        "👨‍💼 Помощь куратора с установкой и первым запуском\n"
        "💰 Сможешь продавать магазины сам и оставлять всю выручку себе</blockquote>\n"
        "<i>Код — для твоего проекта; перепродавать сам исходный код нельзя.</i>")),
    "vip_delivery": ("👑 VIP: выдача исходников", (
        "👑 <b>Добро пожаловать в VIP!</b>\n\nВ архиве выше — полный исходный код конструктора и магазина.\n\n"
        "<blockquote>1. Распакуй архив и загрузи файлы на GitHub (приватный репозиторий)\n"
        "2. Создай бота на хостинге (например BotHost) из этого репозитория, точка входа — <code>main.py</code>\n"
        "3. Задай переменную <code>BOT_TOKEN</code> — токен своего бота\n"
        "4. Для конструктора — <code>BOT_MODE=constructor</code> и <code>PUBLIC_URL</code> (адрес сайта бота)\n"
        "5. Владелец — твой Telegram ID в <code>config.py</code> (ADMINS)</blockquote>\n\n"
        "Застрял — пиши куратору: {curator}")),
    "vip_wait": ("👑 VIP: архив пришлёт куратор", "👑 <b>Оплата VIP получена!</b>\n\nКуратор пришлёт архив с исходным "
                                                 "кодом и инструкцию в течение 24 часов: {curator}"),
    # ---------- чат владельцев ----------
    "owners_chat": ("👥 Приглашение в чат владельцев", (
        "👥 <b>Ты в клубе владельцев heliys!</b>\n\nВступай в закрытый чат владельцев магазинов: советы по продажам, "
        "поставщики, обновления и помощь куратора.\n\n🔒 Только для тех, кто купил магазин 👇")),
    # ---------- дополнения ----------
    "addons_head": ("🛍 Дополнения — заголовок", "🛍 <b>Дополнения к магазину</b>\n\nУскорь старт продаж 👇"),
    "addon_ads": ("📣 Описание: реклама в канале", (
        "📣 <b>Реклама в нашем канале — {price}</b>\n\n<blockquote>• пост о твоём магазине в канале heliys\n"
        "• текст и оформление сделаем сами\n• ссылка на твоего бота — первые покупатели уже в день публикации"
        "</blockquote>")),
    "addon_fill": ("📦 Описание: заливка товаров", (
        "📦 <b>Заливка 50 товаров куратором — {price}</b>\n\n<blockquote>• куратор сам создаст до 50 товаров и "
        "категорий\n• названия, описания, цены и фото\n• ты присылаешь список или файл — остальное сделаем мы"
        "</blockquote>")),
    "addon_ok": ("🛍 Дополнение оплачено", "✅ <b>{name}</b> оплачено!\n\nКуратор свяжется с тобой в ближайшее время: "
                                          "{curator}"),
    "addon_pick_bot": ("🛍 Выбор бота для дополнения", "🛍 Для какого магазина?"),
    # ---------- партнёрка ----------
    "partner": ("🤝 Партнёрка — экран партнёра", (
        "🤝 <b>Партнёрская программа</b>\n\nЗа каждого нового покупателя по твоей ссылке — <b>{reward}</b>.\n\n"
        "<blockquote>👥 Пришло: <b>{users}</b>\n💳 Купили: <b>{buyers}</b>\n💰 Заработано: <b>{earned}</b>\n"
        "💸 К выплате: <b>{due}</b></blockquote>\n\n🔗 Ссылка для поста:\n<code>{link}</code>")),
    "partner_sale": ("🤝 Партнёру: новый покупатель", "🤝 По твоей ссылке купили магазин — <b>+{amount}</b>.\n"
                                                      "💸 К выплате: <b>{due}</b>"),
    # ---------- курс ----------
    "course_done": ("📚 Курс: кнопка в конце", "🚀 Создать магазин"),
    # ---------- пуш ----------
    "push_app": ("📲 Пуш «открой приложение»", (
        "👋 {name}, ты заглянул в конструктор, но ещё не открыл приложение.\n\nТам за 2 минуты можно собрать витрину "
        "своего магазина и посмотреть, как она будет выглядеть — бесплатно 👇")),
    # ---------- чат с куратором ----------
    "chat_reply": ("💬 Ответ куратора (в чат)", "💬 <b>Ответ куратора:</b>\n\n{text}"),
    # ---------- проверенный магазин ----------
    "verified": ("🏅 Магазин стал «Проверенным»", "🏅 <b>Поздравляем!</b> У @{username} уже {n} продаж — магазин "
                                                 "получил значок «✅ Проверенный магазин». Покупатели видят его в "
                                                 "приветствии и в мини-приложении."),
    "banned": ("⛔ Блокировка", "⛔ Доступ к конструктору закрыт."),
    "banned_illegal": ("🚫 Блокировка за незаконный бот", (
        "🚫 <b>Доступ к конструктору закрыт</b>\n\nТвой бот нарушает правила: в нём незаконные товары или услуги. "
        "Магазины остановлены.\n\nЕсли считаешь, что это ошибка, — напиши в поддержку.")),
    "maint": ("🛠 Техработы", "🛠 <b>Конструктор на техработах</b>\n\nСовсем скоро вернёмся — попробуй чуть позже. "
                             "Уже созданные магазины работают как обычно."),
    "sub_prompt": ("📣 Обязательная подписка", "📣 <b>Чтобы пользоваться конструктором, подпишись:</b>\n\n"
                                               "{channels}\n\nПодписался — жми «✅ Я подписался»."),
    "sub_not_yet": ("📣 Ещё не подписан", "Подписка ещё не найдена — подпишись на все каналы и нажми снова."),
}

# Тексты мини-приложения конструктора. Можно с премиум-эмодзи.
APP_TEXTS = {
    "app_title": ("Заголовок карточки", "heliys конструктор"),
    "app_mode": ("Мастер: шаг «какой бот»", "Какой бот нужен?"),
    "app_mode_sub": ("Мастер: подпись шага «какой бот»", "Можно с витриной-мини-приложением или классический бот с кнопками"),
    "app_mode_app": ("Вариант «с мини-приложением»", "С мини-приложением"),
    "app_mode_app_sub": ("Подпись «с мини-приложением»", "Витрина с карточками, поиском и избранным, свой цвет и стиль"),
    "app_mode_bot": ("Вариант «без мини-приложения»", "Без мини-приложения"),
    "app_mode_bot_sub": ("Подпись «без мини-приложения»", "Каталог и покупка кнопками прямо в чате — проще и быстрее"),
    "app_sub": ("Подзаголовок карточки", "Свой магазин в Telegram за 5 минут"),
    "app_badge": ("Бейдж на карточке", "Конструктор"),
    "app_create": ("Кнопка «Создать»", "Создать бота"),
    "app_create_sub": ("Подпись под «Создать»", "Магазин как @heliys_shop_bot — со своим цветом, стилем и приветствием"),
    "app_feat_title": ("Заголовок «Что внутри»", "Что будет в твоём боте"),
    "app_feat1": ("Пункт 1", "Мини-приложение с витриной, поиском и избранным"),
    "app_feat2": ("Пункт 2", "Автовыдача товаров 24/7"),
    "app_feat3": ("Пункт 3", "Оплата СБП, звёздами, CryptoBot и xRocket"),
    "app_feat4": ("Пункт 4", "Поддержка, рефералы, промокоды, статусы"),
    "app_feat5": ("Пункт 5", "Админ-панель: тексты, кнопки, премиум-эмодзи"),
    "app_feat6": ("Пункт 6 (куратор)", "Личный куратор: поможет с рекламным текстом, товарами и настройкой"),
    "app_home": ("Вкладка «Главная»", "Главная"),
    "app_bots": ("Вкладка «Мои боты»", "Мои боты"),
    "app_profile": ("Вкладка «Профиль»", "Профиль"),
    "app_balance": ("«Баланс»", "Баланс"),
    "app_topup": ("«Пополнить»", "Пополнить"),
    "app_support": ("«Поддержка»", "Поддержка"),
    "app_no_bots": ("Нет ботов", "Пока нет ботов — создай первый"),
    "app_step1": ("Шаг 1 — заголовок", "Выбери цвет"),
    "app_step1_sub": ("Шаг 1 — подпись", "Основной цвет кнопок и акцентов витрины"),
    "app_custom": ("«Свой цвет»", "Ввести свой цвет"),
    "app_step2": ("Шаг 2 — заголовок", "Выбери стиль"),
    "app_step2_sub": ("Шаг 2 — подпись", "Анимация и значок на главной карточке"),
    "app_step3": ("Шаг 3 — заголовок", "Заголовок витрины"),
    "app_step3_sub": ("Шаг 3 — подпись", "Название магазина на главной карточке"),
    "app_step4": ("Шаг 4 — заголовок", "Описание витрины"),
    "app_step4_sub": ("Шаг 4 — подпись", "Что продаёшь и почему у тебя — выбери вариант или напиши своё"),
    "app_next": ("«Далее»", "Далее"),
    "app_back": ("«Назад»", "Назад"),
    "app_finish": ("Финальная кнопка", "Продолжить в чате"),
    "app_finish_hint": ("Подсказка у финальной кнопки", "Дальше бот предложит набор товаров, попросит приветствие, "
                                                         "поддержку и токен"),
    "app_preview": ("«Так будет выглядеть»", "Так будет выглядеть витрина"),
    "app_trial": ("Плашка пробного", "{days} бесплатно"),
    "app_price": ("Плашка цены", "Тарифы от {min}"),
    "app_price_label": ("Подпись цены на карточке", "Магазин от"),
    "app_tariffs": ("Тарифы — заголовок", "Тарифы"),
    "app_tariffs_more": ("Кнопка «Подробнее о тарифах»", "Подробнее о тарифах"),
    "app_tariff_pick": ("Кнопка «Выбрать тариф»", "Выбрать"),
    "app_faq": ("FAQ — заголовок", "Частые вопросы"),
    "app_faq_search": ("FAQ — поиск", "Поиск по вопросам"),
    "app_faq_empty": ("FAQ — ничего не найдено", "Ничего не нашлось — спроси куратора в чате"),
    "app_chat": ("Чат с куратором — заголовок", "Чат с куратором"),
    "app_chat_hint": ("Чат — подсказка", "Куратор отвечает обычно в течение часа. Ответ придёт и в чат с ботом."),
    "app_chat_ph": ("Чат — поле ввода", "Напиши вопрос…"),
    "app_course": ("Кнопка «Бесплатный курс»", "Бесплатный курс по продажам"),
    "app_ob1_t": ("Слайд 1 — заголовок", "Свой магазин в Telegram"),
    "app_ob1_x": ("Слайд 1 — текст", "Мини-приложение, автовыдача 24/7 и оплата звёздами, криптой и СБП — без "
                                     "программирования"),
    "app_ob2_t": ("Слайд 2 — заголовок", "Готов за 5 минут"),
    "app_ob2_x": ("Слайд 2 — текст", "Выбери цвет, стиль и набор товаров — витрина собирается у тебя на глазах"),
    "app_ob3_t": ("Слайд 3 — заголовок", "Куратор поможет"),
    "app_ob3_x": ("Слайд 3 — текст", "Личный куратор подскажет с товарами, ценами и первыми продажами. Начни с "
                                     "бесплатного пробного периода"),
    "app_ob_next": ("Слайды — «Дальше»", "Дальше"),
    "app_ob_start": ("Слайды — «Начать»", "Начать"),
    "app_topup_title": ("Пополнение — заголовок", "Пополнение баланса"),
    "app_topup_hint": ("Пополнение — подсказка", "Реквизиты СБП придут в чат с ботом, чек проверит админ"),
    "app_plan_title": ("Выбор тарифа — заголовок", "Как запустим магазин?"),
    "app_plan_trial": ("Тариф «Пробный»", "Пробный период"),
    "app_plan_trial_sub": ("Тариф «Пробный» — подпись", "{days} бесплатно — понравится, купишь"),
    "app_plan_used": ("Пробный уже использован", "Пробный период уже использован"),
    "app_plan_buy": ("Тариф «Купить»", "Купить тариф"),
    "app_plan_buy_sub": ("Тариф «Купить» — подпись", "Оплата после настройки магазина"),
    "app_buy_sent": ("Покупка — способы оплаты в чате", "Способы оплаты отправлены в чат с ботом"),
    "app_sub_title": ("Подписка — заголовок", "Подпишись, чтобы продолжить"),
    "app_sub_text": ("Подписка — текст", "Конструктор доступен подписчикам каналов ниже"),
    "app_sub_check": ("Подписка — кнопка проверки", "Я подписался"),
}
TEXTS.update(APP_TEXTS)


class _Safe(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def tx(key, **kw):
    s = get("t:" + key)
    if s is None:
        s = TEXTS[key][1]
    if not kw:
        return s
    try:
        return s.format_map(_Safe(kw))
    except (ValueError, IndexError, KeyError, AttributeError):
        return s


def plain(s):
    return re.sub(r"<[^>]+>", "", s or "")


# ======================= кнопки =======================
# ключ -> (название в админке, текст по умолчанию, цвет по умолчанию)
BUTTONS = {
    "create": ("Создать бота", "🤖 Создать своего бота", "success"),
    "app": ("Открыть приложение", "📱 Открыть приложение", "primary"),
    "bots": ("Мои боты", "🧾 Мои боты", None),
    "topup": ("Пополнить баланс", "💳 Пополнить баланс", None),
    "support": ("Поддержка", "💬 Поддержка", None),
    "menu": ("Главное меню", "🏠 Главное меню", None),
    "ok": ("Всё верно", "✅ Всё верно", "success"),
    "edit": ("Изменить", "✏️ Изменить", None),
    "preview": ("Показать приветствие", "👀 Показать приветствие", None),
    "paid": ("Я оплатил", "✅ Я оплатил", "success"),
    "cancel": ("Отмена", "❌ Отмена", "danger"),
    "back": ("Назад", "◀️ Назад", None),
    "default_welcome": ("Готовое приветствие", "✨ Использовать готовое", "primary"),
    "my_support": ("Поддержка — мой профиль", "👤 Мой профиль", "primary"),
    "skip": ("Пропустить", "⏭ Пропустить", None),
    "mode_app": ("Кнопка «С мини-приложением»", "📱 С мини-приложением", None),
    "mode_bot": ("Кнопка «Без мини-приложения»", "💬 Без мини-приложения", None),
    "custom_color": ("Свой цвет (в чате)", "🎨 Ввести свой цвет", None),
    "botfather": ("Открыть @BotFather", "🔗 Открыть @BotFather", "primary"),
    "buy": ("Купить навсегда", "💳 Купить навсегда", "success"),
    "new_token": ("Новый токен", "🔑 Прислать новый токен", None),
    "restart": ("Начать заново", "🔄 Начать заново", None),
    "sub_check": ("Я подписался", "✅ Я подписался", "success"),
    "curator": ("Написать куратору", "👨‍💼 Написать куратору", "primary"),
    "trial": ("Пробный период", "🎁 Пробный период", "success"),
    "pay_stars": ("Оплата звёздами", "⭐ Звёзды", "primary"),
    "pay_cryptobot": ("Оплата CryptoBot", "💎 CryptoBot", None),
    "pay_xrocket": ("Оплата xRocket", "🚀 xRocket", None),
    "pay_sbp": ("Оплата СБП", "💳 СБП", None),
    "pay_balance": ("Оплата с баланса", "💰 С баланса", None),
    "pay_open": ("Открыть счёт (крипта)", "💎 Оплатить", "success"),
    "pay_check": ("Проверить оплату", "🔄 Проверить оплату", None),
    "ref": ("Пригласить друга", "🤝 Пригласить друга", None),
    "ref_share": ("Поделиться ссылкой", "📤 Поделиться ссылкой", "primary"),
    "promo": ("Промокод", "🎟 Промокод", None),
    "pay_free": ("Создать бесплатно (100% скидка)", "🎁 Получить бесплатно", "success"),
    "autobuy": ("Автопродление (вкл/выкл)", "🔁 Автопродление", None),
    "ad": ("Реклама для магазина (нейросеть)", "🪄 Реклама", "primary"),
    "ad_more": ("Реклама: ещё варианты", "🔄 Ещё варианты", None),
    "tariffs": ("Тарифы", "💎 Тарифы", None),
    "renew": ("Продлить / купить", "💳 Продлить / купить", "success"),
    "owners_chat": ("Чат владельцев", "👥 Чат владельцев", "primary"),
    "addons": ("Дополнения", "🛍 Дополнения", None),
    "course": ("Бесплатный курс", "📚 Бесплатный курс", None),
    "course_next": ("Курс: дальше", "Дальше ▶️", "primary"),
    "partner": ("Партнёрка (для партнёров)", "🤝 Партнёрка", None),
}
STYLES = {"": "обычный", "primary": "синий", "success": "зелёный", "danger": "красный"}


def bt(key):
    return get("b:" + key) or BUTTONS[key][1]


def bicon(key):
    return get("bi:" + key)


def bstyle(key):
    s = get("bs:" + key)
    if s is None:
        return BUTTONS[key][2]
    return s or None


# ======================= иконки мини-приложения =======================
ICON_SLOTS = {
    "badge": ("Бейдж на карточке", "🏗"),
    "create": ("Кнопка «Создать»", "🤖"),
    "bots": ("Мои боты", "🧾"),
    "topup": ("Пополнить", "💳"),
    "support": ("Поддержка", "💬"),
    "feat": ("Пункты «Что внутри»", "✨"),
    "trial": ("Плашка пробного", "🎁"),
    "home": ("Вкладка «Главная»", "🏠"),
    "buy": ("Тариф «Купить навсегда»", "💳"),
    "stars": ("Значок «Звёзды»", "⭐"),
    "crypto": ("Значок «Крипта»", "💎"),
    "sbp": ("Значок «СБП»", "🏦"),
    "profile": ("Вкладка «Профиль»", "👤"),
}


def icons():
    return {k: {"e": d, "id": get("ai:" + k)} for k, (_, d) in ICON_SLOTS.items()}


# ======================= пользователи =======================
def user(uid):
    return db.q1("SELECT * FROM ctor_users WHERE id=?", (uid,))


def touch_user(u):
    """Регистрирует пользователя Telegram или обновляет имя. -> строка из базы."""
    row = user(u.id)
    if row is None:
        db.x("INSERT INTO ctor_users(id, username, first_name, balance, joined) VALUES (?, ?, ?, 0, ?)",
             (u.id, u.username, u.first_name, db.now()))
    elif row["username"] != u.username or row["first_name"] != u.first_name:
        db.x("UPDATE ctor_users SET username=?, first_name=? WHERE id=?", (u.username, u.first_name, u.id))
    return user(u.id)


def touch_tg(tg):
    """То же для данных из мини-приложения (dict initData.user)."""
    class _U:
        id = tg["id"]
        username = tg.get("username")
        first_name = tg.get("first_name")
    return touch_user(_U)


def add_balance(uid, amount):
    db.x("UPDATE ctor_users SET balance=ROUND(balance+?, 2) WHERE id=?", (amount, uid))


def take_balance(uid, amount):
    """Списывает сумму, только если её хватает. -> True/False (атомарно)."""
    cur = db.conn.execute("UPDATE ctor_users SET balance=ROUND(balance-?, 2) WHERE id=? AND balance>=?",
                          (amount, uid, amount))
    db.conn.commit()
    return cur.rowcount == 1


def user_ids():
    return [r[0] for r in db.q("SELECT id FROM ctor_users WHERE banned=0")]


def user_link(u):
    if not u:
        return "?"
    name = html.escape(u["first_name"] or "user")
    uname = f" (@{u['username']})" if u["username"] else ""
    return f'<a href="tg://user?id={u["id"]}">{name}</a>{uname} <code>{u["id"]}</code>'


# ======================= пополнения =======================
def create_topup(uid, amount):
    db.x("UPDATE ctor_topups SET status='canceled' WHERE user_id=? AND status='wait_pay'", (uid,))
    return db.x("INSERT INTO ctor_topups(user_id, amount, status, created) VALUES (?, ?, 'wait_pay', ?)",
                (uid, amount, db.now()))


def topup(tid):
    return db.q1("SELECT * FROM ctor_topups WHERE id=?", (tid,))


def topup_wait(uid):
    return db.q1("SELECT * FROM ctor_topups WHERE user_id=? AND status='wait_pay' ORDER BY id DESC LIMIT 1", (uid,))


def set_topup(tid, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    db.x(f"UPDATE ctor_topups SET {sets} WHERE id=?", (*kw.values(), tid))


# ======================= черновики магазинов =======================
def draft(uid):
    """-> (данные, шаг)."""
    r = db.q1("SELECT data, step FROM ctor_drafts WHERE user_id=?", (uid,))
    if not r:
        return {}, None
    try:
        return json.loads(r["data"] or "{}"), r["step"]
    except ValueError:
        return {}, r["step"]


def save_draft(uid, data, step=None):
    db.x("INSERT INTO ctor_drafts(user_id, data, step, updated) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
         "data=excluded.data, step=excluded.step, updated=excluded.updated",
         (uid, json.dumps(data, ensure_ascii=False), step, db.now()))


def set_step(uid, step):
    db.x("UPDATE ctor_drafts SET step=?, updated=? WHERE user_id=?", (step, db.now(), uid))


def drop_draft(uid):
    db.x("DELETE FROM ctor_drafts WHERE user_id=?", (uid,))


# порядок шагов мастера: первый незаполненный — следующий
ORDER = ("mode", "color", "style", "title", "desc", "template", "welcome", "support", "token")
APP_ONLY = ("color", "style")  # шаги, которые нужны только магазину с мини-приложением


def no_app(d):
    """Покупатель выбрал бота без мини-приложения: магазин работает кнопками в чате."""
    return d.get("mode") == "bot"


def ban_text(u):
    """Что видит забаненный: за незаконный бот — отдельный текст."""
    return tx("banned_illegal" if u and u["ban_reason"] == "illegal" else "banned")


def ban_label(u):
    if not u or not u["banned"]:
        return "✅ активен"
    return "🚫 <b>в бане за незаконный бот</b>" if u["ban_reason"] == "illegal" else "⛔ <b>в бане</b>"


def mkbot_hidden(b):
    """Кнопка «🤖 Создать своего бота» скрыта в этом магазине (для всех магазинов или для одного)."""
    return get("mkbot_off") == "1" or bool(b["no_mkbot"] if "no_mkbot" in b.keys() else 0)

# ======================= шаблоны магазинов =======================
# ключ -> (кнопка, описание, [(категория, [(товар, описание, цена, выдача)])]).
# Выдача: auto — со склада (создаётся без остатка), manual — вручную. Товары с ручной выдачей создаются
# скрытыми (active=0), чтобы покупатель не оплатил услугу, которую владелец ещё не готов оказать.
TEMPLATES = {
    "empty": ("📭 Пустой магазин", "Добавлю категории и товары сам", []),
    "accounts": ("🎮 Аккаунты", "Игровые и соцсети", [
        ("🎮 Игровые аккаунты", [
            ("Steam — аккаунт с играми", "Аккаунт Steam с купленными играми. Данные для входа придут сразу после оплаты.", 299, "auto"),
            ("Epic Games — аккаунт", "Аккаунт Epic Games с библиотекой игр. Почта меняется.", 199, "auto"),
            ("Minecraft Java — лицензия", "Лицензионный аккаунт Minecraft Java Edition.", 499, "auto"),
        ]),
        ("📱 Соцсети", [
            ("Telegram — аккаунт", "Готовый аккаунт Telegram, вход по коду.", 149, "auto"),
            ("Instagram — аккаунт", "Аккаунт Instagram с подтверждённой почтой.", 99, "auto"),
            ("TikTok — аккаунт", "Чистый аккаунт TikTok для продвижения.", 89, "auto"),
        ]),
    ]),
    "subs": ("🔑 Подписки и ключи", "Сервисы, ключи активации", [
        ("🎧 Подписки", [
            ("Spotify Premium — 1 месяц", "Подписка Spotify Premium на ваш аккаунт.", 199, "auto"),
            ("YouTube Premium — 1 месяц", "YouTube без рекламы и с фоновым воспроизведением.", 249, "auto"),
            ("Discord Nitro — 1 месяц", "Ссылка-подарок Discord Nitro.", 349, "auto"),
        ]),
        ("🔑 Ключи активации", [
            ("Windows 11 Pro — ключ", "Ключ активации Windows 11 Pro, привязывается к ПК.", 390, "auto"),
            ("Office 2021 — ключ", "Ключ Microsoft Office 2021 Pro Plus.", 490, "auto"),
        ]),
    ]),
    "ai": ("🤖 AI-сервисы", "ChatGPT, Midjourney и другие", [
        ("🤖 AI-сервисы", [
            ("ChatGPT Plus — 1 месяц", "Доступ к ChatGPT Plus на месяц.", 1490, "auto"),
            ("Midjourney — 1 месяц", "Подписка Midjourney Basic.", 990, "auto"),
            ("Claude Pro — 1 месяц", "Доступ к Claude Pro на месяц.", 1590, "auto"),
        ]),
        ("🧠 Аккаунты AI", [
            ("ChatGPT — аккаунт", "Готовый аккаунт ChatGPT с почтой.", 149, "auto"),
        ]),
    ]),
    "numbers": ("📱 Номера", "Номера для регистрации", [
        ("📱 Номера для Telegram", [
            ("Номер РФ для Telegram", "Номер для регистрации Telegram, код придёт в бот.", 79, "auto"),
            ("Номер США для Telegram", "Иностранный номер для регистрации Telegram.", 99, "auto"),
        ]),
        ("💬 Номера для WhatsApp", [
            ("Номер РФ для WhatsApp", "Номер для регистрации WhatsApp.", 59, "auto"),
        ]),
    ]),
    "services": ("🛠 Услуги", "Дизайн, монтаж, помощь", [
        ("🎨 Дизайн", [
            ("Аватарка для канала", "Уникальная аватарка для канала или бота. Срок — 1 день.", 500, "manual"),
            ("Баннер для поста", "Рекламный баннер под ваш пост.", 700, "manual"),
        ]),
        ("🎬 Монтаж", [
            ("Монтаж ролика до 1 минуты", "Shorts / Reels / TikTok с титрами и музыкой.", 900, "manual"),
        ]),
    ]),
}


def template_label(d):
    t = TEMPLATES.get(d.get("template") or "empty")
    return t[0] if t else "—"


def template_counts(key):
    cats = TEMPLATES.get(key, ("", "", []))[2]
    return len(cats), sum(len(items) for _, items in cats)


def next_step(d):
    for k in ORDER:
        if k in APP_ONLY and no_app(d):
            continue
        if k not in d:
            return k
    return "confirm"


def clean_title(text):
    return re.sub(r"\s+", " ", plain(text or "")).strip()[:40]


def clean_desc(text):
    return re.sub(r"[ \t]+", " ", plain(text or "")).strip()[:200]


def desc_ideas(title=""):
    name = clean_title(title) or "наш магазин"
    return [
        "Цифровые товары с автовыдачей 24/7 — быстро, честно, с гарантией",
        f"{name}: аккаунты, подписки и ключи по лучшим ценам",
        "Моментальная выдача после оплаты, поддержка всегда на связи",
        "Оплата СБП, звёздами и криптой. Выдача за секунды",
    ]


def default_welcome(d):
    title = html.escape(clean_title(d.get("title")) or "мой магазин")
    desc = html.escape(clean_desc(d.get("desc")))
    return (f"✨ <b>{title}</b>\n" + (f"{desc}\n" if desc else "") +
            "\n<blockquote>👋 Привет, <b>{name}</b>!\n💰 Баланс: <b>{balance}</b></blockquote>\n"
            "⚡ Автовыдача 24/7  ·  💬 Поддержка прямо в боте\n\n👇 Открывай магазин")
