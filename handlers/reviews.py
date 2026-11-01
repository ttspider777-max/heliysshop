"""Отзывы на товары: после выдачи покупатель ставит ⭐1–5 и (по желанию) пишет пару слов. Отзывы видны в карточке
товара в боте и в мини-приложении. Админам приходит каждый отзыв с кнопкой «🙈 Скрыть».

Выключить просьбу об оценке: настройка reviews_off=1 (админ-панель → ⚙️ Настройки → ⭐ Отзывы на товары).
"""
import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admins
import db
from services import to_admins, user_link
from texts import t
from ui import btn, kb, raw_btn, render

router = Router()


class ReviewSt(StatesGroup):
    text = State()


PER_PAGE = 5


def stars(n):
    return "⭐" * int(n or 0)


@router.callback_query(F.data.startswith("rv:"))
async def cb_rate(call: CallbackQuery, state: FSMContext, lang: str):
    try:
        _, oid, n = call.data.split(":")
        oid, n = int(oid), int(n)
    except ValueError:
        return await call.answer()
    o = db.order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "done" or not 1 <= n <= 5:
        return await call.answer()
    rid = db.add_review(oid, o["user_id"], o["product_id"], n)
    if not rid:
        return await call.answer(t("rate_done", lang), show_alert=True)
    await state.set_state(ReviewSt.text)
    await state.update_data(review_id=rid)
    await render(call, t("rate_text", lang, stars=stars(n)), kb([[btn("rv_skip", lang, "rvs")]]))
    await call.answer("⭐" * n)
    await notify_admins(call.bot, db.review(rid))


@router.callback_query(F.data == "rvs")
async def cb_skip(call: CallbackQuery, state: FSMContext, lang: str):
    await state.clear()
    await render(call, t("rate_done", lang), kb([[btn("main_menu", lang, "menu")]]))
    await call.answer()


@router.message(ReviewSt.text, F.text)
async def msg_review(m: Message, state: FSMContext, lang: str):
    if m.text.startswith("/"):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    r = db.review(data.get("review_id") or 0)
    if not r or r["user_id"] != m.from_user.id:
        return
    db.set_review(r["id"], text=m.text.strip()[:500])
    await m.answer(t("rate_done", lang), reply_markup=kb([[btn("main_menu", lang, "menu")]]))
    await notify_admins(m.bot, db.review(r["id"]))


async def notify_admins(bot: Bot, r):
    p = db.product(r["product_id"])
    text = (f"⭐ <b>Отзыв</b> {stars(r['rating'])}\n📦 {html.escape(p['name'] if p else '—')}\n"
            f"👤 {user_link(db.get_user(r['user_id']))}" + (f"\n\n💬 {html.escape(r['text'])}" if r["text"] else ""))
    await to_admins(bot, text, kb([[raw_btn("🙈 Скрыть отзыв", f"rvh:{r['id']}", style="danger")]]))


@router.callback_query(F.data.startswith("rvh:"))
async def cb_hide(call: CallbackQuery):
    if not admins.is_admin(call.from_user.id):
        return await call.answer()
    rid = int(call.data[4:])
    r = db.review(rid)
    if r:
        db.set_review(rid, hidden=0 if r["hidden"] else 1)
    hidden = r and not r["hidden"]
    await call.answer("🙈 Отзыв скрыт" if hidden else "👁 Отзыв снова виден")
    try:
        await call.message.edit_reply_markup(reply_markup=kb([[raw_btn(
            "👁 Показать отзыв" if hidden else "🙈 Скрыть отзыв", f"rvh:{rid}", style=None if hidden else "danger")]]))
    except Exception:
        pass


@router.callback_query(F.data.startswith("rvl:"))
async def cb_list(call: CallbackQuery, lang: str):
    """rvl:<id товара>:<откуда>:<страница> — список отзывов о товаре."""
    try:
        _, pid, kind, page = call.data.split(":")
        pid, page = int(pid), max(int(page), 0)
    except ValueError:
        return await call.answer()
    p = db.product(pid)
    if not p:
        return await call.answer()
    avg, n = db.review_stats(pid)
    rows_db = db.reviews_for(pid, PER_PAGE, page * PER_PAGE)
    lines = [f"{stars(r['rating'])} <b>{html.escape(r['first_name'] or 'Покупатель')}</b> · {r['created'][8:10]}."
             f"{r['created'][5:7]}" + (f"\n{html.escape(r['text'])}" if r["text"] else "") for r in rows_db]
    text = t("reviews_title", lang, name=html.escape(p["name"])) + "\n" + \
        (t("rating_line", lang, avg=f"{avg:g}", n=n) + "\n\n" + "\n\n".join(lines) if n else "\n" + t("reviews_empty", lang))
    nav = []
    if page > 0:
        nav.append(raw_btn("◀️", f"rvl:{pid}:{kind}:{page - 1}"))
    if (page + 1) * PER_PAGE < n:
        nav.append(raw_btn("▶️", f"rvl:{pid}:{kind}:{page + 1}"))
    await render(call, text, kb([nav, [btn("back", lang, f"p:{pid}:{kind}")]]))
    await call.answer()

