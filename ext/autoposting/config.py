import os
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH", "")

WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
# Свой порт для Mini App. Переменную PORT не используем: на хостинге её занимает служебный сервер
PORT = int(os.getenv("WEB_PORT") or 8080)

CRYPTOPAY_TOKEN = os.getenv("CRYPTOPAY_TOKEN", "")
XROCKET_TOKEN = os.getenv("XROCKET_TOKEN", "")
STAR_RATE_RUB = float((os.getenv("STAR_RATE_RUB") or "1.5").replace(",", "."))

# Ключ шифрования сессий аккаунтов. Создаётся один раз и дописывается в .env;
# если его потерять, все подключённые аккаунты придётся подключать заново.
SESSION_KEY = os.getenv("SESSION_KEY", "")
if not SESSION_KEY:
    # в конструкторе у каждого бота своя папка данных: ключ лежит рядом с базой, а не в общем .env
    _kf = Path(os.getenv("DATA_DIR") or BASE_DIR / "data") / "session.key"
    _kf.parent.mkdir(parents=True, exist_ok=True)
    if _kf.exists():
        SESSION_KEY = _kf.read_text(encoding="utf-8").strip()
    if not SESSION_KEY:
        SESSION_KEY = Fernet.generate_key().decode()
        _kf.write_text(SESSION_KEY, encoding="utf-8")

# На хостинге DATA_DIR указывает на постоянный диск, чтобы база переживала перезапуски
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"

APP_NAME = os.getenv("APP_NAME") or "Heliys AutoPosting"
SUPPORT_URL = os.getenv("SUPPORT_URL") or "https://t.me/BotFather"
POLICY_URL = "https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-08-12-99"
OFFER_URL = "https://telegra.ph/PUBLICHNAYA-OFERTA-08-12-15"

# Пакеты пополнения: hlx -> рубли
PACKAGES = [
    {"id": "p50", "hlx": 50, "rub": 100},
    {"id": "p100", "hlx": 100, "rub": 200},
    {"id": "p200", "hlx": 200, "rub": 380},
    {"id": "p500", "hlx": 500, "rub": 600},
]

# Подписка: цена в hlx
SUB_PLANS = [
    {"id": "d1", "days": 1, "price": 30, "title": "1 день"},
    {"id": "d7", "days": 7, "price": 100, "title": "7 дней"},
    {"id": "d30", "days": 30, "price": 200, "title": "Месяц"},
]

REF_BONUS = 10      # hlx за приглашённого
REF_PERCENT = 10    # % с каждого его пополнения

# Тарифы: Free — бесплатно для всех, Pro — покупается по желанию (цены в SUB_PLANS)
FREE = {"accounts": 5, "chats": 50}
PRO = {"accounts": 10, "chats": 100}
ACC_LIMIT_FREE = FREE["accounts"]
ACC_LIMIT_SUB = PRO["accounts"]

# Ограничения рассылки
INTERVALS = [5, 10, 15, 30, 60, 120, 240, 720, 1440]   # минут паузы после круга
SEND_DELAY = 6                               # секунд между сообщениями в разные чаты
MAX_CHATS = PRO["chats"]
MAX_TEXT = 4000                              # запас до лимита Telegram под подпись бота
MAX_CAPTION = 980                            # подпись к фото: лимит Telegram 1024 минус подпись бота
MAX_PHOTO_MB = 10
MAX_FLOOD_WAIT = 300                         # дольше этого не ждём, а переносим круг

# Автоподписка на каналы, которые требует чат (включается в рассылке по желанию)
AUTOJOIN_PER_DAY = 20                        # не больше вступлений в сутки на один аккаунт
AUTOJOIN_PER_MSG = 3                         # не больше каналов из одного требования

MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
TZ_OFFSET = 3 * 3600                         # «сегодня» в статистике считается по Москве
