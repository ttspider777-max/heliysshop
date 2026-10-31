"""«💬 Поддержка» прямо в боте.

Покупатель: 💬 Поддержка → описывает проблему (текст, фото, видео, файл, голосовое) → обращение уходит админам.
Админ получает карточку: кто пишет (имя, @username, ID, язык, баланс, заказы, статус) и сообщение, с кнопками
✍️ Ответить / ✅ Закрыть / 🚫 Отклонить / 👤 Профиль / 📜 История. Ответ админа приходит покупателю от имени бота,
покупатель может ответить снова — переписка идёт в одном обращении, пока его не закроют.
Админ-панель → 💬 Поддержка: открытые обращения и история.
"""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import admins
import appcfg
import db
from handlers.admin import A, B, back, done, inp, mark_admin_msg, router as admin_router, user_card
from services import safe_send, user_link
from texts import fdate, money, t
from ui import btn, kb, menu_row, render

router = Router()


class SupSt(StatesGroup):
    text = State()


KIND_LABEL = {"photo": "🖼 фото", "video": "🎬 видео", "document": "📎 файл", "voice": "🎤 голосовое",
              "animation": "🎞 GIF", "video_note": "⭕ кружок", "sticker": "🙂 стикер", "audio": "🎵 аудио"}


def _content(m: Message):
    """-> (текст в HTML, file_id, тип) из сообщения."""
    for kind in ("photo", "video", "document", "voice", "animation", "video_note", "sticker", "audio"):
        obj = getattr(m, kind, None)
        if obj:
            fid = obj[-1].file_id if kind == "photo" else obj.file_id
            return (m.html_text if (m.caption or m.text) else ""), fid, kind
    return (m.html_text if m.text else ""), None, None


def _status_text(tk, lang):
    return t("sup_status_answered" if tk["status"] == "answered" else "sup_status_open", lang)


# ======================= покупатель =======================
async def support_view(target, state: FSMContext, lang, uid):
    tk = db.user_active_ticket(uid)
    if tk:
        await state.set_state(None)
        return await render(target, t("sup_active", lang, tid=tk["id"], status=_status_text(tk, lang),
                                      date=fdate(tk["created"])), kb([
            [btn("sup_write", lang, f"sup:r:{tk['id']}")],
            [btn("sup_close", lang, f"sup:c:{tk['id']}")],
            menu_row(lang),
        ]))
    await state.set_state(SupSt.text)
    await state.update_data(sup_tid=None)
    await render(target, t("sup_prompt", lang), kb([[btn("cancel", lang, "menu")]]))


@router.callback_query(F.data == "sup")
async def cb_support(call: CallbackQuery, state: FSMContext, lang: str):
    await support_view(call, state, lang, call.from_user.id)
    await call.answer()


@router.callback_query(F.data.startswith("sup:r:"))
async def cb_support_more(call: CallbackQuery, state: FSMContext, lang: str):
    tid = int(call.data.split(":")[2])
    tk = db.ticket(tid)
    if not tk or tk["user_id"] != call.from_user.id or tk["status"] not in ("open", "answered"):
        await call.answer()
        return await support_view(call, state, lang, call.from_user.id)
    await state.set_state(SupSt.text)
    await state.update_data(sup_tid=tid)
    await call.message.answer(t("sup_more_prompt", lang), reply_markup=kb([[btn("cancel", lang, "menu")]]))
    await call.answer()


@router.callback_query(F.data.startswith("sup:c:"))
async def cb_support_close(call: CallbackQuery, state: FSMContext, lang: str, bot: Bot):
    tid = int(call.data.split(":")[2])
    tk = db.ticket(tid)
    await state.set_state(None)
    if tk and tk["user_id"] == call.from_user.id and tk["status"] in ("open", "answered"):
        db.set_ticket(tid, status="closed", closed_by=call.from_user.id)
        u = db.get_user(call.from_user.id)
        for aid in admins.ids():
            await safe_send(bot, aid, f"✅ Обращение #{tid} закрыл сам пользователь {user_link(u)}")
    await render(call, t("sup_closed", lang, tid=tid), kb([menu_row(lang)]))
    await call.answer()


@router.message(SupSt.text)
async def msg_support(m: Message, state: FSMContext, lang: str, bot: Bot):
    text, fid, kind = _content(m)
    if not text and not fid:
        return await m.answer(t("sup_prompt", lang))
    uid = m.from_user.id
    tid = (await state.get_data()).get("sup_tid")
    tk = db.ticket(tid) if tid else None
    if not tk or tk["user_id"] != uid or tk["status"] not in ("open", "answered"):
        tk = db.user_active_ticket(uid)
    is_new = tk is None
    tid = db.create_ticket(uid) if is_new else tk["id"]
    db.add_ticket_msg(tid, "user", text, fid, kind)
    db.set_ticket(tid, status="open")
    await state.set_state(None)
    await notify_admins(bot, m, tid, is_new, text, fid)
    await m.answer(t("sup_sent" if is_new else "sup_more_sent", lang, tid=tid), reply_markup=kb([
        [btn("sup_write", lang, f"sup:r:{tid}")],
        menu_row(lang),
    ]))


