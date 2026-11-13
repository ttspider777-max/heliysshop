"""Планировщик рассылок."""
import asyncio
import logging
import re
import time

from telethon.errors import (
    ChannelPrivateError, ChatAdminRequiredError, ChatRestrictedError, ChatWriteForbiddenError,
    FloodWaitError, InviteRequestSentError, SlowModeWaitError, UserAlreadyParticipantError,
    UserBannedInChannelError,
)
from telethon.tl import types
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputPeerChannel, InputPeerChat

import accounts
import config
import db
import post
from loader import bot

log = logging.getLogger(__name__)

# Чат запретил писать — убираем его из рассылки, а не пробуем снова
FORBIDDEN = (ChatWriteForbiddenError, UserBannedInChannelError, ChannelPrivateError,
             ChatAdminRequiredError, ChatRestrictedError)

_running: set[int] = set()


def _peer(chat):
    if chat["kind"] == "channel":
        return InputPeerChannel(chat["chat_id"], chat["access_hash"])
    return InputPeerChat(chat["chat_id"])


async def _still_active(mailing_id) -> bool:
    row = await db.one("SELECT status FROM mailings WHERE id=?", mailing_id)
    return bool(row) and row["status"] == "active"


# ---------- автоподписка ----------

SUB_WORDS = ("подпис", "subscri", "вступ", "join")
LINK_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([\w\-+]+)", re.I)


def _targets(msg) -> list[str]:
    """Каналы из требования бота: ссылки в тексте, кнопки-ссылки, @упоминания."""
    found = []
    for ent, txt in msg.get_entities_text():
        if isinstance(ent, types.MessageEntityTextUrl):
            found.append(ent.url)
        elif isinstance(ent, (types.MessageEntityUrl, types.MessageEntityMention)):
            found.append(txt)
    for row in msg.buttons or []:
        for b in row:
            if getattr(b, "url", None):
                found.append(b.url)
    out = []
    for raw in found:
        raw = raw.strip()
        if raw.startswith("@"):
            key = raw[1:]
        else:
            m = LINK_RE.search(raw)
            if not m:
                continue
            key = ("+" + m.group(1)) if ("/+" in raw or "joinchat/" in raw) else m.group(1)
        # ботов и служебные ссылки пропускаем
        if not key or key.lower().endswith("bot") or key.lower() in ("share", "addstickers", "addemoji", "proxy"):
            continue
        if key not in out:
            out.append(key)
    return out[:config.AUTOJOIN_PER_MSG]


async def _join(client, key) -> bool:
    if key.startswith("+"):
        try:
            await client(ImportChatInviteRequest(key[1:]))
        except (UserAlreadyParticipantError, InviteRequestSentError):
            pass
        return True
    entity = await client.get_entity(key)
    if not isinstance(entity, types.Channel):
        return False   # пользователь или бот — не канал
    if not getattr(entity, "left", True):
        return False   # уже подписан
    await client(JoinChannelRequest(entity))
    return True


async def autojoin(client, acc, m, peer, chat, sent_msg) -> int:
    """Если бот-охранник чата в ответ на наше сообщение просит подписаться — вступаем в эти каналы."""
    day_ago = int(time.time()) - 86400
    used = (await db.one("SELECT COUNT(*) c FROM joins WHERE account_id=? AND created_at>?", acc["id"], day_ago))["c"]
    if used >= config.AUTOJOIN_PER_DAY:
        return 0
    try:
        msgs = await client.get_messages(peer, min_id=sent_msg.id, limit=10)
    except Exception:
        return 0
    joined = 0
    for msg in msgs:
        text = (msg.message or "").lower()
        if not any(w in text for w in SUB_WORDS):
            continue
        sender = await msg.get_sender()
        if not getattr(sender, "bot", False):
            continue
        if not (msg.mentioned or msg.reply_to_msg_id == sent_msg.id):
            continue
        for key in _targets(msg):
            if used + joined >= config.AUTOJOIN_PER_DAY:
                return joined
            try:
                if await _join(client, key):
                    joined += 1
                    await db.run("INSERT INTO joins(account_id, target, chat_id, created_at) VALUES(?,?,?,?)",
                                 acc["id"], key, chat["chat_id"], int(time.time()))
                    log.info("mailing %s: автоподписка на %s (чат %s)", m["id"], key, chat["chat_id"])
            except FloodWaitError:
                return joined   # Telegram просит притормозить — до следующего круга не вступаем
            except Exception as e:
                log.info("mailing %s: не удалось вступить в %s: %s", m["id"], key, e)
            await asyncio.sleep(2)
    return joined


