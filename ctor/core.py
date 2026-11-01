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
CREATE TABLE IF NOT EXISTS ctor_drafts (
    user_id INTEGER PRIMARY KEY,
    data TEXT,
    step TEXT,
    updated TEXT
);
"""


def init():
    db.conn.executescript(SCHEMA)
    cols = [r["name"] for r in db.conn.execute("PRAGMA table_info(hosted_bots)")]
    for col in ("source", "cfg"):  # source='ctor' — магазин создан через конструктор; cfg — данные мастера
        if col not in cols:
            db.conn.execute(f"ALTER TABLE hosted_bots ADD COLUMN {col} TEXT")
    db.conn.commit()


# ======================= настройки =======================
def get(key, default=None):
    return db.get_setting("c:" + key, default)


def put(key, value):
    db.set_setting("c:" + key, value)


def token():
    """Токен конструктора: из настроек (вводится в основном боте) или из переменной окружения."""
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
        "<blockquote>👋 Привет, <b>{name}</b>!\n💰 Баланс: <b>{balance}</b>\n🤖 Твоих ботов: <b>{bots}</b></blockquote>\n"
        "✨ Мини-приложение, автовыдача товаров, оплата СБП / звёздами / криптой, поддержка и админка — всё уже внутри.\n\n"
        "{trial}👇 Жми «Создать своего бота»")),
    "trial_line": ("🎁 Строка про пробный период", "🎁 Первые <b>{days}</b> — бесплатно, потом {price} навсегда.\n\n"),
    "price_line": ("💰 Строка про цену (без пробного)", "💰 Создание бота — <b>{price}</b>, навсегда.\n\n"),
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
    "pay_trial": ("🎁 Оплата: бесплатно", "🎁 <b>{days} бесплатно</b>, потом {price} навсегда"),
    "pay_price": ("💰 Оплата: с баланса", "💰 <b>{price}</b> спишется с баланса (сейчас {balance})"),
    "edit_menu": ("✏️ Что изменить", "✏️ <b>Что изменить?</b>"),
    "no_money": ("💸 Не хватает денег", "💸 <b>Не хватает на балансе</b>\n\nСоздание бота стоит <b>{price}</b>, "
                                        "на балансе <b>{balance}</b>. Пополни баланс — и вернись к созданию, "
                                        "все данные магазина сохранены."),
    "creating": ("⏳ Создаю магазин", "⏳ Создаю магазин и запускаю бота…"),
    "created": ("✅ Магазин создан", (
        "🎉 <b>Магазин создан!</b>\n\nТвой бот @{username} уже работает.\n\n<blockquote>"
        "1. Открой бота и отправь /admin\n2. Добавь категории и товары: 🛍 Товары и склад\n"
        "3. Укажи реквизиты для оплаты: ⚙️ Настройки\n4. Поменяй тексты, кнопки и премиум-эмодзи: ✏️ Оформление</blockquote>"
        "{trial}")),
    "created_trial": ("🎁 Строка о пробном после создания", "\n\n🎁 Бесплатно до <b>{until}</b>. Купить навсегда можно "
                                                            "в «🧾 Мои боты»."),
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
    "bought": ("♾ Бот куплен", "♾ Бот @{username} куплен навсегда. Спасибо!"),
    "trial_soon": ("⏰ Пробный скоро закончится", "⏰ Пробный период бота @{username} закончится <b>{until}</b>.\n\n"
                                                 "Купи его навсегда за {price}, чтобы магазин не выключился."),
    "trial_over": ("⌛ Пробный закончился", "⌛ Пробный период бота @{username} закончился — бот выключен. Товары и "
                                           "настройки сохранены: купи бота за {price}, и он сразу заработает."),
    "failed": ("⚠️ Бот упал", "⚠️ Бот @{username} перестал работать — скорее всего, токен отозвали в @BotFather. "
                             "Открой «🧾 Мои боты» и пришли новый токен."),
    "retoken": ("🔑 Новый токен для бота", "🔑 Пришли новый токен бота @{username} из @BotFather (/token)."),
    "retoken_other": ("❌ Токен от другого бота", "❌ Это токен другого бота. Нужен токен именно @{username}."),
    "retoken_ok": ("✅ Бот снова работает", "✅ Бот @{username} снова работает."),
    "banned": ("⛔ Блокировка", "⛔ Доступ к конструктору закрыт."),
}

# Тексты мини-приложения конструктора. Можно с премиум-эмодзи.
APP_TEXTS = {
    "app_title": ("Заголовок карточки", "heliys конструктор"),
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
    "app_finish_hint": ("Подсказка у финальной кнопки", "Дальше бот попросит приветствие, поддержку и токен"),
    "app_preview": ("«Так будет выглядеть»", "Так будет выглядеть витрина"),
    "app_trial": ("Плашка пробного", "{days} бесплатно"),
    "app_price": ("Плашка цены", "Навсегда — {price}"),
    "app_topup_title": ("Пополнение — заголовок", "Пополнение баланса"),
    "app_topup_hint": ("Пополнение — подсказка", "Реквизиты СБП придут в чат с ботом, чек проверит админ"),
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
    "custom_color": ("Свой цвет (в чате)", "🎨 Ввести свой цвет", None),
    "botfather": ("Открыть @BotFather", "🔗 Открыть @BotFather", "primary"),
    "buy": ("Купить навсегда", "💳 Купить навсегда", "success"),
    "new_token": ("Новый токен", "🔑 Прислать новый токен", None),
    "restart": ("Начать заново", "🔄 Начать заново", None),
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
ORDER = ("color", "style", "title", "desc", "welcome", "support", "token")


def next_step(d):
    for k in ORDER:
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
