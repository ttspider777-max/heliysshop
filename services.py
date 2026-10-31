import asyncio
import html
import logging

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

import admins
import config
import db
import ext
from texts import money, t
from ui import btn, kb


def final_price(u, price):
    """Цена со скидкой покупателя -> (цена, процент, код промокода или None).
    Скидки не складываются: берётся большая из двух — скидка статуса или активный промокод.
    Код возвращается, только если сработал промокод (тогда он и расходуется)."""
    import appcfg
    promo = u["promo_percent"] or 0
    status = appcfg.status_discount(u)
    if promo and promo >= status:
        pct, code = promo, u["promo_code"]
    else:
        pct, code = status, None
    return round(price * (100 - pct) / 100, 2), pct, code


async def safe_send(bot: Bot, chat_id, text, markup=None):
    try:
        await bot.send_message(chat_id, text, reply_markup=markup)
        return True
    except Exception as e:
        logging.info("send to %s failed: %s", chat_id, e)
        return False


async def to_admins(bot: Bot, text, markup=None):
    for aid in admins.ids():
        await safe_send(bot, aid, text, markup)


def user_link(u):
    name = html.escape(u["first_name"] or "user") if u else "user"
    uname = f" (@{u['username']})" if u and u["username"] else ""
    uid = u["id"] if u else "?"
    return f'<a href="tg://user?id={uid}">{name}</a>{uname} <code>{uid}</code>'


def _lang(uid):
    u = db.get_user(uid)
    return u["lang"] if u else "ru"


def _menu_kb(lang):
    return kb([[btn("my_orders", lang, "ord:m:0")], [btn("main_menu", lang, "menu")]])


async def fulfill(bot: Bot, oid):
    """Заказ оплачен — выдаём товар. Возвращает итоговый статус: done / manual / refunded."""
    o = db.order(oid)
    uid = o["user_id"]
    lang = _lang(uid)
    p = db.product(o["product_id"])
    # промокод снимается с покупателя ещё при оформлении заказа (db.consume_promo)

    if p is not None and p["kind"] == "manual":
        db.set_order(oid, status="manual")
        await safe_send(bot, uid, t("order_manual", lang, oid=oid), _menu_kb(lang))
        await to_admins(
            bot,
            f"🛠 <b>Заказ #{oid} ждёт ручной выдачи</b>\n\n📦 {html.escape(o['product_name'])}\n💰 {money(o['price'])}\n"
            f"👤 {user_link(db.get_user(uid))}",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✉️ Выдать товар", callback_data=f"a:dlv:{oid}")]]),
        )
        await reward_referrer(bot, o)
        return "manual"

    qty = o["qty"] or 1
    if p is not None and p["kind"] == "ext":
        return await fulfill_ext(bot, o, p, qty, lang)

    items = db.take_items(o["product_id"], oid, qty) if p is not None else None
    content = None
    if items:
        sep = "\n\n" if any("\n" in i for i in items) else "\n"
        content = sep.join(items)
    if content is None:
        db.add_balance(uid, o["price"])
        db.set_order(oid, status="refunded")
        db.restore_promo(o)
        await safe_send(bot, uid, t("order_refunded", lang, oid=oid, price=money(o["price"])), _menu_kb(lang))
        await to_admins(bot, f"⚠️ Заказ #{oid}: товар «{html.escape(o['product_name'])}» закончился, "
                             f"{money(o['price'])} возвращено на баланс покупателя.")
        return "refunded"

    await deliver(bot, oid, content)
    await reward_referrer(bot, o)
    return "done"