def admin_card(tid, is_new, text, kind=None):
    tk = db.ticket(tid)
    u = db.get_user(tk["user_id"])
    uname = f"@{html.escape(u['username'])}" if u and u["username"] else "нет"
    n_orders = db.count_user_orders(u["id"]) if u else 0
    head = "🆕 Новое обращение" if is_new else "💬 Новое сообщение в обращении"
    body = (f"{head} <b>#{tid}</b>\n\n"
            f"👤 {user_link(u)}\n"
            f"🆔 ID: <code>{tk['user_id']}</code>\n"
            f"🔗 Юзернейм: {uname}\n"
            + (f"🌐 Язык: {u['lang']} · 📅 В боте с {fdate(u['joined'])}\n"
               f"💰 Баланс: {money(u['balance'])} · 🏅 {html.escape(appcfg.status_label(u))}\n"
               f"🛒 Заказов: {n_orders} на {money(db.user_spent(u['id']))}\n" if u else ""))
    if text:
        body += f"\n📝 <b>Сообщение:</b>\n<blockquote>{text[:3000]}</blockquote>"
    if kind:
        body += f"\n📎 Вложение: {KIND_LABEL.get(kind, kind)} (ниже)"
    return body


def ticket_kb(tid, uid):
    return kb([
        [B("✍️ Ответить", f"a:tkr:{tid}", style="primary")],
        [B("✅ Закрыть", f"a:tkc:{tid}", style="success"), B("🚫 Отклонить", f"a:tkx:{tid}", style="danger")],
        [B("👤 Профиль", f"a:tku:{uid}"), B("📜 История", f"a:tkh:{tid}")],
    ])


async def notify_admins(bot: Bot, m: Message, tid, is_new, text, fid):
    _, _, kind = _content(m)
    card = admin_card(tid, is_new, text, kind if fid else None)
    markup = ticket_kb(tid, m.from_user.id)
    for aid in admins.ids():
        try:
            if fid:
                await bot.send_message(aid, card)
                await bot.copy_message(aid, m.chat.id, m.message_id, reply_markup=markup)
            else:
                await bot.send_message(aid, card, reply_markup=markup)
        except Exception as e:
            logging.info("обращение #%s не доставлено админу %s: %s", tid, aid, e)


# ======================= админ =======================
def _lang_of(uid):
    u = db.get_user(uid)
    return u["lang"] if u else "ru"


@admin_router.callback_query(F.data.startswith("a:tkr:"))
async def cb_ticket_reply(call: CallbackQuery, state: FSMContext):
    tid = int(call.data.split(":")[2])
    tk = db.ticket(tid)
    if not tk:
        return await call.answer("Обращение не найдено", show_alert=True)
    if tk["status"] in ("closed", "rejected"):
        return await call.answer("Обращение уже закрыто. Можно написать пользователю из его профиля.", show_alert=True)
    await state.set_state(A.inp)
    await state.set_data({"act": "tkr", "tid": tid})
    u = db.get_user(tk["user_id"])
    await call.message.answer(f"✍️ <b>Ответ на обращение #{tid}</b> для {user_link(u)}\n\n"
                              "Отправьте ответ — текст, фото, видео, файл или голосовое. "
                              "Форматирование и премиум-эмодзи сохранятся.",
                              reply_markup=kb([[B("❌ Отмена", "a:tkcancel", style="danger")]]))
    await call.answer()


