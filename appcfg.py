"""Настройки мини-приложения и «игровых» функций: сезонный стиль, тема, статусы, ежедневный бонус, иконки.

Всё хранится в таблице settings (меняется в админ-панели → 🎨 Мини-приложение), поэтому переживает
перезапуски и обновления кода. Значения по умолчанию — здесь.
"""
import json
from datetime import datetime, timedelta

import config
import db

# ---------- сезонные стили ----------
# ключ -> (название в админке, текст бейджа RU, EN, акцентный цвет)
SEASONS = {
    "halloween": ("🎃 Хэллоуин", "Хэллоуин", "Halloween", "#ff7a1a"),
    "newyear": ("🎄 Новый год", "Новый год", "New Year", "#3fb6ff"),
    "winter": ("❄️ Зима", "Зима", "Winter", "#8fd3ff"),
    "autumn": ("🍂 Осень", "Осень", "Autumn", "#e8913a"),
    "spring": ("🌸 Весна", "Весна", "Spring", "#ff7eb6"),
    "summer": ("☀️ Лето", "Лето", "Summer", "#ffbf1f"),
    "valentine": ("💘 День влюблённых", "14 февраля", "Valentine's", "#ff4d6d"),
    "none": ("⚪ Без стиля", "", "", "#8b7bff"),
}
THEMES = {"dark": "🌑 Тёмная", "light": "☀️ Светлая", "auto": "📱 Как в Telegram"}


def season():
    s = db.get_setting("app_season", "halloween")
    return s if s in SEASONS else "none"


def badge(lang="ru", s=None):
    """Текст бейджа сезона на карточке (у каждого сезона админ может задать свой)."""
    s = s or season()
    own = db.get_setting(f"app_badge:{s}:{lang}")
    if own is not None:
        return own
    _, ru, en, _ = SEASONS[s]
    return en if lang == "en" else ru


def fx_on():
    """Анимированные эффекты сезона (летучие мыши, снег, листья…)."""
    return db.get_setting("app_fx", "1") == "1"


def accent():
    return db.get_setting("app_accent") or SEASONS[season()][3]


def theme():
    t = db.get_setting("app_theme", "dark")
    return t if t in THEMES else "dark"


def card_title():
    return db.get_setting("app_title") or config.SHOP_NAME


# ---------- иконки (премиум-эмодзи) ----------
# Каждый значок мини-приложения можно заменить премиум-эмодзи: ключ -> (название, обычное эмодзи по умолчанию)
ICON_SLOTS = {
    "badge": ("Бейдж сезона на карточке", ""),
    "tab_home": ("Вкладка «Главная»", "🏠"),
    "tab_catalog": ("Вкладка «Каталог»", "🛍"),
    "tab_orders": ("Вкладка «Заказы»", "📦"),
    "tab_profile": ("Вкладка «Профиль»", "👤"),
    "hits": ("Раздел «Хиты»", "🔥"),
    "disc": ("Раздел «Скидки»", "🏷"),
    "new": ("Раздел «Новинки»", "🆕"),
    "fav": ("Раздел «Избранное»", "❤️"),
    "search": ("Поиск", "🔎"),
    "bonus": ("Ежедневный бонус", "🎁"),
    "topup": ("Пополнение баланса", "💳"),
    "status": ("Статус", "🏅"),
    "refs": ("Рефералы", "👥"),
    "promo": ("Промокод", "🎟"),
    "support": ("Поддержка", "💬"),
    "theme": ("Тема", "🌓"),
    "empty": ("Пустой список", "🤷"),
    "success": ("Успешная покупка", "✅"),
}


def icons():
    """{слот: {"e": обычное эмодзи, "id": id премиум-эмодзи или None}}"""
    return {k: {"e": db.get_setting(f"aie:{k}") or d, "id": db.get_setting(f"ai:{k}"),
                "c": bool(db.get_setting(f"aie:{k}"))} for k, (_, d) in ICON_SLOTS.items()}


# ---------- статусы ----------
# Статус зависит от того, сколько реальных денег покупатель принёс в бота (пополнения + оплаты СБП/звёздами).
DEFAULT_STATUSES = [
    {"name": "Генин", "min": 0, "emoji": "🍃"},
    {"name": "Чунин", "min": 500, "emoji": "🌀"},
    {"name": "Джонин", "min": 2000, "emoji": "⚡"},
    {"name": "АНБУ", "min": 5000, "emoji": "🦊"},
    {"name": "Саннин", "min": 10000, "emoji": "🐸"},
]


