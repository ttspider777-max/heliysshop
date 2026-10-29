"""Хостинг ботов клиентов («🤖 Создать своего бота»).

Каждый бот клиента — отдельный процесс `python main.py` на этом же сервере, с переменными окружения:
CHILD_BOT=1, BOT_TOKEN (токен клиента), OWNER_IDS (клиент — владелец и админ), SHOP_NAME и своя база
data/bots/bot_<id>.db. Основной бот следит за процессами: при падении перезапускает, а если бот падает
снова и снова (например, токен отозвали в @BotFather) — останавливает и сообщает владельцу и админам.
После перезапуска сервера все боты со статусом running поднимаются автоматически.
"""
import asyncio
import logging
import os
import re
import sys
import time

from aiogram import Bot
from aiogram.exceptions import TelegramUnauthorizedError

import config
import db

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(ROOT, "main.py")
BOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)), "bots")
LOG_MAX = 1_000_000      # лог бота больше 1 МБ откладывается в .old
MAX_FAILS = 5            # столько падений подряд — и бот останавливается со статусом failed
QUICK_FAIL = 120         # падение раньше чем через 2 минуты после запуска считается «подряд»
START_CHECK = 8          # сколько секунд ждём после запуска, чтобы убедиться, что бот не упал сразу

TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,}$")

_procs = {}   # id бота -> asyncio.subprocess.Process
_tasks = {}   # id бота -> asyncio.Task, который держит процесс
_exits = {}   # id бота -> сколько раз процесс завершался (для проверки запуска)
_bot = None   # основной бот: им отправляем уведомления


class TokenError(Exception):
    """code: format — не похоже на токен, invalid — Telegram не принял токен, network — нет связи."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def db_path(bid):
    return os.path.join(BOTS_DIR, f"bot_{bid}.db")


def log_path(bid):
    return os.path.join(BOTS_DIR, f"bot_{bid}.log")


def find_token(text):
    """Достаёт токен из сообщения (его часто присылают вместе с текстом от @BotFather)."""
    for word in re.split(r"\s+", text or ""):
        word = word.strip("`'\".,;")
        if TOKEN_RE.match(word):
            return word
    return None


async def check_token(token):
    """Проверяет токен через Telegram. Возвращает данные бота (getMe) или бросает TokenError."""
    if not token or not TOKEN_RE.match(token):
        raise TokenError("format")
    bot = Bot(token)
    try:
        return await bot.get_me()
    except TelegramUnauthorizedError:
        raise TokenError("invalid")
    except Exception as e:
        log.warning("проверка токена не удалась: %s", e)
        raise TokenError("network")
    finally:
        await bot.session.close()


def _env(b):
    drop = {"BOT_TOKEN", "DB_PATH", "OWNER_IDS", "SHOP_NAME", "PUBLIC_URL", "PORT", "CHILD_BOT"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(
        CHILD_BOT="1",
        BOT_TOKEN=b["token"],
        DB_PATH=db_path(b["id"]),
        OWNER_IDS=str(b["user_id"]),
        SHOP_NAME=b["shop_name"] or b["username"] or "shop",
        PYTHONUNBUFFERED="1",
        PYTHONIOENCODING="utf-8",
    )
    return env


def is_alive(bid):
    p = _procs.get(bid)
    return p is not None and p.returncode is None


async def _terminate(proc):
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), 10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    except ProcessLookupError:
        pass


async def _run(bid):
    fails = 0
    try:
        while True:
            b = db.hosted(bid)
            if not b or b["status"] != "running" or not b["token"]:
                return
            os.makedirs(BOTS_DIR, exist_ok=True)
            lp = log_path(bid)
            try:
                if os.path.getsize(lp) > LOG_MAX:
                    os.replace(lp, lp + ".old")
            except OSError:
                pass
            started = time.monotonic()
            with open(lp, "ab") as logf:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, MAIN, cwd=ROOT, env=_env(b),
                    stdin=asyncio.subprocess.DEVNULL, stdout=logf, stderr=asyncio.subprocess.STDOUT)
                _procs[bid] = proc
                log.info("бот клиента #%s (@%s) запущен, pid %s", bid, b["username"], proc.pid)
                try:
                    rc = await proc.wait()
                except asyncio.CancelledError:
                    await _terminate(proc)
                    raise
                finally:
                    _procs.pop(bid, None)
                    _exits[bid] = _exits.get(bid, 0) + 1
            b = db.hosted(bid)
            if not b or b["status"] != "running":
                return
            fails = fails + 1 if time.monotonic() - started < QUICK_FAIL else 1
            log.warning("бот клиента #%s завершился с кодом %s (падение %s/%s)", bid, rc, fails, MAX_FAILS)
            if fails >= MAX_FAILS:
                db.set_hosted(bid, status="failed")
                await _on_failed(db.hosted(bid))
                return
            await asyncio.sleep(min(5 * fails, 60))
    finally:
        if _tasks.get(bid) is asyncio.current_task():
            _tasks.pop(bid, None)


async def _on_failed(b):
    from services import safe_send, to_admins  # здесь, чтобы не было циклического импорта
    from texts import t
    if _bot is None or b is None:
        return
    u = db.get_user(b["user_id"])
    await safe_send(_bot, b["user_id"], t("mb_failed", u["lang"] if u else "ru", username=b["username"] or "?"))
    await to_admins(_bot, f"⚠️ Бот клиента #{b['id']} (@{b['username']}) постоянно падает и остановлен.\n"
                          f"Скорее всего, владелец отозвал токен. Лог: <code>{log_path(b['id'])}</code>")


def start(bid):
    """Запускает процесс бота (статус в базе уже должен быть running)."""
    task = _tasks.get(bid)
    if task and not task.done():
        return
    _tasks[bid] = asyncio.create_task(_run(bid))


async def stop(bid):
    task = _tasks.pop(bid, None)
    if task and not task.done():
        task.cancel()
        await asyncio.wait({task})


async def launch(bid):
    """Запуск после получения токена. True — бот работает спустя несколько секунд после старта."""
    before = _exits.get(bid, 0)
    start(bid)
    for _ in range(START_CHECK * 2):
        await asyncio.sleep(0.5)
        if _exits.get(bid, 0) != before:  # процесс успел упасть
            return False
    return is_alive(bid)


def start_all(bot):
    """Поднимает всех ботов со статусом running (вызывается при старте основного бота)."""
    global _bot
    _bot = bot
    n = 0
    for b in db.hosted_running():
        start(b["id"])
        n += 1
    if n:
        log.info("запущено ботов клиентов: %s", n)


async def shutdown():
    tasks = list(_tasks.values())
    _tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks)
