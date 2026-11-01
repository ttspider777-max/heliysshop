"""Защита от флуда и спама: слишком много нажатий/сообщений от одного человека — короткая пауза.

Срабатывает, если за WINDOW секунд пришло больше LIMIT событий: человек на BLOCK секунд игнорируется
(один раз получает «не так быстро»). Админов не трогает. Настоящую DDoS-защиту сети даёт хостинг —
это защита бота от спама кнопками и сообщениями, которая не даёт одному человеку «положить» магазин.
"""
import time

WINDOW = 10      # секунд
LIMIT = 25       # событий за окно
BLOCK = 30       # секунд паузы

_hits = {}       # uid -> [время событий]
_blocked = {}    # uid -> до какого времени игнорируем
_warned = set()


def check(uid, now=None):
    """-> "ok" | "warn" (только что попал в паузу — предупредить) | "block" (игнорировать)."""
    now = now or time.monotonic()
    until = _blocked.get(uid)
    if until:
        if now < until:
            return "block"
        _blocked.pop(uid, None)
        _warned.discard(uid)
    hits = [t for t in _hits.get(uid, ()) if now - t < WINDOW]
    hits.append(now)
    _hits[uid] = hits
    if len(hits) > LIMIT:
        _blocked[uid] = now + BLOCK
        _hits.pop(uid, None)
        if uid not in _warned:
            _warned.add(uid)
            return "warn"
        return "block"
    if len(_hits) > 50000:  # не копим память на старых пользователях
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW]:
            _hits.pop(k, None)
    return "ok"


WARN_TEXT = "⏳ Слишком много действий подряд — подожди 30 секунд."
