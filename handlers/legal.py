"""Документы для покупателей: политика конфиденциальности и пользовательское соглашение.

Тексты задаёт админ (админ-панель → 📄 Документы) и может менять в любой момент. Покупатель открывает их
кнопкой «Документы» в главном меню, командами /privacy и /terms или кнопками при оплате.
"""
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from texts import DIVIDER, t
from ui import btn, doc_text, kb, legal_row, menu_row, pager, render
from handlers.user import show_main

router = Router()

TITLES = {"privacy": "🔒 Политика конфиденциальности", "terms": "📜 Пользовательское соглашение"}
CHUNK = 3300  # символов на страницу: с запасом до лимита Telegram в 4096

_TAG = re.compile(r"<(/?)([a-zA-Z-]+)[^>]*>")
_PAIRED = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "blockquote",
           "tg-spoiler", "tg-emoji"}


def split_html(text, limit=CHUNK):
    """Режет HTML-текст Telegram на страницы по строкам; незакрытые теги закрываются в конце страницы
    и открываются заново в начале следующей, чтобы разметка не ломалась."""
    if len(text) <= limit:
        return [text]
    pieces = []
    for line in text.split("\n"):
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(line[:cut])
            line = line[cut:].lstrip(" ")
        pieces.append(line)
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > limit:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n{piece}" if cur else piece
    chunks.append(cur)

    out, stack = [], []
    for ch in chunks:
        prefix = "".join(tag for _, tag in stack)
        for m in _TAG.finditer(ch):
            closing, name = m.group(1), m.group(2).lower()
            if name not in _PAIRED:
                continue
            if closing:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        del stack[i]
                        break
            else:
                stack.append((name, m.group(0)))
        suffix = "".join(f"</{n}>" for n, _ in reversed(stack))
        out.append(prefix + ch + suffix)
    return out


async def show_doc(target, name, page, lang):
    text = doc_text(name)
    if not text:
        return False
    chunks = split_html(text)
    page = min(max(page, 0), len(chunks) - 1)
    body = f"<b>{TITLES[name]}</b>\n{DIVIDER}\n{chunks[page]}"
    seller = db.get_setting("seller_info")
    if seller and page == len(chunks) - 1:
        body += f"\n\n{DIVIDER}\n{seller}"
    other = "terms" if name == "privacy" else "privacy"
    rows = [pager(f"legal:{name}:", page, len(chunks))]
    if doc_text(other):
        rows.append([btn("legal_terms" if other == "terms" else "legal_privacy", lang, f"legal:{other}:0")])
    rows.append([btn("back", lang, "docs"), btn("main_menu", lang, "menu")])
    await render(target, body, kb(rows))
    return True


async def show_docs(target, lang):
    rows = [legal_row(lang)]
    rows.append(menu_row(lang))
    text = t("docs_title", lang)
    seller = db.get_setting("seller_info")
    if seller:
        text += f"\n\n{seller}"
    await render(target, text, kb(rows))


@router.callback_query(F.data == "docs")
async def cb_docs(call: CallbackQuery, state: FSMContext, lang: str):
    await state.clear()
    await show_docs(call, lang)
    await call.answer()


@router.callback_query(F.data.startswith("legal:"))
async def cb_legal(call: CallbackQuery, lang: str):
    _, name, page = call.data.split(":")
    if name not in TITLES or not await show_doc(call, name, int(page), lang):
        return await call.answer(t("doc_empty", lang), show_alert=True)
    await call.answer()


@router.message(Command("privacy"))
async def cmd_privacy(m: Message, lang: str):
    if not await show_doc(m, "privacy", 0, lang):
        await m.answer(t("doc_empty", lang))


@router.message(Command("terms"))
async def cmd_terms(m: Message, lang: str):
    if not await show_doc(m, "terms", 0, lang):
        await m.answer(t("doc_empty", lang))


@router.callback_query(F.data == "agree")
async def cb_agree(call: CallbackQuery, state: FSMContext, lang: str):
    db.update_user(call.from_user.id, agreed=1)
    await call.answer("✅")
    await show_main(call, lang, call.from_user.id, state)
