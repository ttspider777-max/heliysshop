import os

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


# CHILD_BOT=1 — это бот клиента, запущенный через «🤖 Создать своего бота» (см. hosting.py).
# Такой бот получает токен, владельца и базу из переменных окружения и не читает .env основного бота.
CHILD = os.getenv("CHILD_BOT") == "1"

if not CHILD:
    _load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Токен бота: переменная окружения BOT_TOKEN на хостинге или строка BOT_TOKEN=... в файле .env.
# В коде токен не хранится, чтобы он не утёк вместе с репозиторием на GitHub.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Администраторы бота (у бота клиента — его владелец)
if CHILD:
    ADMINS = {int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip().isdigit()}
else:
    ADMINS = {1867178992, 8717087613}

# База данных: на Amvera — постоянное хранилище /data, локально — папка data рядом с ботом
_BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH") or (
    "/data/heliys_shop.db" if os.path.isdir("/data") else os.path.join(_BASE, "data", "heliys_shop.db")
)

SHOP_NAME = (os.getenv("SHOP_NAME") or "shop") if CHILD else "heliys shop"
SHOP_TITLE = SHOP_NAME if CHILD else "heliys 𝗌𝗁𝗈𝗉"  # заголовок в приветствии

# Встроенный сайт с документами (/privacy, /terms) — публичные ссылки для платёжной системы.
# На Amvera порт 80 (см. amvera.yaml), локально 8080. Можно задать переменной окружения PORT.
# У ботов клиентов сайт не запускается: порт один на весь хостинг.
WEB_PORT = int(os.getenv("PORT") or (80 if os.path.isdir("/data") else 8080))
PUBLIC_URL = "" if CHILD else os.getenv("PUBLIC_URL", "")  # например https://heliys-shop.amvera.io

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
