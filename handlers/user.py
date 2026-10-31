import html
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

import admins
import appcfg
import config
import db
import subscription
from services import safe_send, to_admins, user_link
from texts import bar, fdate, money, status, t
from ui import as_media, btn, kb, main_kb, menu_row, pager, render, shop_btn

router = Router()


class UserSt(StatesGroup):
    promo = State()


async def show_main(target, lang, uid, state: FSMContext = None):
    if state:
        await state.clear()
    u = db.get_user(uid)
    text = t("welcome", lang, name=html.escape((u["first_name"] if u else None) or "friend"),
             balance=money(u["balance"] if u else 0), orders=db.count_user_orders(uid),
             status=html.escape(appcfg.status_label(u)))
    media = as_media(db.get_setting("welcome_photo"), db.get_setting("welcome_media_type"))
    await render(target, text, main_kb(lang, admins.is_admin(uid)), photo=media)


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, state: FSMContext, lang: str, is_new: bool, bot: Bot):
    arg = command.args or ""
    if is_new and arg.startswith("ref_") and arg[4:].isdigit():
        rid = int(arg[4:])
        ref = db.get_user(rid)
        if rid != m.from_user.id and ref:
            db.update_user(m.from_user.id, referrer_id=rid)
            await safe_send(bot, rid, t("ref_new", ref["lang"]))
    if arg.startswith("p_") and arg[2:].isdigit():  # ссылка на товар из рассылки о пополнении
        from handlers.shop import show_product
        await state.clear()
        if await show_product(m, int(arg[2:]), "new", lang):
            return
    if arg == "topup":  # из мини-приложения: «пополнить баланс»
        from handlers.topup import topup_view
        await state.clear()
        return await topup_view(m, lang, m.from_user.id)
    if arg == "support":  # из мини-приложения: «написать в поддержку»
        from handlers.support import support_view
        await state.clear()
        return await support_view(m, state, lang, m.from_user.id)
    await show_main(m, lang, m.from_user.id, state)


@router.callback_query(F.data == "subcheck")
async def cb_subcheck(call: CallbackQuery, state: FSMContext, lang: str, bot: Bot):
    subscription.forget(call.from_user.id)
    if not admins.is_admin(call.from_user.id) and await subscription.missing(bot, call.from_user.id):
        return await call.answer(t("sub_not_yet", lang), show_alert=True)
    await call.answer(t("sub_thanks", lang))
    await show_main(call, lang, call.from_user.id, state)


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext, lang: str):
    await show_main(call, lang, call.from_user.id, state)
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()


# ---------- язык ----------
@router.callback_query(F.data == "lang")
async def cb_lang(call: CallbackQuery, lang: str):
    await render(call, t("lang_choose", lang), kb([
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang:ru"),
         InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang:en")],
        menu_row(lang),
    ]))
    await call.answer()


@router.callback_query(F.data.startswith("setlang:"))
async def cb_setlang(call: CallbackQuery, state: FSMContext):
    lang = "en" if call.data.endswith("en") else "ru"
    db.update_user(call.from_user.id, lang=lang)
    await call.answer("✅ English" if lang == "en" else "✅ Русский")
    await show_main(call, lang, call.from_user.id, state)


# ---------- профиль ----------
def profile_text(u, lang):
    cur, nxt, pct, left = appcfg.user_status(u)
    if nxt:
        progress = t("profile_next", lang, bar=bar(pct), pct=pct, next=html.escape(nxt["name"]), left=money(left))
    else:
        progress = t("profile_max", lang)
    uname = f"@{html.escape(u['username'])}" if u["username"] else html.escape(u["first_name"] or "—")
    text = t("profile", lang, id=u["id"], username=uname, name=html.escape(u["first_name"] or ""),
             date=fdate(u["joined"]), orders=db.count_user_orders(u["id"]), balance=money(u["balance"]),
             status=html.escape(appcfg.status_label(u)), progress=progress, deposited=money(u["deposited"]))
    if u["promo_percent"]:
        text += t("profile_promo", lang, code=html.escape(u["promo_code"]), pct=u["promo_percent"])
    return text


