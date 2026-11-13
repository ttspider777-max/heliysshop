"""Подключённые Telegram-аккаунты пользователей (Telethon)."""
import logging
import re
import time

from cryptography.fernet import Fernet
from telethon import TelegramClient
from telethon.errors import (
    AuthKeyUnregisteredError, FloodWaitError, PasswordHashInvalidError, PhoneCodeExpiredError,
    PhoneCodeInvalidError, PhoneNumberBannedError, PhoneNumberInvalidError, SessionPasswordNeededError,
    SessionRevokedError, UserDeactivatedBanError, UserDeactivatedError,
)
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat

import config
import db
from loader import bot

log = logging.getLogger(__name__)
fernet = Fernet(config.SESSION_KEY.encode())

DEAD_ERRORS = (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError, UserDeactivatedBanError)
CODE_COOLDOWN = 30

clients: dict[int, TelegramClient] = {}    # account_id -> client
pending: dict[int, dict] = {}              # user_id -> незавершённый вход
scans: dict[int, dict] = {}                # account_id -> {chat_id: chat}


class AccError(Exception):
    pass


class AccountDead(Exception):
    pass


def _new_client(session=""):
    if not config.API_ID or not config.API_HASH:
        raise AccError("Подключение аккаунтов ещё не настроено администратором")
    # Имя устройства честное — пользователь увидит эту сессию в «Устройствах» и сможет её завершить
    return TelegramClient(StringSession(session), config.API_ID, config.API_HASH,
                          device_model=config.APP_NAME, system_version="Server", app_version="1.0",
                          lang_code="ru", system_lang_code="ru")


def mask_phone(phone):
    return f"{phone[:3]} ••• •• {phone[-2:]}" if phone and len(phone) > 6 else phone


async def mark_dead(acc):
    await db.run("UPDATE accounts SET alive=0 WHERE id=?", acc["id"])
    await db.run("UPDATE mailings SET status='stopped' WHERE account_id=?", acc["id"])
    client = clients.pop(acc["id"], None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    try:
        await bot.send_message(acc["user_id"], f"⚠️ Аккаунт <b>{acc['name']}</b> отключён: сессия завершена. "
                                                "Рассылки с него остановлены.")
    except Exception:
        pass


async def get_client(acc) -> TelegramClient:
    client = clients.get(acc["id"])
    if client is None:
        client = _new_client(fernet.decrypt(acc["session"].encode()).decode())
        clients[acc["id"]] = client
    try:
        if not client.is_connected():
            await client.connect()
        ok = await client.is_user_authorized()
    except DEAD_ERRORS:
        ok = False
    if not ok:
        await mark_dead(acc)
        raise AccountDead
    return client


# ---------- вход по номеру ----------

async def cancel_login(user_id):
    p = pending.pop(user_id, None)
    if p:
        try:
            await p["client"].disconnect()
        except Exception:
            pass


async def send_code(user, phone):
    phone = "+" + re.sub(r"\D", "", phone or "")
    if len(phone) < 9:
        raise AccError("Введите номер в международном формате")
    count = (await db.one("SELECT COUNT(*) c FROM accounts WHERE user_id=?", user["id"]))["c"]
    if count >= db.acc_limit(user):
        raise AccError(f"Достигнут лимит аккаунтов: {db.acc_limit(user)}")
    old = pending.get(user["id"])
    if old and time.time() - old["ts"] < CODE_COOLDOWN:
        raise AccError("Подождите немного перед повторным запросом кода")
    await cancel_login(user["id"])
    client = _new_client()
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        await client.disconnect()
        raise AccError("Неверный номер телефона")
    except PhoneNumberBannedError:
        await client.disconnect()
        raise AccError("Этот номер заблокирован в Telegram")
    except FloodWaitError as e:
        await client.disconnect()
        raise AccError(f"Telegram просит подождать {e.seconds} сек.")
    pending[user["id"]] = {"client": client, "phone": phone, "hash": sent.phone_code_hash, "ts": time.time()}


async def sign_in(user, code) -> bool:
    """True — вход завершён, False — нужен пароль двухфакторной защиты."""
    p = pending.get(user["id"])
    if not p:
        raise AccError("Сначала запросите код")
    try:
        await p["client"].sign_in(p["phone"], re.sub(r"\D", "", code or ""), phone_code_hash=p["hash"])
    except SessionPasswordNeededError:
        return False
    except PhoneCodeInvalidError:
        raise AccError("Неверный код")
    except PhoneCodeExpiredError:
        await cancel_login(user["id"])
        raise AccError("Код устарел, запросите новый")
    except FloodWaitError as e:
        raise AccError(f"Telegram просит подождать {e.seconds} сек.")
    await _finish(user, p)
    return True


async def sign_in_password(user, password):
    p = pending.get(user["id"])
    if not p:
        raise AccError("Сначала запросите код")
    try:
        await p["client"].sign_in(password=password)
    except PasswordHashInvalidError:
        raise AccError("Неверный пароль")
    except FloodWaitError as e:
        raise AccError(f"Telegram просит подождать {e.seconds} сек.")
    await _finish(user, p)


async def _finish(user, p):
    client = p["client"]
    pending.pop(user["id"], None)
    me = await client.get_me()
    if await db.one("SELECT 1 FROM accounts WHERE tg_id=?", me.id):
        await client.log_out()
        raise AccError("Этот аккаунт уже подключён")
    name = " ".join(x for x in (me.first_name, me.last_name) if x) or "Без имени"
    session = fernet.encrypt(client.session.save().encode()).decode()
    cur = await db.run(
        "INSERT INTO accounts(user_id, tg_id, phone, name, username, session, created_at) VALUES(?,?,?,?,?,?,?)",
        user["id"], me.id, p["phone"], name, me.username, session, int(time.time()))
    clients[cur.lastrowid] = client


async def remove(acc):
    """Завершает сессию в Telegram и удаляет аккаунт из сервиса."""
    if acc["alive"]:
        try:
            client = await get_client(acc)
            await client.log_out()
        except Exception:
            pass
    clients.pop(acc["id"], None)
    scans.pop(acc["id"], None)
    await db.run("DELETE FROM mailing_chats WHERE mailing_id IN (SELECT id FROM mailings WHERE account_id=?)",
                 acc["id"])
    await db.run("DELETE FROM mailings WHERE account_id=?", acc["id"])
    await db.run("DELETE FROM accounts WHERE id=?", acc["id"])


# ---------- чаты ----------

def _can_write(entity) -> bool:
    if getattr(entity, "left", False):
        return False
    if getattr(entity, "creator", False) or getattr(entity, "admin_rights", None):
        return True
    for rights in (getattr(entity, "banned_rights", None), getattr(entity, "default_banned_rights", None)):
        if rights and rights.send_messages:
            return False
    return True


async def scan_chats(acc) -> list[dict]:
    """Группы и супергруппы, в которые аккаунт может писать."""
    client = await get_client(acc)
    found = {}
    async for d in client.iter_dialogs():
        e = d.entity
        if isinstance(e, Channel):
            if not e.megagroup or getattr(e, "gigagroup", False) or not _can_write(e):
                continue
            kind, access_hash = "channel", e.access_hash
        elif isinstance(e, Chat):
            if e.deactivated or getattr(e, "migrated_to", None) or not _can_write(e):
                continue
            kind, access_hash = "chat", 0
        else:
            continue
        found[e.id] = {"id": e.id, "title": e.title, "kind": kind, "access_hash": access_hash,
                       "members": getattr(e, "participants_count", None)}
    scans[acc["id"]] = found
    return [{"id": c["id"], "title": c["title"], "members": c["members"]} for c in found.values()]
