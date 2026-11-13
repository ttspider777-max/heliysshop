"""Типы ботов, которые можно создать в конструкторе.

shop    — магазин (main.py --child), весь мастер: цвет, стиль, товары, приветствие.
casino  — игровой бот (casino_main.py --child).
Остальные — отдельные боты из папки ext/<dir> (чат-менеджер, автопостинг, SaveMod): каждый запускается своим процессом `python <entry>` с переменными
окружения (токен, владелец, своя папка данных, порт мини-приложения), см. hosting._ext_env.
Исключены по решению владельца: бот сторис, бот поддержки, парсер лидов и ChatGPT-бот; казино снято с продажи.

Цены и включение типа задаются в админке конструктора (/admin → 🧩 Типы ботов): core.kind_price / core.kind_on.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_DIR = os.path.join(ROOT, "ext")

# ключ -> (название, описание, папка в ext/ (None — не внешний), файл запуска, есть мини-приложение)
KINDS = {
    "shop": ("🛍 Магазин", "Цифровые товары, автовыдача, оплата СБП / звёзды / крипта, мини-приложение", None, None, True),
    "casino": ("🎰 Казино CRX", "Игры на виртуальных CRX: краш, мины, плинко, рулетка, кейсы", None, "casino_main.py", True),
    "chat": ("💬 Чат-менеджер", "Для групп: экономика, игры, модерация, подписка на каналы", "chat_manager", "main.py", False),
    "autopost": ("📣 Автопостинг", "Рассылка по чатам со своих аккаунтов по расписанию", "autoposting", "main.py", True),
    "savemod": ("🕵️ SaveMod", "Бизнес-бот: показывает удалённые и изменённые сообщения", "savemod", "main.py", False),
}
DEFAULT_KIND = "shop"
# сняты с продажи в конструкторе: новые боты такого типа создать нельзя, но уже созданные продолжают работать
RETIRED = {"casino"}
VISIBLE = [x for x in KINDS if x not in RETIRED]


def name(kind):
    return KINDS.get(kind, KINDS[DEFAULT_KIND])[0]


def desc(kind):
    return KINDS.get(kind, KINDS[DEFAULT_KIND])[1]


def ext_dir(kind):
    """Папка внешнего бота или None."""
    d = KINDS.get(kind, ("", "", None))[2]
    return os.path.join(EXT_DIR, d) if d else None


def is_ext(kind):
    return bool(KINDS.get(kind, ("", "", None))[2])


def has_app(kind):
    return KINDS.get(kind, KINDS[DEFAULT_KIND])[4]


def kind_of_cfg(cfg):
    """Тип бота по данным мастера (draft / hosted_bots.cfg)."""
    if not isinstance(cfg, dict):
        return DEFAULT_KIND
    k = cfg.get("kind")
    if k in KINDS:
        return k
    return "casino" if cfg.get("template") == "casino" else DEFAULT_KIND  # старые казино-боты


def kind_of(b):
    """Тип бота из строки hosted_bots."""
    try:
        return kind_of_cfg(json.loads(b["cfg"] or "{}"))
    except (KeyError, IndexError, TypeError, ValueError):
        return DEFAULT_KIND