async def fulfill_ext(bot: Bot, o, p, qty, lang):
    """Товар внешнего магазина: покупаем у поставщика по API и отдаём покупателю."""
    oid, uid = o["id"], o["user_id"]
    shop = db.ext_shop(p["ext_shop"])
    items, error = [], None
    if shop is None or not shop["active"]:
        error = "магазин-поставщик отключён или удалён"
    else:
        try:
            items = await ext.purchase(shop, p, qty)
        except Exception as e:  # ExtError и любые сбои сети — деньги покупателю возвращаем в любом случае
            error = str(e)
    got = min(len(items), qty)
    if got:
        db.dec_ext_stock(p["id"], got)  # не ждём автосинхронизации, чтобы не продавать то, чего уже нет
    elif error and p["ext_stock"] and p["ext_stock"] > 0 and any(
            w in error.lower() for w in ("stock", "нет в наличии", "закончил", "out of")):
        db.update_product(p["id"], ext_stock=0)  # поставщик сообщил, что товар закончился
    if got < qty:
        refund = round(o["price"] * (qty - got) / qty, 2)
        db.add_balance(uid, refund)
        name = html.escape(o["product_name"])
        if got == 0:
            db.set_order(oid, status="refunded")
            db.restore_promo(o)
            await safe_send(bot, uid, t("order_refunded_ext", lang, oid=oid, price=money(refund)), _menu_kb(lang))
            await to_admins(bot, f"⚠️ Заказ #{oid}: поставщик не выдал «{name}».\n"
                                 f"Причина: {html.escape(error or 'нет ответа')}\n"
                                 f"{money(refund)} возвращено на баланс покупателя. "
                                 f"Проверьте баланс и статус у магазина «{html.escape(shop['name']) if shop else '—'}».")
            return "refunded"
        db.set_order(oid, price=round(o["price"] - refund, 2))
        o = db.order(oid)
        await to_admins(bot, f"⚠️ Заказ #{oid}: поставщик выдал {got} из {qty} шт. «{name}», "
                             f"{money(refund)} возвращено покупателю на баланс.")
    items = items[:qty]
    sep = "\n\n" if any("\n" in i for i in items) else "\n"
    await deliver(bot, oid, sep.join(items))
    await reward_referrer(bot, o)
    return "done"


async def deliver(bot: Bot, oid, content):
    o = db.order(oid)
    db.set_order(oid, status="done", content=content)
    lang = _lang(o["user_id"])
    text = t("order_delivered", lang, oid=oid, name=html.escape(o["product_name"]), content=html.escape(content))
    if len(text) <= 4000:
        await safe_send(bot, o["user_id"], text, _menu_kb(lang))
        await ask_review(bot, o["user_id"])
        return
    # много позиций не влезают в одно сообщение — отправляем файлом
    head = t("order_delivered_file", lang, oid=oid, name=html.escape(o["product_name"]))
    try:
        await bot.send_document(o["user_id"], BufferedInputFile(content.encode("utf-8"), f"order_{oid}.txt"),
                                caption=head, reply_markup=_menu_kb(lang))
    except Exception as e:
        logging.warning("не удалось отправить файл заказа %s: %s", oid, e)
    await ask_review(bot, o["user_id"])


async def ask_review(bot: Bot, uid):
    """После покупки просим оставить отзыв (ссылка и юзернейм — в ⚙️ Настройки; пустая ссылка — не просим)."""
    link = db.get_setting("review_url", config.REVIEW_URL)
    if not link:
        return
    user = db.get_setting("review_user", config.REVIEW_USER) or ""
    await safe_send(bot, uid, t("review_ask", _lang(uid), link=link, user=html.escape(user)))



async def reward_referrer(bot: Bot, o):
    u = db.get_user(o["user_id"])
    rid = u["referrer_id"] if u else None
    if not rid or not db.get_user(rid):
        return
    pct = float(db.get_setting("ref_percent", config.REF_PERCENT))
    amount = round(o["price"] * pct / 100, 2)
    if amount <= 0:
        return
    db.add_ref_balance(rid, amount)
    await safe_send(bot, rid, t("ref_bonus", _lang(rid), amount=money(amount)))


async def notify_arrival(bot: Bot, pid):
    p = db.product(pid)
    if not p:
        return 0
    n = 0
    for uid in db.pop_notify(pid):
        lang = _lang(uid)
        markup = kb([[btn("buy", lang, f"p:{pid}:new")], [btn("main_menu", lang, "menu")]])
        if await safe_send(bot, uid, t("notify_arrived", lang, name=html.escape(p["name"])), markup):
            n += 1
        await asyncio.sleep(0.05)
    return n


async def broadcast(bot: Bot, ids, send, report_to):
    """send — корутина-функция (bot, uid), отправляющая сообщение одному пользователю."""
    ok = fail = 0
    for uid in ids:
        try:
            await send(bot, uid)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await safe_send(bot, report_to, f"📢 Рассылка завершена\n\n✅ Доставлено: {ok}\n❌ Не доставлено: {fail}")
