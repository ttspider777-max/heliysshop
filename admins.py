"""Список админов бота.

Владельцы (config.ADMINS) прописаны в коде: их нельзя удалить из админки, и только они управляют админами.
Остальных админов добавляют и удаляют в админ-панели → 👮 Админы; список хранится в базе (настройка «admins»).
В боте клиента есть ещё «суперадмины» (config.SUPER_ADMINS) — владельцы основного бота: у них полный доступ,
но в списке админов они не показываются и уведомления бота клиента им не приходят.
"""
import config
import db


def owners():
    return set(config.ADMINS)


def supers():
    return set(config.SUPER_ADMINS)


def extra():
    """Админы, добавленные через админ-панель."""
    raw = db.get_setting("admins") or ""
    return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()}


def ids():
    """Кому слать чеки, обращения и уведомления."""
    return sorted(owners() | extra())


def is_admin(uid):
    return uid in config.ADMINS or uid in config.SUPER_ADMINS or uid in extra()


def is_owner(uid):
    return uid in config.ADMINS or uid in config.SUPER_ADMINS


def is_super(uid):
    return uid in config.SUPER_ADMINS


def _save(s):
    db.set_setting("admins", ",".join(str(i) for i in sorted(s)) or None)


def add(uid):
    s = extra()
    s.add(int(uid))
    _save(s)


def remove(uid):
    s = extra()
    s.discard(int(uid))
    _save(s)
