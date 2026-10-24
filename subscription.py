import asyncio
import logging
import time

from aiogram import Bot

import db

log = logging.getLogger(__name__)

_ok_until = {}    # uid -> время, до которого подписку не перепроверяем
_miss_cache = {}  # uid -> (время, список каналов) — короткий кэш для неподписанных
OK_TTL = 120
MISS_TTL = 15     # неподписанного не проверяем по API на каждое нажатие; кнопка «Проверить» сбрасывает кэш


def enabled():
    return db.get_setting("sub_on", "1") == "1"


def forget(uid):
    _ok_until.pop(uid, None)
    _miss_cache.pop(uid, None)


async def _check(bot: Bot, ch, uid):
    try:
        member = await bot.get_chat_member(ch["chat_id"], uid)
    except Exception as e:  # бота убрали из канала и т.п. — не блокируем всех пользователей
        log.warning("Не могу проверить подписку на %s: %s", ch["chat_id"], e)
        return False
    return member.status in ("left", "kicked") or (member.status == "restricted" and not member.is_member)


async def missing(bot: Bot, uid: int) -> list:
    """Каналы обязательной подписки, на которые пользователь ещё не подписан."""
    if not enabled():
        return []
    chans = db.channels()
    if not chans:
        return []
    now = time.time()
    if _ok_until.get(uid, 0) > now:
        return []
    cached = _miss_cache.get(uid)
    if cached and cached[0] > now:
        ids = {c["chat_id"] for c in chans}
        return [c for c in cached[1] if c["chat_id"] in ids]
    flags = await asyncio.gather(*(_check(bot, ch, uid) for ch in chans))
    result = [ch for ch, miss in zip(chans, flags) if miss]
    if result:
        _miss_cache[uid] = (now + MISS_TTL, result)
    else:
        _miss_cache.pop(uid, None)
        _ok_until[uid] = now + OK_TTL
    return result
