"""API сервиса виртуальных номеров для «🔐 Верификация Codex».

Протокол SMS-Activate (handler_api.php) — его поддерживает большинство сервисов номеров
(SMS-Activate и его клоны: Grizzly SMS, SMSHub, SMS-Man и др.). Настройки — админ-панель → 🔐 Верификация Codex:
адрес API, ключ, код сервиса и код страны. Выдаются только номера +1: если сервис дал другой — номер отменяется.
"""
import asyncio
import logging

import aiohttp

import db

log = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=25)

# значения по умолчанию в протоколе SMS-Activate: dr — OpenAI/ChatGPT/Codex, 187 — США
DEFAULTS = {"cx_api_url": "", "cx_api_key": "", "cx_service": "dr", "cx_country": "187"}

ERRORS = {
    "NO_NUMBERS": "нет свободных номеров",
    "NO_BALANCE": "на балансе сервиса номеров нет денег",
    "BAD_KEY": "неверный API-ключ",
    "BAD_SERVICE": "неверный код сервиса",
    "BAD_ACTION": "сервис не понимает запрос (проверьте адрес API)",
    "ERROR_SQL": "ошибка на стороне сервиса",
    "NO_ACTIVATION": "активация не найдена",
    "BANNED": "аккаунт в сервисе номеров заблокирован",
}


class NumError(Exception):
    pass


def opt(key):
    return db.get_setting(key, DEFAULTS[key]) or DEFAULTS[key]


def configured():
    return bool(opt("cx_api_url") and opt("cx_api_key"))


async def _call(**params):
    url = opt("cx_api_url")
    if not configured():
        raise NumError("API номеров не подключено")
    params["api_key"] = opt("cx_api_key")
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
            async with s.get(url, params={k: str(v) for k, v in params.items()}) as r:
                text = (await r.text()).strip()
    except asyncio.TimeoutError:
        raise NumError("сервис номеров не ответил за 25 секунд")
    except aiohttp.ClientError as e:
        raise NumError(f"нет соединения с сервисом номеров: {e}")
    return text


def _err(text):
    key = text.split(":")[0]
    return NumError(f"{ERRORS.get(key, 'ответ сервиса')}: {text[:200]}")


async def balance():
    text = await _call(action="getBalance")
    if text.startswith("ACCESS_BALANCE:"):
        return text.split(":", 1)[1]
    raise _err(text)


async def get_number():
    """Берёт номер +1. -> (id активации, номер без «+», например 12025550123)."""
    text = await _call(action="getNumber", service=opt("cx_service"), country=opt("cx_country"))
    if not text.startswith("ACCESS_NUMBER:"):
        raise _err(text)
    _, act_id, number = text.split(":", 2)
    number = "".join(ch for ch in number if ch.isdigit())
    if not (number.startswith("1") and len(number) == 11):
        await cancel(act_id)
        raise NumError(f"сервис выдал номер не +1 ({number}) — проверьте код страны")
    try:
        await _call(action="setStatus", id=act_id, status=1)  # «номер введён, ждём SMS» — нужно не всем сервисам
    except NumError:
        pass
    return act_id, number


async def get_code(act_id):
    """Код из SMS или None, если SMS ещё не пришла."""
    text = await _call(action="getStatus", id=act_id)
    if text.startswith("STATUS_OK:"):
        return text.split(":", 1)[1].strip()
    if text.startswith(("STATUS_WAIT_CODE", "STATUS_WAIT_RETRY", "STATUS_WAIT_RESEND")):
        return None
    raise _err(text)


async def finish(act_id):
    try:
        await _call(action="setStatus", id=act_id, status=6)
    except NumError as e:
        log.warning("не удалось завершить активацию %s: %s", act_id, e)


async def cancel(act_id):
    try:
        await _call(action="setStatus", id=act_id, status=8)
    except NumError as e:
        log.warning("не удалось отменить активацию %s: %s", act_id, e)
