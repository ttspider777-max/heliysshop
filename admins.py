"""Список админов бота.

Владельцы (config.ADMINS) прописаны в коде: их нельзя удалить из админки, и только они управляют админами.
Остальных админов добавляют и удаляют в админ-панели → 👮 Админы; список хранится в базе (настройка «admins»).
"""
import config
import db


def owners():
    return set(config.ADMINS)


def extra():
    """Админы, добавленные через админ-панель."""
    raw = db.get_setting("admins") or ""
    return {int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()}


def ids():
    return sorted(owners() | extra())


def is_admin(uid):
    return uid in config.ADMINS or uid in extra()


def is_owner(uid):
    return uid in config.ADMINS


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
