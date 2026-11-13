"""Пост рассылки: текст, фото, форматирование и премиум-эмодзи."""
import json
import logging

from telethon.errors import BadRequestError
from telethon.tl import types

import config

log = logging.getLogger(__name__)

# Форматирование из сообщения боту (Bot API) -> сущности Telethon. Ссылки, @упоминания и #теги
# Telegram распознаёт в тексте сам, их переносить не нужно.
_SIMPLE = {
    "bold": types.MessageEntityBold, "italic": types.MessageEntityItalic,
    "underline": types.MessageEntityUnderline, "strikethrough": types.MessageEntityStrike,
    "spoiler": types.MessageEntitySpoiler, "code": types.MessageEntityCode,
    "blockquote": types.MessageEntityBlockquote, "expandable_blockquote": types.MessageEntityBlockquote,
}


def entities_from_message(entities) -> str | None:
    """aiogram MessageEntity[] -> JSON для хранения в базе."""
    out = []
    for e in entities or []:
        if e.type in _SIMPLE or e.type in ("pre", "text_link", "custom_emoji"):
            out.append({"type": e.type, "offset": e.offset, "length": e.length, "url": e.url,
                        "language": e.language, "custom_emoji_id": e.custom_emoji_id})
    return json.dumps(out) if out else None


def to_telethon(raw: str | None, with_emoji=True) -> list:
    ents = []
    for e in json.loads(raw) if raw else []:
        t, off, ln = e["type"], e["offset"], e["length"]
        if t in _SIMPLE:
            ents.append(_SIMPLE[t](off, ln))
        elif t == "pre":
            ents.append(types.MessageEntityPre(off, ln, e.get("language") or ""))
        elif t == "text_link" and e.get("url"):
            ents.append(types.MessageEntityTextUrl(off, ln, e["url"]))
        elif t == "custom_emoji" and with_emoji and e.get("custom_emoji_id"):
            ents.append(types.MessageEntityCustomEmoji(off, ln, int(e["custom_emoji_id"])))
    return ents


def has_custom_emoji(raw: str | None) -> bool:
    return bool(raw) and '"custom_emoji"' in raw


def signature(bot_username: str) -> str:
    return f"\n\nОтправлено через @{bot_username}"


def media_path(name: str | None):
    if not name:
        return None
    path = config.MEDIA_DIR / name
    return path if path.is_file() else None


async def send(client, peer, mailing, bot_username, uploaded=None):
    """Отправляет пост рассылки в чат. uploaded — фото, уже загруженное на серверы Telegram в этом круге."""
    text = (mailing["text"] or "") + signature(bot_username)
    raw = mailing.get("entities")
    try:
        return await client.send_message(peer, text, file=uploaded, formatting_entities=to_telethon(raw))
    except BadRequestError as e:
        # премиум-эмодзи может отправлять только аккаунт с Telegram Premium — шлём без них
        if not has_custom_emoji(raw) or not any(k in str(e).upper() for k in ("ENTIT", "EMOJI", "DOCUMENT", "PREMIUM")):
            raise
        log.info("mailing %s: без премиум-эмодзи (%s)", mailing["id"], e)
        return await client.send_message(peer, text, file=uploaded, formatting_entities=to_telethon(raw, False))
