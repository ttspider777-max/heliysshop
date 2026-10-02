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


_load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Токен бота: переменная окружения BOT_TOKEN на хостинге или строка BOT_TOKEN=... в файле .env.
# В коде токен не хранится, чтобы он не утёк вместе с репозиторием на GitHub.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Администраторы бота
ADMINS = {8717087613}

# База данных: на Amvera — постоянное хранилище /data, локально — папка data рядом с ботом
_BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH") or (
    "/data/heliys_shop.db" if os.path.isdir("/data") else os.path.join(_BASE, "data", "heliys_shop.db")
)

# Значения по умолчанию (всё меняется в админ-панели → ⚙️ Настройки)
REVIEWS_URL = "https://t.me/rephel"
SUPPORT_URL = "https://t.me/apfov"
SBP_DETAILS = "<code>+79161893553</code> — Т-Банк"
REF_PERCENT = 10      # % с покупок рефералов
MIN_WITHDRAW = 50     # минимальный вывод реф. баланса, ₽