def profile_kb(u, lang):
    bonus = []
    if appcfg.bonus_on():
        left = appcfg.bonus_left(u)
        label = None if not left else f"⏳ {appcfg.fmt_left(left, lang)}"
        b = btn("bonus", lang, "bonus")
        if b and label:
            b.text = f"{b.text} · {label}"
        bonus = [b]
    return kb([
        [btn("topup", lang, "topup")],
        bonus,
        [btn("my_orders", lang, "ord:p:0"), btn("fav", lang, "l:pfav:0")],
        [btn("statuses", lang, "stl"), shop_btn(lang, "#profile")],
        [btn("back", lang, "menu")],
    ])


async def show_profile(target, lang, uid, note=None):
    u = db.get_user(uid)
    await render(target, (note + "\n\n" if note else "") + profile_text(u, lang), profile_kb(u, lang))


@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery, state: FSMContext, lang: str):
    await state.clear()
    await show_profile(call, lang, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "bonus")
async def cb_bonus(call: CallbackQuery, lang: str):
    if not appcfg.bonus_on():
        return await call.answer(t("bonus_off", lang), show_alert=True)
    got = appcfg.claim_bonus(call.from_user.id)
    if got is None:
        left = appcfg.bonus_left(db.get_user(call.from_user.id))
        return await call.answer(t("bonus_wait", lang, left=appcfg.fmt_left(left, lang)), show_alert=True)
    await call.answer(t("bonus_ok", lang, amount=money(got)), show_alert=True)
    await show_profile(call, lang, call.from_user.id)


@router.callback_query(F.data == "stl")
async def cb_statuses(call: CallbackQuery, lang: str):
    u = db.get_user(call.from_user.id)
    cur = appcfg.user_status(u)[0]
    lines = []
    for s in appcfg.statuses():
        mark = "👉 " if s["name"] == cur["name"] else "▫️ "
        name = f"{s.get('emoji') or ''} {html.escape(s['name'])}".strip()
        lines.append(f"{mark}<b>{name}</b> — от {money(s['min'])}" if lang != "en"
                     else f"{mark}<b>{name}</b> — from {money(s['min'])}")
    await render(call, t("statuses", lang, list="\n".join(lines)), kb([[btn("back", lang, "profile")]]))
    await call.answer()


# ---------- заказы ----------
PER_PAGE = 8


