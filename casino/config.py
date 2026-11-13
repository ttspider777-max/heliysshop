"""Cursed Casino — настройки. Бот клиента из конструктора: `casino_main.py --child <файл.json>`
(как у магазинов, см. hosting.py). Отдельный запуск: переменные окружения или файл .env рядом с casino_main.py."""
import json
import os
import re
import sys

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env_file(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass


def _child():
    if "--child" not in sys.argv:
        return None
    try:
        with open(sys.argv[sys.argv.index("--child") + 1], encoding="utf-8") as f:
            return json.load(f)
    except (IndexError, OSError, ValueError) as e:
        raise SystemExit(f"не прочитан файл настроек: {e}")


_C = _child()
CHILD = _C is not None
if not CHILD:
    _env_file(os.path.join(_BASE, ".env"))
    _env_file(os.path.join(_BASE, "casino", ".env"))

if CHILD:
    BOT_TOKEN = str(_C.get("token") or "")
    OWNERS = {int(_C["owner"])} if str(_C.get("owner", "")).isdigit() else set()
    OWNERS |= {int(x) for x in _C.get("supers") or [] if str(x).isdigit()}
    DB_PATH = str(_C.get("db") or "")
    NAME = str(_C.get("shop_name") or "Cursed Casino")
    PORT = int(_C.get("port") or 0)
    PUBLIC_URL = str(_C.get("public_url") or "").rstrip("/")
    SUPPORT = str(_C.get("support") or "").lstrip("@")
    HOST = "127.0.0.1"
    # защита как у магазинов клиентов: только свой токен и своя база
    _tid = BOT_TOKEN.split(":", 1)[0]
    if not _tid.isdigit() or int(_tid) != int(_C.get("tg_id") or 0) or int(_tid) == int(_C.get("main_bot_id") or 0):
        print("ОСТАНОВЛЕН: токен не принадлежит боту клиента", file=sys.stderr, flush=True)
        raise SystemExit(3)
    if not re.fullmatch(r"bot_\d+\.db", os.path.basename(DB_PATH)) or not OWNERS or not PORT:
        print("ОСТАНОВЛЕН: неверные настройки бота клиента", file=sys.stderr, flush=True)
        raise SystemExit(3)
else:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    OWNERS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.isdigit()}
    DB_PATH = os.getenv("DB_PATH") or os.path.join(_BASE, "data", "casino.db")
    NAME = os.getenv("CASINO_NAME", "Cursed Casino")
    PORT = int(os.getenv("PORT") or 8081)
    PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").rstrip("/")
    SUPPORT = os.getenv("SUPPORT", "apfov").lstrip("@")
    HOST = "0.0.0.0"

CURRENCY = "CRX"
APP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html")