def _drop_kage_once():
    """Разово убирает статус «Каге» (от 25 000 ₽) из уже сохранённого списка: максимум теперь «Саннин», 10 000 ₽.
    Статусы, которые админ добавит после этого, не трогаются."""
    if db.get_setting("mig_no_kage"):
        return
    try:
        data = json.loads(db.get_setting("statuses") or "null")
        if isinstance(data, list):
            left = [s for s in data if not (s.get("name") == "Каге" and float(s.get("min") or 0) == 25000)]
            if left and len(left) != len(data):
                save_statuses(left)
    except (ValueError, TypeError, AttributeError):
        pass
    db.set_setting("mig_no_kage", "1")


def statuses():
    _drop_kage_once()
    try:
        data = json.loads(db.get_setting("statuses") or "null")
        if isinstance(data, list) and data:
            return sorted(data, key=lambda s: s["min"])
    except (ValueError, KeyError, TypeError):
        pass
    return DEFAULT_STATUSES


def save_statuses(items):
    db.set_setting("statuses", json.dumps(sorted(items, key=lambda s: s["min"]), ensure_ascii=False))


def user_status(u):
    """-> (текущий статус, следующий или None, прогресс 0..100, сколько осталось до следующего)."""
    dep = float((u["deposited"] if u and "deposited" in u.keys() else 0) or 0)
    items = statuses()
    cur, nxt = items[0], None
    for s in items:
        if dep >= s["min"]:
            cur = s
        elif nxt is None:
            nxt = s
    if not nxt:
        return cur, None, 100, 0
    span = max(nxt["min"] - cur["min"], 1)
    pct = int(min(max((dep - cur["min"]) / span * 100, 0), 100))
    return cur, nxt, pct, round(nxt["min"] - dep, 2)


def status_label(u):
    cur = user_status(u)[0]
    return f"{cur.get('emoji') or ''} {cur['name']}".strip()


# ---------- ежедневный бонус ----------
def bonus_on():
    return db.get_setting("bonus_on", "1") == "1"


def bonus_amount():
    try:
        return round(float(db.get_setting("bonus_amount", 3)), 2)
    except ValueError:
        return 3.0


def bonus_left(u):
    """Секунд до следующего бонуса (0 — можно забирать)."""
    last = u["bonus_at"] if u and "bonus_at" in u.keys() else None
    if not last:
        return 0
    try:
        ready = datetime.strptime(last, "%Y-%m-%d %H:%M:%S") + timedelta(days=1)
    except ValueError:
        return 0
    return max(int((ready - datetime.now()).total_seconds()), 0)


def claim_bonus(uid):
    """Начисляет бонус, если прошли сутки. -> сумма или None. Атомарно: двойное нажатие не даст два бонуса."""
    if not bonus_on():
        return None
    amount = bonus_amount()
    if amount <= 0:
        return None
    cur = db.conn.execute(
        """UPDATE users SET balance=ROUND(balance+?, 2), bonus_at=? WHERE id=?
           AND (bonus_at IS NULL OR bonus_at <= datetime('now','localtime','-1 day'))""",
        (amount, db.now(), uid))
    db.conn.commit()
    return amount if cur.rowcount else None


def fmt_left(sec, lang="ru"):
    h, m = sec // 3600, sec % 3600 // 60
    return f"{h}h {m}m" if lang == "en" else f"{h} ч {m} мин"


# ---------- пополнение ----------
def topup_min():
    try:
        return max(float(db.get_setting("topup_min", 50)), 1)
    except ValueError:
        return 50.0


def topup_amounts():
    raw = db.get_setting("topup_amounts", "100,300,500,1000,2000")
    out = []
    for p in raw.replace(" ", "").split(","):
        try:
            v = float(p)
            if v > 0:
                out.append(int(v) if v == int(v) else v)
        except ValueError:
            pass
    return out or [100, 300, 500, 1000]


# ---------- адрес мини-приложения ----------
def public_url():
    if config.CHILD and config.PUBLIC_URL:  # у бота клиента адрес выдаёт основной бот
        return config.PUBLIC_URL.rstrip("/")
    return (db.get_setting("public_url") or config.PUBLIC_URL or "").strip().rstrip("/")


def app_url():
    """Адрес мини-приложения или None, если сайт бота не настроен (Telegram требует https)."""
    base = public_url()
    return f"{base}/app" if base.startswith("https://") else None
