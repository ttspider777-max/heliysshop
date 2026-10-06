import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from services import final_price, fulfill, user_link
from texts import DIVIDER, money, plural, t
from ui import btn, kb, legal_row, menu_row, pager, raw_btn, render

router = Router()
PER_PAGE = 8

LIST_TITLES = {"hits": "list_hits", "disc": "list_disc", "new": "list_new", "recent": "list_recent",
               "fav": "list_fav", "pfav": "list_fav", "srch": "list_srch"}


MAX_QTY = 100  # верхний предел количества за один заказ


class ShopSt(StatesGroup):
    search = State()
    receipt = State()
    qty = State()


# ---------- каталог ----------
@router.callback_query(F.data == "cat")
async def cb_catalog(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(None)
    lines = [t("catalog_title", lang), DIVIDER]
    rows, row = [], []
    sup = db.suppliers_cid()
    for c in db.categories():
        if c["id"] == sup:  # поставщики показываются отдельной кнопкой главного меню
            continue
        n = db.count_in_category(c["id"])
        lines.append(f"{html.escape(c['name'])}  ·  <b>{n}</b> {plural(n, lang)}")
        row.append(raw_btn(c["name"], f"l:c{c['id']}:0", icon=c["emoji_id"]))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    lines += [DIVIDER, t("catalog_body", lang)]
    rows += [
        [btn("hits", lang, "l:hits:0"), btn("disc", lang, "l:disc:0")],
        [btn("new", lang, "l:new:0"), btn("recent", lang, "l:recent:0")],
        [btn("search", lang, "search"), btn("fav", lang, "l:fav:0")],
        menu_row(lang),
    ]
    await render(call, "\n".join(lines), kb(rows))
    await call.answer()


def product_label(p):
    mark = ""
    if p["old_price"] and p["old_price"] > p["price"]:
        mark = "🏷 "
    if not db.unlimited(p) and db.stock(p["id"]) == 0:
        mark = "❌ "
    return f"{mark}{p['name']} — {money(p['price'])}"


def product_btn(p, cb):
    """Кнопка товара в списке; премиум-эмодзи товара ставится иконкой слева."""
    kw = {"icon_custom_emoji_id": p["emoji_id"]} if p["emoji_id"] else {}
    return InlineKeyboardButton(text=product_label(p), callback_data=cb, **kw)


def name_html(p):
    """Название товара для текста: с премиум-эмодзи, если оно задано."""
    icon = f'<tg-emoji emoji-id="{p["emoji_id"]}">⭐</tg-emoji> ' if p["emoji_id"] else ""
    return icon + html.escape(p["name"])


def is_multi(p):
    c = db.category(p["category_id"])
    return bool(c and c["multi"])


def max_qty(p):
    return MAX_QTY if db.unlimited(p) else min(db.stock(p["id"]), MAX_QTY)


async def show_list(target, kind, page, uid, lang, query=None):
    items = db.products_by(kind, uid, query)
    if kind.startswith("c"):
        cat = db.category(int(kind[1:]))
        title = t("list_cat", lang, name=html.escape(cat["name"]) if cat else "")
    else:
        title = t(LIST_TITLES[kind], lang, q=html.escape(query or ""))
    if not items:
        title += t("list_empty", lang)
    pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    page = min(max(page, 0), pages - 1)
    rows = [[product_btn(p, f"p:{p['id']}:{kind}")]
            for p in items[page * PER_PAGE:(page + 1) * PER_PAGE]]
    rows.append(pager(f"l:{kind}:", page, pages))
    back = "profile" if kind == "pfav" else "menu" if kind == f"c{db.suppliers_cid()}" else "cat"
    rows.append([btn("back", lang, back), btn("main_menu", lang, "menu")])
    await render(target, title, kb(rows))


@router.callback_query(F.data.startswith("l:"))
async def cb_list(call: CallbackQuery, state: FSMContext, lang: str):
    _, kind, page = call.data.split(":")
    query = (await state.get_data()).get("search_q") if kind == "srch" else None
    await state.set_state(None)
    await show_list(call, kind, int(page), call.from_user.id, lang, query)
    await call.answer()


# ---------- поиск ----------
@router.callback_query(F.data == "search")
async def cb_search(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(ShopSt.search)
    await render(call, t("search_prompt", lang), kb([[btn("back", lang, "cat"), btn("main_menu", lang, "menu")]]))
    await call.answer()


@router.message(ShopSt.search, F.text)
async def msg_search(m: Message, state: FSMContext, lang: str):
    q = m.text.strip()[:64]
    await state.set_state(None)
    await state.update_data(search_q=q)
    await show_list(m, "srch", 0, m.from_user.id, lang, q)


# ---------- карточка товара ----------
def product_text(p, lang, u):
    lines = [f"<b>{name_html(p)}</b>", DIVIDER]
    if p["description"]:
        lines += [p["description"], ""]
    if p["old_price"] and p["old_price"] > p["price"]:
        pct = round((1 - p["price"] / p["old_price"]) * 100)
        lines.append(t("price_disc", lang, old=money(p["old_price"]), price=money(p["price"]), pct=pct))
    else:
        lines.append(t("price", lang, price=money(p["price"])))
    if u["promo_percent"]:
        fp, _, code = final_price(u, p["price"])
        lines.append(t("promo_applied", lang, code=html.escape(code), price=money(fp)))
    if db.unlimited(p):
        lines.append(t("stock_manual", lang))
    else:
        n = db.stock(p["id"])
        lines.append(t("stock", lang, n=n) if n else t("stock_out", lang))
    if is_multi(p) and in_stock(p):
        lines.append(t("multi_hint", lang))
    return "\n".join(lines)


def in_stock(p):
    return db.unlimited(p) or db.stock(p["id"]) > 0


async def show_product(call: CallbackQuery, pid, kind, lang):
    p = db.product(pid)
    if not p or not p["active"]:
        return False
    uid = call.from_user.id
    db.add_view(uid, pid)
    u = db.get_user(uid)
    fav = db.is_fav(uid, pid)
    first = btn("buy", lang, f"buy:{pid}:{kind}") if in_stock(p) else btn("notify", lang, f"nt:{pid}")
    await render(call, product_text(p, lang, u), kb([
        [first],
        [btn("fav_del" if fav else "fav_add", lang, f"fv:{pid}:{kind}")],
        [btn("back", lang, f"l:{kind}:0"), btn("main_menu", lang, "menu")],
    ]))
    return True


@router.callback_query(F.data.startswith("p:"))
async def cb_product(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(None)
    _, pid, kind = call.data.split(":")
    if not await show_product(call, int(pid), kind, lang):
        return await call.answer(t("not_found", lang), show_alert=True)
    await call.answer()


@router.callback_query(F.data.startswith("fv:"))
async def cb_fav(call: CallbackQuery, lang: str):
    _, pid, kind = call.data.split(":")
    if not db.product(int(pid)):
        return await call.answer(t("not_found", lang), show_alert=True)
    added = db.toggle_fav(call.from_user.id, int(pid))
    await show_product(call, int(pid), kind, lang)
    await call.answer(t("fav_added" if added else "fav_removed", lang))


@router.callback_query(F.data.startswith("nt:"))
async def cb_notify(call: CallbackQuery, lang: str):
    db.add_notify(call.from_user.id, int(call.data.split(":")[1]))
    await call.answer(t("notify_on", lang), show_alert=True)


# ---------- покупка ----------
def parse_cb(data, n):
    """'buy:5:new:3' -> ['buy','5','new','3']; недостающие хвостовые части заполняются пустыми."""
    parts = data.split(":")
    return parts + [""] * (n - len(parts))


def total_price(u, p, qty):
    return final_price(u, round(p["price"] * qty, 2))


def qty_text(p, u, qty, lang):
    total, _, _ = total_price(u, p, qty)
    avail = t("qty_avail_manual", lang) if db.unlimited(p) else t("qty_avail_n", lang, n=db.stock(p["id"]))
    return t("qty_title", lang, name=name_html(p), price=money(p["price"]), avail=avail, qty=qty, total=money(total))


async def show_qty(call: CallbackQuery, p, kind, qty, lang):
    u = db.get_user(call.from_user.id)
    top = max_qty(p)
    qty = min(max(qty, 1), top)
    pid = p["id"]

    def step(label, n):
        return InlineKeyboardButton(text=label, callback_data=f"qty:{pid}:{kind}:{min(max(n, 1), top)}")

    await render(call, qty_text(p, u, qty, lang), kb([
        [step("−10", qty - 10), step("−1", qty - 1),
         InlineKeyboardButton(text=str(qty), callback_data="noop"),
         step("+1", qty + 1), step("+10", qty + 10)],
        [btn("qty_input", lang, f"qtyin:{pid}:{kind}")],
        [btn("qty_confirm", lang, f"co:{pid}:{kind}:{qty}")],
        [btn("back", lang, f"p:{pid}:{kind}"), btn("main_menu", lang, "menu")],
    ]))
    return qty


async def show_checkout(call: CallbackQuery, p, kind, qty, lang):
    u = db.get_user(call.from_user.id)
    total, _, _ = total_price(u, p, qty)
    name = html.escape(p["name"]) + (f" × {qty}" if qty > 1 else "")
    back_cb = f"qty:{p['id']}:{kind}:{qty}" if is_multi(p) else f"p:{p['id']}:{kind}"
    await render(call, t("choose_pay", lang, name=name, price=money(total), balance=money(u["balance"])), kb([
        [btn("pay_balance", lang, f"pb:{p['id']}:{qty}"), btn("pay_sbp", lang, f"ps:{p['id']}:{qty}")],
        legal_row(lang),
        [btn("back", lang, back_cb), btn("main_menu", lang, "menu")],
    ]))


def check_buyable(p, qty):
    """None — можно покупать, иначе ключ текста-ошибки."""
    if not p or not p["active"]:
        return "not_found"
    if not in_stock(p) or qty > max_qty(p):
        return "out_alert"
    return None


async def reject_buy(call: CallbackQuery, p, kind, err, lang):
    if err == "out_alert":
        await show_product(call, p["id"], kind, lang)
    await call.answer(t(err, lang), show_alert=True)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, lang: str):
    _, pid, kind, _q = parse_cb(call.data, 4)
    p = db.product(int(pid))
    err = check_buyable(p, 1)
    if err:
        return await reject_buy(call, p, kind, err, lang)
    if is_multi(p):
        await show_qty(call, p, kind, 1, lang)
    else:
        await show_checkout(call, p, kind, 1, lang)
    await call.answer()


@router.callback_query(F.data.startswith("qty:"))
async def cb_qty(call: CallbackQuery, state: FSMContext, lang: str):
    await state.set_state(None)
    _, pid, kind, n = parse_cb(call.data, 4)
    p = db.product(int(pid))
    err = check_buyable(p, 1)
    if err:
        return await reject_buy(call, p, kind, err, lang)
    want = int(n or 1)
    got = await show_qty(call, p, kind, want, lang)
    await call.answer(t("qty_max", lang, max=got) if want > got else None)


@router.callback_query(F.data.startswith("qtyin:"))
async def cb_qty_input(call: CallbackQuery, state: FSMContext, lang: str):
    _, pid, kind = parse_cb(call.data, 3)
    p = db.product(int(pid))
    err = check_buyable(p, 1)
    if err:
        return await reject_buy(call, p, kind, err, lang)
    await state.set_state(ShopSt.qty)
    await state.update_data(qty_pid=p["id"], qty_kind=kind)
    await render(call, t("qty_prompt", lang, max=max_qty(p)), kb([[btn("cancel", lang, f"qty:{p['id']}:{kind}:1")]]))
    await call.answer()


@router.message(ShopSt.qty, F.text)
async def msg_qty(m: Message, state: FSMContext, lang: str):
    d = await state.get_data()
    p = db.product(d.get("qty_pid") or 0)
    kind = d.get("qty_kind", "new")
    err = check_buyable(p, 1)
    if err:
        await state.set_state(None)
        return await m.answer(t(err, lang), reply_markup=kb([menu_row(lang)]))
    top = max_qty(p)
    txt = m.text.strip()
    if not txt.isdigit() or not 1 <= int(txt) <= top:
        return await m.answer(t("qty_bad", lang, max=top))
    await state.set_state(None)
    qty = int(txt)
    await m.answer(qty_text(p, db.get_user(m.from_user.id), qty, lang), reply_markup=kb([
        [btn("qty_confirm", lang, f"co:{p['id']}:{kind}:{qty}")],
        [btn("qty_input", lang, f"qtyin:{p['id']}:{kind}")],
        [btn("back", lang, f"p:{p['id']}:{kind}"), btn("main_menu", lang, "menu")],
    ]))


@router.callback_query(F.data.startswith("co:"))
async def cb_checkout(call: CallbackQuery, lang: str):
    _, pid, kind, n = parse_cb(call.data, 4)
    p = db.product(int(pid))
    qty = max(int(n or 1), 1)
    err = check_buyable(p, qty)
    if err:
        return await reject_buy(call, p, kind, err, lang)
    await show_checkout(call, p, kind, qty, lang)
    await call.answer()


@router.callback_query(F.data.startswith("pb:"))
async def cb_pay_balance(call: CallbackQuery, lang: str, bot: Bot):
    _, pid, n = parse_cb(call.data, 3)
    qty = max(int(n or 1), 1)
    p = db.product(int(pid))
    err = check_buyable(p, qty)
    if err:
        return await call.answer(t(err, lang), show_alert=True)
    u = db.get_user(call.from_user.id)
    price, _, code = total_price(u, p, qty)
    if u["balance"] < price:
        return await call.answer(t("no_money", lang), show_alert=True)
    db.add_balance(u["id"], -price)
    oid = db.create_order(u["id"], p, price, "balance", "paid", code, qty)
    await render(call, t("paid_balance", lang, oid=oid), kb([menu_row(lang)]))
    await call.answer()
    await fulfill(bot, oid)


@router.callback_query(F.data.startswith("ps:"))
async def cb_pay_sbp(call: CallbackQuery, lang: str):
    _, pid, n = parse_cb(call.data, 3)
    qty = max(int(n or 1), 1)
    p = db.product(int(pid))
    err = check_buyable(p, qty)
    if err:
        return await call.answer(t(err, lang), show_alert=True)
    u = db.get_user(call.from_user.id)
    price, _, code = total_price(u, p, qty)
    oid = db.create_order(u["id"], p, price, "sbp", "wait_pay", code, qty)
    name = html.escape(p["name"]) + (f" × {qty}" if qty > 1 else "")
    await render(call, t("sbp_text", lang, oid=oid, name=name, price=money(price),
                         details=db.get_setting("sbp_details", config.SBP_DETAILS)), kb([
        [btn("paid", lang, f"paid:{oid}")],
        [btn("cancel", lang, f"oc:{oid}")],
    ]))
    await call.answer()


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(call: CallbackQuery, state: FSMContext, lang: str):
    oid = int(call.data.split(":")[1])
    o = db.order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "wait_pay":
        return await call.answer(t("order_bad", lang), show_alert=True)
    await state.set_state(ShopSt.receipt)
    await state.update_data(receipt_oid=oid)
    await render(call, t("send_receipt", lang), kb([[btn("cancel", lang, f"oc:{oid}")]]))
    await call.answer()


@router.callback_query(F.data.startswith("oc:"))
async def cb_order_cancel(call: CallbackQuery, state: FSMContext, lang: str):
    oid = int(call.data.split(":")[1])
    o = db.order(oid)
    if o and o["user_id"] == call.from_user.id and o["status"] == "wait_pay":
        db.set_order(oid, status="canceled")
    await state.set_state(None)
    await render(call, t("order_canceled", lang), kb([[btn("catalog", lang, "cat")], menu_row(lang)]))
    await call.answer()


@router.message(ShopSt.receipt, F.photo | F.document)
async def msg_receipt(m: Message, state: FSMContext, lang: str, bot: Bot):
    oid = (await state.get_data()).get("receipt_oid")
    await state.set_state(None)
    o = db.order(oid) if oid else None
    if not o or o["status"] != "wait_pay":
        o = db.last_wait_pay(m.from_user.id)
    if not o:
        return await m.answer(t("order_bad", lang), reply_markup=kb([menu_row(lang)]))
    await send_receipt(m, o, lang, bot)


@router.message(StateFilter(None), F.photo | F.document)
async def msg_receipt_fallback(m: Message, lang: str, bot: Bot):
    """Чек прислали без нажатия «Я оплатил» или после перезапуска бота — ищем неоплаченный заказ."""
    o = db.last_wait_pay(m.from_user.id)
    if o:
        await send_receipt(m, o, lang, bot)


async def send_receipt(m: Message, o, lang: str, bot: Bot):
    oid = o["id"]
    if m.photo:
        file_id, is_photo = m.photo[-1].file_id, True
    else:
        file_id, is_photo = m.document.file_id, False
    db.set_order(oid, status="pending", receipt=file_id)

    u = db.get_user(m.from_user.id)
    caption = (f"🧾 <b>Оплата СБП — заказ #{oid}</b>\n\n👤 {user_link(u)}\n📦 {html.escape(o['product_name'])}\n"
               f"💰 Сумма: <b>{money(o['price'])}</b>")
    if o["promo_code"]:
        caption += f"\n🎟 Промокод: <code>{html.escape(o['promo_code'])}</code>"
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"a:ook:{oid}", style="success"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"a:ono:{oid}", style="danger"),
    ]])
    for aid in config.ADMINS:
        try:
            if is_photo:
                await bot.send_photo(aid, file_id, caption=caption, reply_markup=markup)
            else:
                await bot.send_document(aid, file_id, caption=caption, reply_markup=markup)
        except Exception as e:
            logging.warning("не удалось отправить чек админу %s: %s", aid, e)
    await m.answer(t("receipt_sent", lang), reply_markup=kb([menu_row(lang)]))


@router.message(ShopSt.receipt)
async def msg_receipt_wrong(m: Message, lang: str):
    await m.answer(t("need_receipt", lang))