@router.callback_query(F.data.startswith("ord:"))
async def cb_orders(call: CallbackQuery, state: FSMContext, lang: str):
    await state.clear()
    _, src, page = call.data.split(":")
    page = int(page)
    orders = db.user_orders(call.from_user.id)
    pages = max(1, (len(orders) + PER_PAGE - 1) // PER_PAGE)
    page = min(max(page, 0), pages - 1)
    text = t("orders_title", lang, n=len(orders))
    if not orders:
        text += t("orders_empty", lang)
    rows = []
    for o in orders[page * PER_PAGE:(page + 1) * PER_PAGE]:
        icon = status(o["status"], lang).split(" ")[0]
        rows.append([InlineKeyboardButton(text=f"{icon} #{o['id']} {o['product_name']} — {money(o['price'])}",
                                          callback_data=f"o:{o['id']}:{src}")])
    rows.append(pager(f"ord:{src}:", page, pages))
    rows.append([btn("back", lang, "profile" if src == "p" else "menu")])
    await render(call, text, kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("o:"))
async def cb_order(call: CallbackQuery, lang: str):
    _, oid, src = call.data.split(":")
    o = db.order(int(oid))
    if not o or o["user_id"] != call.from_user.id:
        return await call.answer(t("order_bad", lang), show_alert=True)
    text = t("order_detail", lang, oid=o["id"], name=html.escape(o["product_name"]), price=money(o["price"]),
             method=t("m_balance" if o["method"] == "balance" else "m_sbp", lang),
             date=fdate(o["created"]) + " " + o["created"][11:16], status=status(o["status"], lang))
    if o["content"]:
        text += t("order_content", lang, content=html.escape(o["content"]))
    await render(call, text, kb([[btn("back", lang, f"ord:{src}:0")], menu_row(lang)]))
    await call.answer()


# ---------- рефералы ----------
async def refs_view(call: CallbackQuery, lang: str, bot: Bot):
    u = db.get_user(call.from_user.id)
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{u['id']}"
    text = t("refs", lang, link=link, invited=db.count_refs(u["id"]), bought=db.count_refs_bought(u["id"]),
             earned=money(u["ref_earned"]), available=money(u["ref_balance"]),
             pct=db.get_setting("ref_percent", config.REF_PERCENT),
             min=money(db.get_setting("min_withdraw", config.MIN_WITHDRAW)))
    share = f"https://t.me/share/url?url={quote(link)}&text={quote(t('invite_text', lang))}"
    await render(call, text, kb([
        [btn("invite", lang, url=share)],
        [btn("withdraw", lang, "wd"), btn("refresh", lang, "refs_upd")],
        [btn("back", lang, "menu")],
    ]))


@router.callback_query(F.data == "refs")
async def cb_refs(call: CallbackQuery, lang: str, bot: Bot):
    await refs_view(call, lang, bot)
    await call.answer()


@router.callback_query(F.data == "refs_upd")
async def cb_refs_upd(call: CallbackQuery, lang: str, bot: Bot):
    await refs_view(call, lang, bot)
    await call.answer(t("refreshed", lang))


@router.callback_query(F.data == "wd")
async def cb_withdraw(call: CallbackQuery, lang: str, bot: Bot):
    u = db.get_user(call.from_user.id)
    amount = round(u["ref_balance"], 2)
    mn = float(db.get_setting("min_withdraw", config.MIN_WITHDRAW))
    if amount < mn:
        return await call.answer(t("wd_min", lang, min=money(mn)), show_alert=True)
    db.update_user(u["id"], ref_balance=0)
    wid = db.create_withdrawal(u["id"], amount)
    await to_admins(bot, f"💸 <b>Заявка на вывод #{wid}</b>\n\n👤 {user_link(u)}\n💰 Сумма: <b>{money(amount)}</b>\n"
                         f"👥 Рефералов: {db.count_refs(u['id'])}, купили: {db.count_refs_bought(u['id'])}",
                    kb([[InlineKeyboardButton(text="✅ Одобрить", callback_data=f"a:wok:{wid}", style="success"),
                         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"a:wno:{wid}", style="danger")]]))
    await call.answer(t("wd_sent", lang, amount=money(amount)), show_alert=True)
    await refs_view(call, lang, bot)


# ---------- промокод ----------
@router.callback_query(F.data == "promo")
async def cb_promo(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(UserSt.promo)
    await render(call, t("promo_prompt", lang), kb([[btn("cancel", lang, "menu")]]))
    await call.answer()


@router.message(UserSt.promo, F.text)
async def msg_promo(m: Message, state: FSMContext, lang: str):
    code = m.text.strip()
    p = db.promo(code)
    back = kb([menu_row(lang)])
    if not p or p["used"] >= p["max_uses"]:
        return await m.answer(t("promo_bad", lang), reply_markup=kb([[btn("cancel", lang, "menu")]]))
    if db.promo_used_by(p["code"], m.from_user.id):
        await state.clear()
        return await m.answer(t("promo_used", lang), reply_markup=back)
    db.use_promo(p["code"], m.from_user.id)
    db.update_user(m.from_user.id, promo_code=p["code"], promo_percent=p["percent"])
    await state.clear()
    await m.answer(t("promo_ok", lang, code=html.escape(p["code"]), pct=p["percent"]),
                   reply_markup=kb([[shop_btn(lang)], menu_row(lang)]))
