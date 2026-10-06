import logging
import time

from aiogram import Bot

import db

log = logging.getLogger(__name__)

_ok_until = {}  # uid -> время, до которого подписку не перепроверяем
OK_TTL = 120


def enabled():
    return db.get_setting("sub_on", "1") == "1"


def forget(uid):
    _ok_until.pop(uid, None)


async def missing(bot: Bot, uid: int) -> list:
    """Каналы обязательной подписки, на которые пользователь ещё не подписан."""
    if not enabled():
        return []
    chans = db.channels()
    if not chans:
        return []
    if _ok_until.get(uid, 0) > time.time():
        return []
    result = []
    for ch in chans:
        try:
            member = await bot.get_chat_member(ch["chat_id"], uid)
        except Exception as e:  # бота убрали из канала и т.п. — не блокируем всех пользователей
            log.warning("Не могу проверить подписку на %s: %s", ch["chat_id"], e)
            continue
        if member.status in ("left", "kicked") or (member.status == "restricted" and not member.is_member):
            result.append(ch)
    if not result:
        _ok_until[uid] = time.time() + OK_TTL
    return result
