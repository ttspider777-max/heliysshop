"""Обязательная подписка на каналы."""
import logging
import time

import config
import db
from loader import bot

log = logging.getLogger(__name__)

_passed: dict[int, float] = {}   # user_id -> до какого времени не перепроверяем
PASS_TTL = 300


async def missing_channels(user_id) -> list[dict]:
    if user_id in config.ADMIN_IDS:
        return []
    channels = await db.all("SELECT * FROM channels")
    if not channels:
        return []
    if _passed.get(user_id, 0) > time.time():
        return []
    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["chat_id"], user_id)
            ok = member.status in ("creator", "administrator", "member") or getattr(member, "is_member", False)
        except Exception as e:
            # бота убрали из канала или сняли админку — не блокируем людей из-за этого
            log.warning("Не удалось проверить подписку на %s: %s", ch["chat_id"], e)
            ok = True
        if not ok:
            missing.append(ch)
    if not missing:
        _passed[user_id] = time.time() + PASS_TTL
    return missing


def reset_cache():
    _passed.clear()