@admin_router.callback_query(F.data == "a:tkcancel")
async def cb_ticket_reply_cancel(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer("Ответ отменён")


@inp("tkr")
async def i_ticket_reply(m, state, d, txt, bot):
    tid = d["tid"]
    tk = db.ticket(tid)
    if not tk or tk["status"] in ("closed", "rejected"):
        return await done(m, state, "Обращение уже закрыто.")
    uid = tk["user_id"]
    lang = _lang_of(uid)
    markup = kb([[btn("sup_reply", lang, f"sup:r:{tid}")], [btn("sup_close", lang, f"sup:c:{tid}")]])
    try:
        await bot.send_message(uid, t("sup_reply", lang, tid=tid))
        await bot.copy_message(uid, m.chat.id, m.message_id, reply_markup=markup)
    except Exception as e:
        return await done(m, state, f"❌ Не удалось доставить ответ (пользователь заблокировал бота?): "
                                    f"{html.escape(str(e))}")
    text, fid, kind = _content(m)
    db.add_ticket_msg(tid, "admin", text, fid, kind, admin_id=m.from_user.id)
    db.set_ticket(tid, status="answered")
    who = html.escape(m.from_user.first_name or "админ")
    for aid in admins.ids():  # остальные админы видят, что на обращение уже ответили
        if aid != m.from_user.id:
            await safe_send(bot, aid, f"💬 {who} ответил на обращение #{tid}")
    await done(m, state, f"✅ Ответ на обращение #{tid} отправлен.", kb([
        [B("📜 История", f"a:tkh:{tid}"), B("✅ Закрыть", f"a:tkc:{tid}", style="success")],
        [B("💬 Все обращения", "a:tk:open")],
    ]))


@admin_router.callback_query(F.data.startswith("a:tkc:") | F.data.startswith("a:tkx:"))
async def cb_ticket_close(call: CallbackQuery, bot: Bot):
    _, op, tid = call.data.split(":")
    tid = int(tid)
    tk = db.ticket(tid)
    if not tk:
        return await call.answer("Обращение не найдено", show_alert=True)
    if tk["status"] in ("closed", "rejected"):
        await mark_admin_msg(call, "ℹ️ Уже закрыто")
        return await call.answer("Обращение уже закрыто", show_alert=True)
    reject = op == "tkx"
    db.set_ticket(tid, status="rejected" if reject else "closed", closed_by=call.from_user.id)
    lang = _lang_of(tk["user_id"])
    await safe_send(bot, tk["user_id"], t("sup_rejected" if reject else "sup_closed", lang, tid=tid),
                    kb([[btn("support", lang, "sup")], menu_row(lang)]))
    who = html.escape(call.from_user.first_name or "админ")
    await mark_admin_msg(call, f"{'🚫 Отклонено' if reject else '✅ Закрыто'} ({who})")
    await call.answer("Отклонено" if reject else "Закрыто")


@admin_router.callback_query(F.data.startswith("a:tku:"))
async def cb_ticket_user(call: CallbackQuery):
    text, markup = user_card(int(call.data.split(":")[2]))
    if not text:
        return await call.answer("Пользователь не найден", show_alert=True)
    await call.message.answer(text, reply_markup=markup)
    await call.answer()


TK_STATUS = {"open": "⏳ ждёт ответа", "answered": "💬 отвечено", "closed": "✅ закрыто", "rejected": "🚫 отклонено"}


def history_text(tid):
    tk = db.ticket(tid)
    u = db.get_user(tk["user_id"])
    lines = [f"📜 <b>Обращение #{tid}</b> · {TK_STATUS.get(tk['status'], tk['status'])}",
             f"👤 {user_link(u)}", f"📅 {tk['created']}", ""]
    for msg in db.ticket_msgs(tid):
        who = "👤 Пользователь" if msg["sender"] == "user" else "🛡 Поддержка"
        att = f" [{KIND_LABEL.get(msg['kind'], 'вложение')}]" if msg["file_id"] else ""
        lines.append(f"<b>{who}</b> · {msg['created'][11:16]} {fdate(msg['created'])}{att}")
        if msg["text"]:
            lines.append(f"<blockquote>{msg['text'][:700]}</blockquote>")
    text = "\n".join(lines)
    return text if len(text) <= 4000 else text[:3990] + "…"


@admin_router.callback_query(F.data.startswith("a:tkh:") | F.data.startswith("a:tkv:"))
async def cb_ticket_history(call: CallbackQuery):
    tid = int(call.data.split(":")[2])
    tk = db.ticket(tid)
    if not tk:
        return await call.answer("Обращение не найдено", show_alert=True)
    rows = []
    if tk["status"] in ("open", "answered"):
        rows = ticket_kb(tid, tk["user_id"]).inline_keyboard
    rows = [list(r) for r in rows] + [back("a:tk:open", "◀️ К обращениям")]
    text = history_text(tid)
    if call.data.startswith("a:tkh:"):  # из карточки в личке — не затираем её, а шлём историю отдельно
        await call.message.answer(text, reply_markup=kb(rows))
    else:
        await render(call, text, kb(rows))
    await call.answer()


@admin_router.callback_query(F.data.startswith("a:tk:"))
async def cb_tickets(call: CallbackQuery):
    mode = call.data.split(":")[2]
    statuses = ("open", "answered") if mode == "open" else ("closed", "rejected")
    items = db.tickets_list(statuses, 40)
    rows = []
    for tk in items:
        u = db.get_user(tk["user_id"])
        name = (f"@{u['username']}" if u and u["username"] else (u["first_name"] if u else None)) or str(tk["user_id"])
        icon = TK_STATUS.get(tk["status"], "•").split(" ")[0]
        rows.append([B(f"{icon} #{tk['id']} · {name} · {tk['updated'][5:16]}", f"a:tkv:{tk['id']}")])
    rows.append([B("🗂 Закрытые" if mode == "open" else "📬 Открытые", "a:tk:done" if mode == "open" else "a:tk:open")])
    rows.append(back())
    n_open = db.val("SELECT COUNT(*) FROM tickets WHERE status='open'")
    title = "📬 Открытые обращения" if mode == "open" else "🗂 Закрытые обращения"
    text = (f"💬 <b>Поддержка</b> · {title}\n\n⏳ Ждут ответа: <b>{n_open}</b>\n\n"
            "⏳ ждёт ответа · 💬 вы ответили · ✅ закрыто · 🚫 отклонено")
    if not items:
        text += "\n\n<i>Обращений нет.</i>"
    await render(call, text, kb(rows))
    await call.answer()