# ---------- круг рассылки ----------

async def run_round(m):
    acc = await db.one("SELECT * FROM accounts WHERE id=?", m["account_id"])
    user = await db.get_user(m["user_id"])
    if not acc or not user or user["banned"]:
        await db.run("UPDATE mailings SET status='stopped' WHERE id=?", m["id"])
        return
    try:
        client = await accounts.get_client(acc)
    except accounts.AccountDead:
        return

    chats = await db.all("SELECT * FROM mailing_chats WHERE mailing_id=? AND active=1", m["id"])
    if not chats:
        await db.run("UPDATE mailings SET status='stopped' WHERE id=?", m["id"])
        return

    bot_username = (await bot.me()).username
    uploaded = None
    photo = post.media_path(m.get("media"))
    if photo:   # фото загружаем один раз за круг и шлём его во все чаты
        uploaded = await client.upload_file(str(photo))

    sent = failed = joined = 0
    delay_until = 0
    for chat in chats:
        if not await _still_active(m["id"]):
            break
        peer = _peer(chat)
        msg = None
        try:
            msg = await post.send(client, peer, m, bot_username, uploaded)
            sent += 1
        except FloodWaitError as e:
            # Telegram попросил подождать — ждём, длинное ожидание переносит весь круг
            if e.seconds > config.MAX_FLOOD_WAIT:
                delay_until = int(time.time()) + e.seconds + 5
                break
            await asyncio.sleep(e.seconds + 1)
            failed += 1
        except SlowModeWaitError:
            failed += 1   # в чате медленный режим — пропускаем до следующего круга
        except FORBIDDEN as e:
            failed += 1
            await db.run("UPDATE mailing_chats SET active=0, error=? WHERE mailing_id=? AND chat_id=?",
                         type(e).__name__, m["id"], chat["chat_id"])
        except accounts.DEAD_ERRORS:
            await accounts.mark_dead(acc)
            break
        except Exception:
            failed += 1
            log.exception("mailing %s -> chat %s", m["id"], chat["chat_id"])
        await asyncio.sleep(config.SEND_DELAY)
        if msg is not None and m.get("autojoin"):
            joined += await autojoin(client, acc, m, peer, chat, msg)

    # пауза считается от конца круга: «5 минут» — это 5 минут отдыха перед следующим кругом
    now = int(time.time())
    next_run = max(now + m["interval_min"] * 60, delay_until)
    await db.run("UPDATE mailings SET sent=sent+?, failed=failed+?, rounds=rounds+1, joined=joined+?, "
                 "last_run=?, next_run=? WHERE id=?", sent, failed, joined, now, next_run, m["id"])
    await db.run("UPDATE users SET total_sent = total_sent + ? WHERE id=?", sent, m["user_id"])
    await db.add_stats(m["user_id"], sent=sent, failed=failed, rounds=1, joined=joined)


async def _guarded(m):
    try:
        await run_round(m)
    except Exception:
        log.exception("mailing %s", m["id"])
        await db.run("UPDATE mailings SET next_run=? WHERE id=?", int(time.time()) + m["interval_min"] * 60, m["id"])
    finally:
        _running.discard(m["id"])


async def scheduler():
    while True:
        try:
            due = await db.all("SELECT * FROM mailings WHERE status='active' AND next_run <= ?", int(time.time()))
            for m in due:
                if m["id"] not in _running:
                    _running.add(m["id"])
                    asyncio.create_task(_guarded(m))
        except Exception:
            log.exception("scheduler")
        await asyncio.sleep(15)
