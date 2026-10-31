import json
import os
import re
import sys


def _load_env(path):
    """Читает файл .env (KEY=VALUE), если он есть. Переменные окружения хостинга имеют приоритет."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


_BASE = os.path.dirname(os.path.abspath(__file__))

# Бот клиента («🤖 Создать своего бота», см. hosting.py) запускается как `python main.py --child <файл.json>`.
# Все его настройки (токен, владелец, база, порт) берутся ТОЛЬКО из этого файла, а не из переменных окружения:
# хостинг (BotHost) подставляет свои переменные BOT_TOKEN / DB_PATH в каждый процесс, и бот клиента запускался
# с токеном и базой основного бота — клиент становился владельцем основного бота.
EXIT_IDENTITY = 3  # код выхода: бот клиента получил чужой токен или базу (hosting.py сразу останавливает его)


def _identity_fail(msg):
    print(f"ОСТАНОВЛЕН: {msg}", file=sys.stderr, flush=True)
    sys.exit(EXIT_IDENTITY)


def _child_cfg():
    if "--child" not in sys.argv:
        return None
    i = sys.argv.index("--child")
    try:
        with open(sys.argv[i + 1], encoding="utf-8") as f:
            return json.load(f)
    except (IndexError, OSError, ValueError) as e:
        _identity_fail(f"не прочитан файл настроек бота клиента: {e}")


_CHILD_CFG = _child_cfg()
CHILD = _CHILD_CFG is not None

if not CHILD:
    _load_env(os.path.join(_BASE, ".env"))

if CHILD:
    c = _CHILD_CFG
    BOT_TOKEN = str(c.get("token") or "")
    ADMINS = {int(c["owner"])} if str(c.get("owner", "")).isdigit() else set()
    # Владельцы основного бота: в ботах клиентов у них полный доступ к админке (/admin),
    # но чеки и уведомления этих ботов им не приходят — их получает владелец бота.
    SUPER_ADMINS = {int(x) for x in c.get("supers") or [] if str(x).isdigit()}
    DB_PATH = str(c.get("db") or "")
    SHOP_NAME = str(c.get("shop_name") or "shop")
    WEB_PORT = int(c.get("port") or 0)
    PUBLIC_URL = str(c.get("public_url") or "")
    EXPECT_BOT_ID = int(c.get("tg_id") or 0)
    MAIN_BOT_ID = int(c.get("main_bot_id") or 0)
    # защита: бот клиента работает только со своим токеном и своей базой
    _tok_id = BOT_TOKEN.split(":", 1)[0]
    if not _tok_id.isdigit() or int(_tok_id) != EXPECT_BOT_ID or int(_tok_id) == MAIN_BOT_ID:
        _identity_fail("токен не принадлежит боту клиента")
    if (not re.fullmatch(r"bot_\d+\.db", os.path.basename(DB_PATH))
            or os.path.realpath(DB_PATH) == os.path.realpath(str(c.get("main_db") or ""))):
        _identity_fail("бот клиента получил чужую базу")
    if not ADMINS:
        _identity_fail("не указан владелец бота клиента")
    if not WEB_PORT:
        _identity_fail("не указан порт бота клиента")
else:
    # Токен бота: переменная окружения BOT_TOKEN на хостинге или строка BOT_TOKEN=... в файле .env.
    # В коде токен не хранится, чтобы он не утёк вместе с репозиторием на GitHub.
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMINS = {1867178992, 8717087613}
    SUPER_ADMINS = set()
    # База данных: папка data рядом с ботом (или /data, если хостинг даёт постоянное хранилище; путь — DB_PATH)
    DB_PATH = os.getenv("DB_PATH") or (
        "/data/heliys_shop.db" if os.path.isdir("/data") else os.path.join(_BASE, "data", "heliys_shop.db")
    )
    SHOP_NAME = "heliys shop"
    WEB_PORT = int(os.getenv("PORT") or 8080)
    PUBLIC_URL = os.getenv("PUBLIC_URL") or os.getenv("WEBAPP_URL") or ""  # например https://bot-xxx.bothost.tech
    EXPECT_BOT_ID = MAIN_BOT_ID = 0

SHOP_TITLE = SHOP_NAME if CHILD else "heliys 𝗌𝗁𝗈𝗉"  # заголовок в приветствии

# Встроенный сайт: мини-приложение (/app) и документы (/privacy, /terms).
# BotHost: в панели включите «Использовать домен» и укажите порт 8080 (или задайте свой в переменной PORT —
# он должен совпадать с полем «Порт» в панели). Выданный https-адрес вставьте в /admin → 🎨 Мини-приложение →
# 🌐 Адрес сайта (или в переменную PUBLIC_URL / WEBAPP_URL).
# Бот клиента слушает свой внутренний порт, а наружу его выводит основной бот по адресу <сайт>/b/<номер>.
WEB_HOST = "127.0.0.1" if CHILD else "0.0.0.0"

# Значения по умолчанию (всё меняется в админ-панели → ⚙️ Настройки).
# У ботов клиентов ссылки и реквизиты пустые — владелец указывает свои.
REVIEWS_URL = "" if CHILD else "https://t.me/rephel"
SUPPORT_URL = "" if CHILD else "https://t.me/apfov"
SBP_DETAILS = ("<i>реквизиты ещё не указаны — напишите в поддержку</i>" if CHILD
               else "<code>+79161893553</code> — Т-Банк")
REF_PERCENT = 10      # % с покупок рефералов
MIN_WITHDRAW = 50     # минимальный вывод реф. баланса, ₽

# «🤖 Создать своего бота»: цена по умолчанию (меняется в админ-панели → ⚙️ Настройки)
BOT_PRICE = 300

# Просьба об отзыве после покупки (⚙️ Настройки). Пустая ссылка — просьба не отправляется.
REVIEW_URL = "" if CHILD else "https://t.me/heliys_rep/18"
REVIEW_USER = "" if CHILD else "@apfov"

# Оплата звёздами Telegram: сколько рублей стоит 1 ⭐ (цена в звёздах = цена в ₽ / курс, с округлением вверх)
STAR_RATE = 2

# «🔐 Верификация Codex»: номер +1 через API сервиса виртуальных номеров (протокол SMS-Activate)
CODEX_PRICE = 40   # ₽
CODEX_STARS = 20   # ⭐
