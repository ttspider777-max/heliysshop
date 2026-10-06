import asyncio
import html
import io
import re

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message

import config
import db
import subscription
from services import broadcast, deliver, fulfill, notify_arrival, safe_send, user_link
from texts import BUTTONS, EDITABLE_TEXTS, bt, fdate, money, status, t
from ui import HIDEABLE, fix_url, is_hidden, kb, pager, render, split_custom_emoji

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMINS))
router.callback_query.filter(F.from_user.id.in_(config.ADMINS))


class A(StatesGroup):
    inp = State()


class ClearState(BaseMiddleware):
    """Любая кнопка админки сбрасывает ожидание ввода (кроме шагов мастера добавления товара)."""

    async def __call__(self, handler, event, data):
        st = data.get("state")
        if st and not event.data.startswith("a:npk:"):
            await st.clear()
        return await handler(event, data)


router.callback_query.middleware(ClearState())


def B(text, cb=None, url=None, style=None):
    return InlineKeyboardButton(text=text, callback_data=cb, url=url, style=style)


def back(cb="a:home", text="◀️ Назад"):
    return [B(text, cb)]


STYLE_NAMES = {"": "обычный", "primary": "синий", "success": "зелёный", "danger": "красный"}
STYLE_ORDER = ["", "primary", "success", "danger"]


# ======================= главное меню админки =======================
def admin_kb():
    return kb([
        [B("📊 Статистика", "a:stats"), B("👥 Пользователи", "a:users")],
        [B("👤 Профиль юзера", "a:uinfo"), B("💰 Баланс", "a:bal")],
        [B("🚫 Забанить", "a:ban", style="danger"), B("✅ Разбанить", "a:unban", style="success")],
        [B("📢 Рассылка", "a:bc", style="primary")],
        [B("➕ Добавить товар", "a:addp", style="success"), B("📦 Пополнить склад", "a:additems", style="success")],
        [B("🗂 Товары", "a:prods:0"), B("📁 Категории", "a:cats")],
        [B("🔌 Внешние магазины (API)", "a:xs", style="primary")],
        [B("🏭 Поставщики", "a:sup"), B("🙈 Скрыть кнопки", "a:vis")],
        [B("📄 Документы (оплата)", "a:docs", style="primary")],
        [B("🎟 Промокоды", "a:promos"), B("✏️ Оформление", "a:design")],
        [B("📣 Обязательная подписка", "a:subs", style="primary"), B("⚙️ Настройки", "a:settings")],
        [B("🏠 Главное меню бота", "menu")],
    ])


def admin_text():
    s = db.stats()
    return (f"⚙️ <b>Админ-панель heliys shop</b>\n\n👥 Пользователей: <b>{s['users']}</b>\n"
            f"🛒 Продаж: <b>{s['orders']}</b> на <b>{money(s['rev'])}</b>\n"
            f"🔎 Чеков на проверке: <b>{s['pending']}</b>\n🛠 Ждут ручной выдачи: <b>{s['manual']}</b>\n"
            f"💸 Заявок на вывод: <b>{s['wd_pending']}</b>")


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    await state.clear()
    await render(m, admin_text(), admin_kb())


@router.callback_query(F.data == "a:home")
async def cb_home(call: CallbackQuery):
    await render(call, admin_text(), admin_kb())
    await call.answer()


async def ask(call: CallbackQuery, state: FSMContext, act, prompt, cancel="a:home", **data):
    await state.set_state(A.inp)
    await state.set_data({"act": act, **data})
    await render(call, prompt, kb([[B("❌ Отмена", cancel, style="danger")]]))
    await call.answer()


# ---------- обработчики ввода ----------
INPUTS = {}
SLASH_OK = {"xs_edit"}  # шаги ввода, где текст может начинаться с «/»


def inp(act):
    def deco(fn):
        INPUTS[act] = fn
        return fn
    return deco


@router.message(A.inp)
async def on_input(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    txt = (m.text or m.caption or "").strip()
    # команда отменяет ввод; но в полях, где вводят пути API (/products), отменяют только настоящие команды бота
    is_cmd = txt.startswith("/") and (d.get("act") not in SLASH_OK or
                                      txt.split()[0].split("@")[0] in ("/start", "/admin", "/cancel", "/privacy", "/terms"))
    if is_cmd:
        await state.clear()
        return await m.answer("Ввод отменён.", reply_markup=admin_kb())
    fn = INPUTS.get(d.get("act"))
    if not fn:
        await state.clear()
        return await m.answer("Ввод отменён.", reply_markup=admin_kb())
    await fn(m, state, d, txt, bot)


async def done(m: Message, state: FSMContext, text, markup=None):
    await state.clear()
    await m.answer(text, reply_markup=markup or kb([back()]))


def parse_amount(s):
    try:
        v = round(float(s.replace(",", ".")), 2)
        return v if v == v else None
    except ValueError:
        return None


# ======================= статистика / пользователи =======================
@router.callback_query(F.data == "a:stats")
async def cb_stats(call: CallbackQuery):
    s = db.stats()
    top = f"{html.escape(s['top']['product_name'])} ({s['top']['c']} шт.)" if s["top"] else "—"
    text = (f"📊 <b>Статистика</b>\n\n"
            f"👥 Пользователей: <b>{s['users']}</b>\n   ├ сегодня: +{s['users_today']}\n   ├ за 7 дней: +{s['users_week']}\n"
            f"   └ забанено: {s['banned']}\n\n"
            f"🛒 Продаж: <b>{s['orders']}</b> (сегодня {s['orders_today']})\n"
            f"💰 Выручка: <b>{money(s['rev'])}</b>\n   ├ сегодня: {money(s['rev_today'])}\n   └ за 7 дней: {money(s['rev_week'])}\n\n"
            f"🔎 Чеков на проверке: {s['pending']}\n🛠 Ждут ручной выдачи: {s['manual']}\n💸 Заявок на вывод: {s['wd_pending']}\n\n"
            f"📦 Товаров: {s['products']}\n🔑 Товаров на складе: {s['stock']} (продано {s['sold_items']})\n"
            f"💳 Сумма балансов пользователей: {money(s['balances'])}\n🏆 Топ товар: {top}")
    await render(call, text, kb([[B("🔄 Обновить", "a:stats")], back()]))
    await call.answer()


@router.callback_query(F.data == "a:users")
async def cb_users(call: CallbackQuery):
    users = db.all_users()
    lines = [f"👥 <b>Пользователи бота: {len(users)}</b>\n", "Последние 30:"]
    for u in users[:30]:
        uname = f"@{u['username']}" if u["username"] else html.escape(u["first_name"] or "—")
        ban = " 🚫" if u["banned"] else ""
        lines.append(f"<code>{u['id']}</code> — {uname} — {fdate(u['joined'])}{ban}")
    await render(call, "\n".join(lines), kb([[B("📄 Выгрузить всех (.txt)", "a:users_file")], back()]))
    await call.answer()


@router.callback_query(F.data == "a:users_file")
async def cb_users_file(call: CallbackQuery, bot: Bot):
    rows = ["id | username | имя | дата | баланс | бан"]
    for u in db.all_users():
        rows.append(f"{u['id']} | @{u['username'] or '-'} | {u['first_name'] or '-'} | {u['joined']} | "
                    f"{u['balance']} | {'да' if u['banned'] else 'нет'}")
    data = "\n".join(rows).encode("utf-8")
    await bot.send_document(call.from_user.id, BufferedInputFile(data, "users.txt"),
                            caption=f"👥 Всего пользователей: {len(rows) - 1}")
    await call.answer()


def user_card(uid):
    u = db.get_user(uid)
    if not u:
        return None, None
    orders = db.user_orders(uid)
    text = (f"👤 <b>Профиль пользователя</b>\n\n{user_link(u)}\n"
            f"📅 В боте с: {fdate(u['joined'])}\n🌐 Язык: {u['lang']}\n"
            f"💰 Баланс: <b>{money(u['balance'])}</b>\n"
            f"💸 Реф. баланс: {money(u['ref_balance'])} (заработано {money(u['ref_earned'])})\n"
            f"👥 Приглашено: {db.count_refs(uid)}, купили: {db.count_refs_bought(uid)}\n"
            f"🔗 Пригласил: {u['referrer_id'] or '—'}\n"
            f"🛒 Заказов: {len(orders)} на {money(db.user_spent(uid))}\n"
            f"🎟 Промокод: {html.escape(u['promo_code']) + ' (' + str(u['promo_percent']) + '%)' if u['promo_percent'] else '—'}\n"
            f"🚫 Бан: {'да' if u['banned'] else 'нет'}")
    if orders:
        text += "\n\n<b>Последние заказы:</b>"
        for o in orders[:5]:
            text += f"\n#{o['id']} {html.escape(o['product_name'])} — {money(o['price'])} — {status(o['status'], 'ru')}"
    markup = kb([
        [B("➕ Выдать баланс", f"a:ub:{uid}", style="success"), B("➖ Забрать баланс", f"a:ut:{uid}", style="danger")],
        [B("✅ Разбанить" if u["banned"] else "🚫 Забанить", f"a:uban:{uid}")],
        [B("✉️ Написать от имени бота", f"a:umsg:{uid}")],
        back(),
    ])
    return text, markup


@router.callback_query(F.data == "a:uinfo")
async def cb_uinfo(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "uinfo", "👤 Отправьте ID пользователя:")


@inp("uinfo")
async def i_uinfo(m, state, d, txt, bot):
    if not txt.isdigit():
        return await m.answer("Нужен числовой ID. Попробуйте ещё раз:")
    text, markup = user_card(int(txt))
    if not text:
        return await m.answer("Пользователь не найден. Отправьте другой ID:")
    await done(m, state, text, markup)


@router.callback_query(F.data.startswith("a:uban:"))
async def cb_uban(call: CallbackQuery):
    uid = int(call.data.split(":")[2])
    u = db.get_user(uid)
    db.update_user(uid, banned=0 if u["banned"] else 1)
    text, markup = user_card(uid)
    await render(call, text, markup)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("a:ub:") | F.data.startswith("a:ut:"))
async def cb_ubal(call: CallbackQuery, state: FSMContext):
    _, op, uid = call.data.split(":")
    word = "выдать" if op == "ub" else "забрать"
    await ask(call, state, "ubal", f"💰 Сколько {word} пользователю <code>{uid}</code>? Отправьте сумму:",
              uid=int(uid), sign=1 if op == "ub" else -1)


@inp("ubal")
async def i_ubal(m, state, d, txt, bot):
    v = parse_amount(txt)
    if not v or v <= 0:
        return await m.answer("Отправьте положительное число:")
    await change_balance(m, state, bot, d["uid"], v * d["sign"])


async def change_balance(m, state, bot, uid, amount):
    u = db.get_user(uid)
    if not u:
        return await done(m, state, "Пользователь не найден.")
    db.add_balance(uid, amount)
    u = db.get_user(uid)
    lang = u["lang"]
    if amount > 0:
        note = "💰 Вам начислено на баланс: <b>+{a}</b>" if lang == "ru" else "💰 Credited to your balance: <b>+{a}</b>"
    else:
        note = "💰 С вашего баланса списано: <b>{a}</b>" if lang == "ru" else "💰 Debited from your balance: <b>{a}</b>"
    await safe_send(bot, uid, note.format(a=money(abs(amount))))
    text, markup = user_card(uid)
    await done(m, state, f"✅ Баланс изменён на {'+' if amount > 0 else '−'}{money(abs(amount))}\n\n" + text, markup)


@router.callback_query(F.data == "a:bal")
async def cb_bal(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "bal", "💰 Отправьте <b>ID и сумму</b> через пробел.\n\n"
                                  "<code>123456789 100</code> — выдать 100₽\n<code>123456789 -50</code> — забрать 50₽")


@inp("bal")
async def i_bal(m, state, d, txt, bot):
    parts = txt.split()
    if len(parts) != 2 or not parts[0].isdigit() or parse_amount(parts[1]) in (None, 0):
        return await m.answer("Формат: <code>ID сумма</code>. Попробуйте ещё раз:")
    await change_balance(m, state, bot, int(parts[0]), parse_amount(parts[1]))


@router.callback_query(F.data.startswith("a:umsg:"))
async def cb_umsg(call: CallbackQuery, state: FSMContext):
    uid = int(call.data.split(":")[2])
    await ask(call, state, "umsg", f"✉️ Отправьте сообщение для <code>{uid}</code> (текст, фото, премиум-эмодзи — всё сохранится):", uid=uid)


@inp("umsg")
async def i_umsg(m, state, d, txt, bot):
    try:
        await bot.copy_message(d["uid"], m.chat.id, m.message_id)
        await done(m, state, "✅ Отправлено.")
    except Exception as e:
        await done(m, state, f"❌ Не удалось отправить: {html.escape(str(e))}")


# ======================= бан =======================
@router.callback_query(F.data.in_({"a:ban", "a:unban"}))
async def cb_ban(call: CallbackQuery, state: FSMContext):
    ban = call.data == "a:ban"
    await ask(call, state, "ban" if ban else "unban", f"{'🚫' if ban else '✅'} Отправьте ID пользователя для {'бана' if ban else 'разбана'}:")


@inp("ban")
@inp("unban")
async def i_ban(m, state, d, txt, bot):
    if not txt.isdigit():
        return await m.answer("Нужен числовой ID:")
    uid = int(txt)
    if uid in config.ADMINS:
        return await done(m, state, "Админа забанить нельзя.")
    ban = d["act"] == "ban"
    if not db.get_user(uid):
        db.create_user(uid, None, None, "ru")
    db.update_user(uid, banned=1 if ban else 0)
    await done(m, state, f"{'🚫 Пользователь забанен' if ban else '✅ Пользователь разбанен'}: <code>{uid}</code>")


# ======================= рассылка =======================
@router.callback_query(F.data == "a:bc")
async def cb_bc(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "bc", "📢 Отправьте сообщение для рассылки от имени бота.\n\n"
                                 "Можно текст, фото, видео, форматирование и <b>премиум-эмодзи</b> — всё будет разослано как есть.")


@inp("bc")
async def i_bc(m, state, d, txt, bot):
    ids = db.all_user_ids()
    chat_id, mid = m.chat.id, m.message_id

    async def send(b, uid):
        await b.copy_message(uid, chat_id, mid)

    asyncio.create_task(broadcast(bot, ids, send, m.from_user.id))
    await done(m, state, f"📢 Рассылка запущена на {len(ids)} пользователей. Пришлю отчёт по завершении.")


# ======================= товары =======================
def cats_kb(prefix, cancel="a:home"):
    rows = [[B(c["name"], f"{prefix}{c['id']}")] for c in db.categories()]
    rows.append(back(cancel))
    return kb(rows)


NAME_HINT = "\n\n💎 Можно добавить <b>премиум-эмодзи</b> в название — оно станет иконкой товара в списке и в карточке."


@router.callback_query(F.data == "a:addp")
async def cb_addp(call: CallbackQuery):
    if not db.categories():
        return await call.answer("Сначала создайте категорию", show_alert=True)
    await render(call, "➕ <b>Новый товар</b>\n\nШаг 1/5 — выберите категорию:", cats_kb("a:npc:"))
    await call.answer()


@router.callback_query(F.data.startswith("a:npc:"))
async def cb_np_cat(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "np_name", "Шаг 2/5 — отправьте <b>название</b> товара:" + NAME_HINT, cid=int(call.data.split(":")[2]))


@inp("np_name")
async def i_np_name(m, state, d, txt, bot):
    name, icon = split_custom_emoji(m)
    if not name:
        return await m.answer("Отправьте название текстом:")
    await state.update_data(act="np_desc", name=name[:100], icon=icon)
    await m.answer("Шаг 3/5 — отправьте <b>описание</b> товара.\n"
                   "Форматирование и премиум-эмодзи сохранятся. Без описания — отправьте <code>-</code>")


@inp("np_desc")
async def i_np_desc(m, state, d, txt, bot):
    desc = "" if txt == "-" else m.html_text
    await state.update_data(act="np_price", desc=desc)
    await m.answer("Шаг 4/5 — отправьте <b>цену</b> в рублях (например <code>199</code>):")


@inp("np_price")
async def i_np_price(m, state, d, txt, bot):
    v = parse_amount(txt)
    if v is None or v < 0:
        return await m.answer("Отправьте цену числом:")
    await state.update_data(act="np_kind", price=v)
    await m.answer("Шаг 5/5 — как выдавать товар?", reply_markup=kb([
        [B("🤖 Автовыдача (товары со склада)", "a:npk:auto")],
        [B("🛠 Ручная выдача (админ выдаёт сам)", "a:npk:manual")],
        [B("❌ Отмена", "a:home", style="danger")],
    ]))


@router.callback_query(F.data.startswith("a:npk:"))
async def cb_np_kind(call: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    if d.get("act") != "np_kind":
        return await call.answer("Мастер устарел, начните заново", show_alert=True)
    kind = call.data.split(":")[2]
    pid = db.add_product(d["cid"], d["name"], d["desc"], d["price"], kind, d.get("icon"))
    await call.answer("✅ Товар создан")
    await show_admin_product(call, pid, prefix="✅ <b>Товар создан!</b>\n\n")


def admin_product_text(p):
    cat = db.category(p["category_id"])
    disc = ""
    if p["old_price"] and p["old_price"] > p["price"]:
        disc = f" (скидка, было {money(p['old_price'])})"
    stock = "∞ (ручная выдача)" if p["kind"] == "manual" else f"{db.stock(p['id'])} шт."
    kind = {"auto": "автоматическая", "manual": "ручная", "ext": "через API внешнего магазина"}[p["kind"]]
    ext_info = ""
    if p["kind"] == "ext":
        shop = db.ext_shop(p["ext_shop"])
        stock = "не сообщается магазином" if (p["ext_stock"] or 0) < 0 else f"{db.stock(p['id'])} шт. (у поставщика)"
        ext_info = (f"🔌 Магазин: {html.escape(shop['name']) if shop else '—'}, ID у них: <code>{html.escape(str(p['ext_pid']))}</code>\n"
                    f"🏷 Закупка: {money(p['ext_price'])} → продажа {money(p['price'])}\n")
    return (f"📦 <b>{'💎 ' if p['emoji_id'] else ''}{html.escape(p['name'])}</b>  [ID {p['id']}]\n\n"
            f"📁 Категория: {html.escape(cat['name']) if cat else '—'}\n"
            f"💰 Цена: {money(p['price'])}{disc}\n"
            f"🔧 Выдача: {kind}\n"
            f"{ext_info}"
            f"🔑 Склад: {stock}\n"
            f"👁 Виден покупателям: {'да' if p['active'] else 'нет'}\n\n"
            f"📝 Описание:\n{p['description'] or '—'}")


async def show_admin_product(target, pid, prefix=""):
    p = db.product(pid)
    if not p:
        return await render(target, "Товар удалён.", kb([back("a:prods:0")]))
    rows = [[B("✏️ Название", f"a:pe:name:{pid}"), B("📝 Описание", f"a:pe:desc:{pid}")]]
    if p["kind"] == "ext":  # цена внешнего товара = закупка + наценка магазина, меняется в настройках магазина
        rows.append([B("🔌 Настройки магазина (наценка)", f"a:xs:{p['ext_shop']}")])
    else:
        rows.append([B("💰 Цена", f"a:pe:price:{pid}"), B("🏷 Скидка", f"a:pe:disc:{pid}")])
    if p["old_price"] and p["old_price"] > p["price"]:
        rows.append([B("❎ Убрать скидку", f"a:pnd:{pid}")])
    if p["kind"] == "auto":
        rows.append([B("📦 Пополнить склад", f"a:ai:{pid}", style="success"), B("🗑 Очистить склад", f"a:pclr:{pid}")])
    kind_btn = [] if p["kind"] == "ext" else [B("🔧 Тип выдачи", f"a:pkind:{pid}")]
    rows += [
        [B("📁 Категория", f"a:pcat:{pid}")] + kind_btn,
        [B("🙈 Скрыть" if p["active"] else "👁 Показать", f"a:pact:{pid}"), B("❌ Удалить", f"a:pdel:{pid}", style="danger")],
        back("a:prods:0", "◀️ К товарам"),
    ]
    await render(target, prefix + admin_product_text(p), kb(rows))


@router.callback_query(F.data.startswith("a:prods:"))
async def cb_prods(call: CallbackQuery):
    await prods_view(call, int(call.data.split(":")[2]))
    await call.answer()


async def prods_view(call, page):
    items = db.all_products()
    per = 10
    pages = max(1, (len(items) + per - 1) // per)
    page = min(max(page, 0), pages - 1)
    rows = []
    for p in items[page * per:(page + 1) * per]:
        st = "∞" if db.unlimited(p) else db.stock(p["id"])
        hid = "🙈 " if not p["active"] else ""
        rows.append([B(f"{hid}{p['name']} — {money(p['price'])} [{st}]", f"a:p:{p['id']}")])
    rows.append(pager("a:prods:", page, pages))
    rows.append([B("➕ Добавить товар", "a:addp", style="success")])
    rows.append(back())
    await render(call, f"🗂 <b>Товары</b> — {len(items)}\n\nВ скобках — остаток на складе.", kb(rows))


@router.callback_query(F.data.startswith("a:p:"))
async def cb_prod(call: CallbackQuery):
    await show_admin_product(call, int(call.data.split(":")[2]))
    await call.answer()


PE_PROMPTS = {
    "name": "✏️ Отправьте новое название." + NAME_HINT,
    "desc": "📝 Отправьте новое описание (форматирование и премиум-эмодзи сохранятся, <code>-</code> — убрать):",
    "price": "💰 Отправьте новую цену (скидка при этом сбросится):",
    "disc": "🏷 Отправьте <b>цену со скидкой</b>.\nТекущая цена станет зачёркнутой, товар появится в разделе «Скидки».",
}


@router.callback_query(F.data.startswith("a:pe:"))
async def cb_pedit(call: CallbackQuery, state: FSMContext):
    _, _, field, pid = call.data.split(":")
    await ask(call, state, "pe", PE_PROMPTS[field], cancel=f"a:p:{pid}", field=field, pid=int(pid))


@inp("pe")
async def i_pedit(m, state, d, txt, bot):
    pid, field = d["pid"], d["field"]
    p = db.product(pid)
    if not p:
        return await done(m, state, "Товар не найден.")
    if field == "name":
        name, icon = split_custom_emoji(m)
        if not name:
            return await m.answer("Отправьте название текстом:")
        db.update_product(pid, name=name[:100], emoji_id=icon)
    elif field == "desc":
        db.update_product(pid, description="" if txt == "-" else m.html_text)
    else:
        v = parse_amount(txt)
        if v is None or v < 0:
            return await m.answer("Отправьте число:")
        if field == "price":
            db.update_product(pid, price=v, old_price=0)
        else:
            base = p["old_price"] if p["old_price"] and p["old_price"] > p["price"] else p["price"]
            if v >= base:
                return await m.answer(f"Цена со скидкой должна быть меньше {money(base)}:")
            db.update_product(pid, price=v, old_price=base)
    await state.clear()
    await show_admin_product(m, pid, prefix="✅ Сохранено\n\n")


@router.callback_query(F.data.startswith("a:pnd:"))
async def cb_pnodisc(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    p = db.product(pid)
    db.update_product(pid, price=p["old_price"], old_price=0)
    await show_admin_product(call, pid)
    await call.answer("Скидка убрана")


@router.callback_query(F.data.startswith("a:pact:"))
async def cb_pact(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    db.update_product(pid, active=0 if db.product(pid)["active"] else 1)
    await show_admin_product(call, pid)
    await call.answer()


@router.callback_query(F.data.startswith("a:pkind:"))
async def cb_pkind(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    if db.product(pid)["kind"] == "ext":
        return await call.answer("У товара внешнего магазина тип выдачи менять нельзя", show_alert=True)
    db.update_product(pid, kind="manual" if db.product(pid)["kind"] == "auto" else "auto")
    await show_admin_product(call, pid)
    await call.answer()


@router.callback_query(F.data.startswith("a:pclr:"))
async def cb_pclr(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    await render(call, "🗑 Удалить все непроданные товары со склада?",
                 kb([[B("Да, очистить", f"a:pclr2:{pid}", style="danger")], back(f"a:p:{pid}", "Отмена")]))
    await call.answer()


@router.callback_query(F.data.startswith("a:pclr2:"))
async def cb_pclr2(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    db.clear_stock(pid)
    await show_admin_product(call, pid)
    await call.answer("Склад очищен")


@router.callback_query(F.data.startswith("a:pdel:"))
async def cb_pdel(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    await render(call, "❌ Удалить товар вместе со складом? Это нельзя отменить.",
                 kb([[B("Да, удалить", f"a:pdel2:{pid}", style="danger")], back(f"a:p:{pid}", "Отмена")]))
    await call.answer()


@router.callback_query(F.data.startswith("a:pdel2:"))
async def cb_pdel2(call: CallbackQuery):
    db.delete_product(int(call.data.split(":")[2]))
    await prods_view(call, 0)
    await call.answer("Товар удалён")


@router.callback_query(F.data.startswith("a:pcat:"))
async def cb_pcat(call: CallbackQuery):
    pid = int(call.data.split(":")[2])
    rows = [[B(c["name"], f"a:pcs:{pid}:{c['id']}")] for c in db.categories()]
    rows.append(back(f"a:p:{pid}"))
    await render(call, "📁 Выберите новую категорию:", kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:pcs:"))
async def cb_pcs(call: CallbackQuery):
    _, _, pid, cid = call.data.split(":")
    db.update_product(int(pid), category_id=int(cid))
    await show_admin_product(call, int(pid))
    await call.answer("Категория изменена")


# ---------- склад ----------
@router.callback_query(F.data == "a:additems")
async def cb_additems(call: CallbackQuery):
    prods = [p for p in db.all_products() if p["kind"] == "auto"]
    if not prods:
        return await call.answer("Нет товаров с автовыдачей. Сначала создайте товар с автовыдачей.", show_alert=True)
    rows = [[B(f"{p['name']} [{db.stock(p['id'])}]", f"a:ai:{p['id']}")] for p in prods]
    rows.append(back())
    await render(call, "📦 <b>Пополнить склад</b>\n\nВыберите товар:", kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:ai:"))
async def cb_ai(call: CallbackQuery, state: FSMContext):
    pid = int(call.data.split(":")[2])
    p = db.product(pid)
    await ask(call, state, "items",
              f"📦 Товар: <b>{html.escape(p['name'])}</b> (в наличии {db.stock(pid)})\n\n"
              "Отправьте товары текстом или <b>.txt файлом</b>.\n\n"
              "• <b>одна строка = один товар</b>, например:\n<code>ключ-1\nключ-2</code>\n\n"
              "• если данные одного товара занимают несколько строк — разделяйте товары <b>пустой строкой</b>.\n\n"
              "Бот будет выдавать их покупателям автоматически, по одному на заказ.",
              cancel=f"a:p:{pid}", pid=pid)


@inp("items")
async def i_items(m, state, d, txt, bot):
    pid = d["pid"]
    raw = m.text or ""
    if m.document:
        buf = io.BytesIO()
        await bot.download(m.document, destination=buf)
        raw = buf.getvalue().decode("utf-8", errors="ignore")
    raw = raw.replace("\r\n", "\n").strip()
    if not raw:
        return await m.answer("Пусто. Отправьте текст или .txt файл:")
    if re.search(r"\n\s*\n", raw):
        chunks = [c.strip() for c in re.split(r"\n\s*\n", raw)]
    else:
        chunks = [c.strip() for c in raw.split("\n")]
    chunks = [c for c in chunks if c]
    was = db.stock(pid)
    n = db.add_items(pid, chunks)
    await state.clear()
    notified = await notify_arrival(bot, pid) if n else 0
    extra = f"\n🔔 Уведомлено ожидающих: {notified}" if notified else ""
    await show_admin_product(m, pid, prefix=f"✅ Добавлено: <b>{n}</b> (было {was}, стало {db.stock(pid)}){extra}\n\n")


# ======================= заказы: чеки, ручная выдача =======================
async def mark_admin_msg(call: CallbackQuery, note):
    try:
        base = call.message.html_text or ""
        if call.message.photo or call.message.document:
            await call.message.edit_caption(caption=f"{base}\n\n{note}", reply_markup=None)
        else:
            await call.message.edit_text(f"{base}\n\n{note}", reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("a:ook:"))
async def cb_order_ok(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[2])
    o = db.order(oid)
    if not o or o["status"] != "pending":
        await mark_admin_msg(call, f"ℹ️ Уже обработан: {status(o['status'], 'ru') if o else '—'}")
        return await call.answer("Заказ уже обработан", show_alert=True)
    db.set_order(oid, status="paid")
    res = await fulfill(bot, oid)
    labels = {"done": "✅ Одобрено, товар выдан", "manual": "✅ Одобрено, ждёт ручной выдачи",
              "refunded": "⚠️ Одобрено, но товара нет — деньги на балансе"}
    await mark_admin_msg(call, f"{labels[res]} ({html.escape(call.from_user.first_name)})")
    await call.answer(labels[res])


@router.callback_query(F.data.startswith("a:ono:"))
async def cb_order_no(call: CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[2])
    o = db.order(oid)
    if not o or o["status"] != "pending":
        await mark_admin_msg(call, f"ℹ️ Уже обработан: {status(o['status'], 'ru') if o else '—'}")
        return await call.answer("Заказ уже обработан", show_alert=True)
    db.set_order(oid, status="rejected")
    u = db.get_user(o["user_id"])
    lang = u["lang"] if u else "ru"
    surl = fix_url(db.get_setting("support_url", config.SUPPORT_URL))
    await safe_send(bot, o["user_id"], t("order_rejected", lang, oid=oid),
                    kb([[InlineKeyboardButton(text=bt("support", lang), url=surl)]]) if surl else None)
    await mark_admin_msg(call, f"❌ Отклонено ({html.escape(call.from_user.first_name)})")
    await call.answer("Отклонено")


@router.callback_query(F.data.startswith("a:dlv:"))
async def cb_deliver(call: CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[2])
    o = db.order(oid)
    if not o or o["status"] != "manual":
        return await call.answer("Заказ уже выдан или недоступен", show_alert=True)
    await state.set_state(A.inp)
    await state.set_data({"act": "dlv", "oid": oid})
    await call.message.answer(f"✉️ Отправьте данные товара для заказа #{oid} ({html.escape(o['product_name'])}).\n"
                              "Покупатель получит их сообщением.",
                              reply_markup=kb([[B("❌ Отмена", "a:home", style="danger")]]))
    await call.answer()


@inp("dlv")
async def i_deliver(m, state, d, txt, bot):
    o = db.order(d["oid"])
    if not o or o["status"] != "manual":
        return await done(m, state, "Заказ уже выдан.")
    if not txt:
        return await m.answer("Отправьте данные текстом:")
    await deliver(bot, d["oid"], txt)
    await done(m, state, f"✅ Заказ #{d['oid']} выдан.")


# ======================= вывод реф. баланса =======================
@router.callback_query(F.data.startswith("a:wok:") | F.data.startswith("a:wno:"))
async def cb_withdraw(call: CallbackQuery, bot: Bot):
    _, op, wid = call.data.split(":")
    w = db.withdrawal(int(wid))
    if not w or w["status"] != "pending":
        await mark_admin_msg(call, "ℹ️ Уже обработана")
        return await call.answer("Заявка уже обработана", show_alert=True)
    u = db.get_user(w["user_id"])
    lang = u["lang"] if u else "ru"
    if op == "wok":
        db.set_withdrawal(w["id"], "approved")
        db.add_balance(w["user_id"], w["amount"])
        await safe_send(bot, w["user_id"], t("wd_ok", lang, amount=money(w["amount"])))
        note = "✅ Одобрено, зачислено на баланс бота"
    else:
        db.set_withdrawal(w["id"], "rejected")
        db.update_user(w["user_id"], ref_balance=round(u["ref_balance"] + w["amount"], 2))
        await safe_send(bot, w["user_id"], t("wd_no", lang, amount=money(w["amount"])))
        note = "❌ Отклонено, возвращено на реф. баланс"
    await mark_admin_msg(call, f"{note} ({html.escape(call.from_user.first_name)})")
    await call.answer(note)


# ======================= поставщики =======================
async def sup_view(target, prefix=""):
    cid = db.suppliers_cid()
    items = db.q("SELECT * FROM products WHERE category_id=? ORDER BY id", (cid,))
    rows = [[B(f"{'🙈 ' if not p['active'] else ''}{p['name']} — {money(p['price'])}", f"a:p:{p['id']}")] for p in items]
    rows.append([B("➕ Добавить поставщика", "a:supadd", style="success")])
    rows.append([B("👁 Скрыть кнопку из меню" if not is_hidden("suppliers") else "👁 Показать кнопку в меню", "a:bh:suppliers")])
    rows.append(back())
    await render(target, f"{prefix}🏭 <b>Поставщики</b> — {len(items)}\n\n"
                         "Это поставщики, которых покупатели видят в главном меню по кнопке «Поставщики». "
                         "Нажмите на поставщика, чтобы изменить цену, описание или удалить.", kb(rows))


@router.callback_query(F.data == "a:sup")
async def cb_sup(call: CallbackQuery):
    await sup_view(call)
    await call.answer()


@router.callback_query(F.data == "a:supadd")
async def cb_supadd(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "np_name",
              "➕ <b>Новый поставщик</b>\n\nШаг 2/5 — отправьте <b>название</b> поставщика:" + NAME_HINT
              + "\n\n<i>Дальше бот спросит описание (контакты, условия), цену и способ выдачи — как у обычного товара.</i>",
              cancel="a:sup", cid=db.suppliers_cid())


# ======================= категории =======================
@router.callback_query(F.data == "a:cats")
async def cb_cats(call: CallbackQuery):
    await cats_view(call)
    await call.answer()


async def cats_view(call):
    rows = [[B(f"{c['name']} ({db.count_in_category(c['id'], False)})", f"a:cat:{c['id']}")] for c in db.categories()]
    rows.append([B("➕ Добавить категорию", "a:catadd", style="success")])
    rows.append(back())
    await render(call, "📁 <b>Категории каталога</b>\n\nВ скобках — количество товаров. "
                       "Число товаров в каталоге показывается автоматически.", kb(rows))


CAT_HINT = ("\n\n💎 Можно поставить <b>премиум-эмодзи</b>: просто добавьте его в начало названия — "
            "оно станет иконкой кнопки.")


@router.callback_query(F.data == "a:catadd")
async def cb_catadd(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "catadd", "📁 Отправьте название новой категории, например <code>🤖 Ai-Сервисы</code>" + CAT_HINT, cancel="a:cats")


@inp("catadd")
async def i_catadd(m, state, d, txt, bot):
    name, icon = split_custom_emoji(m)
    if not name:
        return await m.answer("Отправьте название текстом:")
    db.add_category(name[:60], icon)
    await done(m, state, f"✅ Категория «{html.escape(name)}» добавлена.", kb([back("a:cats", "◀️ К категориям")]))


@router.callback_query(F.data.startswith("a:cat:"))
async def cb_cat(call: CallbackQuery):
    cid = int(call.data.split(":")[2])
    c = db.category(cid)
    if not c:
        return await call.answer("Категория не найдена", show_alert=True)
    multi = bool(c["multi"])
    await render(call, f"📁 <b>{html.escape(c['name'])}</b>\n\nТоваров: {db.count_in_category(cid, False)}\n"
                       f"💎 Премиум-эмодзи: {'есть' if c['emoji_id'] else 'нет'}\n"
                       f"🔢 Покупка нескольких штук: {'включена' if multi else 'выключена'}",
                 kb([[B("✏️ Переименовать", f"a:catren:{cid}"), B("⬆️ Выше", f"a:catup:{cid}")],
                     [B("🔢 Несколько штук: ВКЛ ✅" if multi else "🔢 Несколько штук: ВЫКЛ", f"a:catmulti:{cid}",
                        style="success" if multi else None)],
                     [B("🗑 Удалить", f"a:catdel:{cid}", style="danger")],
                     back("a:cats")]))
    await call.answer()


@router.callback_query(F.data.startswith("a:catmulti:"))
async def cb_catmulti(call: CallbackQuery):
    cid = int(call.data.split(":")[2])
    c = db.category(cid)
    if not c:
        return await call.answer("Категория не найдена", show_alert=True)
    db.update_category(cid, multi=0 if c["multi"] else 1)
    await cb_cat(call)


@router.callback_query(F.data.startswith("a:catren:"))
async def cb_catren(call: CallbackQuery, state: FSMContext):
    cid = int(call.data.split(":")[2])
    await ask(call, state, "catren", "✏️ Отправьте новое название категории." + CAT_HINT, cancel=f"a:cat:{cid}", cid=cid)


@inp("catren")
async def i_catren(m, state, d, txt, bot):
    name, icon = split_custom_emoji(m)
    if not name:
        return await m.answer("Отправьте название текстом:")
    db.update_category(d["cid"], name=name[:60], emoji_id=icon)
    await done(m, state, "✅ Категория переименована.", kb([back("a:cats", "◀️ К категориям")]))


@router.callback_query(F.data.startswith("a:catup:"))
async def cb_catup(call: CallbackQuery):
    cid = int(call.data.split(":")[2])
    cats = list(db.categories())
    idx = next((i for i, c in enumerate(cats) if c["id"] == cid), 0)
    if idx > 0:
        cats[idx - 1], cats[idx] = cats[idx], cats[idx - 1]
        for pos, c in enumerate(cats):
            db.update_category(c["id"], position=pos)
    await cats_view(call)
    await call.answer("Перемещено")


@router.callback_query(F.data.startswith("a:catdel:"))
async def cb_catdel(call: CallbackQuery):
    cid = int(call.data.split(":")[2])
    if db.count_in_category(cid, False):
        return await call.answer("В категории есть товары — сначала перенесите или удалите их", show_alert=True)
    db.delete_category(cid)
    await cats_view(call)
    await call.answer("Категория удалена")


# ======================= промокоды =======================
@router.callback_query(F.data == "a:promos")
async def cb_promos(call: CallbackQuery):
    await promos_view(call)
    await call.answer()


async def promos_view(call):
    rows = [[B(f"{p['code']} — {p['percent']}% ({p['used']}/{p['max_uses']})", f"a:pr:{p['code']}")] for p in db.promos()]
    rows.append([B("➕ Создать промокод", "a:pradd", style="success")])
    rows.append(back())
    await render(call, "🎟 <b>Промокоды</b>\n\nВ скобках — использовано / лимит.", kb(rows))


@router.callback_query(F.data == "a:pradd")
async def cb_pradd(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "pradd", "🎟 Отправьте промокод в формате:\n<code>КОД СКИДКА% КОЛ-ВО_АКТИВАЦИЙ</code>\n\n"
                                    "Например: <code>HELIYS10 10 100</code> — скидка 10%, 100 активаций.", cancel="a:promos")


@inp("pradd")
async def i_pradd(m, state, d, txt, bot):
    parts = txt.replace("%", "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit() or not 1 <= int(parts[1]) <= 100:
        return await m.answer("Формат: <code>КОД СКИДКА КОЛ-ВО</code>, скидка от 1 до 100. Попробуйте ещё раз:")
    code = parts[0][:32]
    if not re.fullmatch(r"[\w-]+", code):
        return await m.answer("Код может содержать только буквы, цифры, _ и -:")
    db.add_promo(code, int(parts[1]), int(parts[2]))
    await state.clear()
    await show_promo(m, code, "✅ Промокод создан!\n\n")


async def show_promo(target, code, prefix=""):
    p = db.promo(code)
    if not p:
        return await render(target, "Промокод не найден.", kb([back("a:promos")]))
    await render(target, f"{prefix}🎟 <b>{html.escape(p['code'])}</b>\n\nСкидка: {p['percent']}%\n"
                         f"Использовано: {p['used']} из {p['max_uses']}",
                 kb([[B("📢 Разослать всем от имени бота", f"a:prbc:{p['code']}", style="primary")],
                     [B("🗑 Удалить", f"a:prdel:{p['code']}", style="danger")],
                     back("a:promos")]))


@router.callback_query(F.data.startswith("a:pr:"))
async def cb_promo(call: CallbackQuery):
    await show_promo(call, call.data[5:])
    await call.answer()


@router.callback_query(F.data.startswith("a:prdel:"))
async def cb_prdel(call: CallbackQuery):
    db.delete_promo(call.data[8:])
    await promos_view(call)
    await call.answer("Удалён")


@router.callback_query(F.data.startswith("a:prbc:"))
async def cb_prbc(call: CallbackQuery, bot: Bot):
    p = db.promo(call.data[7:])
    if not p:
        return await call.answer("Промокод не найден", show_alert=True)
    ids = db.all_user_ids()
    code, pct = html.escape(p["code"]), p["percent"]

    async def send(b, uid):
        u = db.get_user(uid)
        lang = u["lang"] if u else "ru"
        text = (f"🎁 <b>Новый промокод!</b>\n\n🎟 <code>{code}</code> — скидка <b>{pct}%</b>\n\n"
                f"Активируйте его в меню «Промокод» 👇") if lang == "ru" else (
                f"🎁 <b>New promo code!</b>\n\n🎟 <code>{code}</code> — <b>{pct}%</b> off\n\n"
                f"Activate it in the «Promo code» menu 👇")
        await b.send_message(uid, text, reply_markup=kb([[InlineKeyboardButton(text=bt("promo", lang), callback_data="promo")]]))

    asyncio.create_task(broadcast(bot, ids, send, call.from_user.id))
    await call.answer(f"Рассылка запущена на {len(ids)} пользователей", show_alert=True)


# ======================= оформление =======================
@router.callback_query(F.data == "a:design")
async def cb_design(call: CallbackQuery):
    rows = []
    for key, title in EDITABLE_TEXTS.items():
        rows.append([B(f"{title} RU", f"a:te:{key}:ru"), B(f"{title} EN", f"a:te:{key}:en")])
    rows += [
        [B("🖼 Фото приветствия", "a:wph")],
        [B("🔘 Кнопки (текст, премиум-эмодзи, цвет)", "a:btns:0")],
        [B("🔗 Свои кнопки в главном меню", "a:cbtns")],
        [B("👀 Предпросмотр главного меню", "menu")],
        back(),
    ]
    await render(call, "✏️ <b>Оформление</b>\n\n"
                       "Здесь можно изменить приветствие, заголовок каталога и любые кнопки бота.\n\n"
                       "💎 <b>Премиум-эмодзи</b>: просто вставьте их в текст сообщения — бот сохранит их. "
                       "Для кнопок премиум-эмодзи ставится иконкой слева от текста.\n\n"
                       "<i>Важно: премиум-эмодзи в сообщениях и кнопках бота отображаются, если у владельца бота есть Telegram Premium.</i>",
                 kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:te:"))
async def cb_text_edit(call: CallbackQuery, state: FSMContext):
    _, _, key, lang = call.data.split(":")
    cur = t(key, lang)
    await ask(call, state, "te", f"✏️ <b>{EDITABLE_TEXTS[key]} ({lang.upper()})</b>\n\nСейчас:\n\n{cur}\n\n"
                                 "Отправьте новый текст. Форматирование (жирный, курсив, ссылки) и премиум-эмодзи сохранятся.\n"
                                 "<code>-</code> — вернуть текст по умолчанию.",
              cancel="a:design", key=key, lang=lang)


@inp("te")
async def i_text_edit(m, state, d, txt, bot):
    if not txt:
        return await m.answer("Отправьте текст:")
    db.set_setting(f"t:{d['key']}:{d['lang']}", None if txt == "-" else m.html_text)
    await state.clear()
    await m.answer("✅ Сохранено. Так это выглядит:")
    await m.answer(t(d["key"], d["lang"]), reply_markup=kb([back("a:design", "◀️ К оформлению")]))


@router.callback_query(F.data == "a:wph")
async def cb_wphoto(call: CallbackQuery, state: FSMContext):
    has = "установлено" if db.get_setting("welcome_photo") else "нет"
    await ask(call, state, "wph", f"🖼 Фото приветствия: {has}\n\nОтправьте фото (или <code>-</code>, чтобы убрать).",
              cancel="a:design")


@inp("wph")
async def i_wphoto(m, state, d, txt, bot):
    if m.photo:
        db.set_setting("welcome_photo", m.photo[-1].file_id)
        await done(m, state, "✅ Фото приветствия установлено.", kb([back("a:design", "◀️ К оформлению")]))
    elif txt == "-":
        db.set_setting("welcome_photo", None)
        await done(m, state, "✅ Фото убрано.", kb([back("a:design", "◀️ К оформлению")]))
    else:
        await m.answer("Отправьте фото или <code>-</code>:")


BTN_KEYS = list(BUTTONS.keys())


@router.callback_query(F.data.startswith("a:btns:"))
async def cb_btns(call: CallbackQuery):
    page = int(call.data.split(":")[2])
    per = 10
    pages = (len(BTN_KEYS) + per - 1) // per
    page = min(max(page, 0), pages - 1)
    rows = []
    for key in BTN_KEYS[page * per:(page + 1) * per]:
        icon = "💎 " if db.get_setting(f"bi:{key}") else ""
        hid = "🙈 " if key in HIDEABLE and is_hidden(key) else ""
        rows.append([B(f"{hid}{icon}{bt(key, 'ru')}", f"a:bk:{key}")])
    rows.append(pager("a:btns:", page, pages))
    rows.append(back("a:design"))
    await render(call, "🔘 <b>Кнопки бота</b>\n\nВыберите кнопку для настройки (💎 — есть премиум-эмодзи, 🙈 — скрыта в боте).\n"
                       "Быстро скрыть сразу несколько кнопок можно в разделе «🙈 Скрыть кнопки».", kb(rows))
    await call.answer()


async def show_btn(target, key, prefix=""):
    icon = db.get_setting(f"bi:{key}")
    style = db.get_setting(f"bs:{key}", BUTTONS[key][2])
    text = (f"{prefix}🔘 <b>Кнопка «{html.escape(bt(key, 'ru'))}»</b>\n\n"
            f"🇷🇺 Текст RU: {html.escape(bt(key, 'ru'))}\n🇬🇧 Текст EN: {html.escape(bt(key, 'en'))}\n"
            f"💎 Премиум-эмодзи: {'<code>' + icon + '</code>' if icon else 'нет'}\n"
            f"🎨 Цвет: {STYLE_NAMES.get(style, style)}")
    rows = [
        [B("✏️ Текст RU", f"a:bt:{key}:ru"), B("✏️ Текст EN", f"a:bt:{key}:en")],
        [B("💎 Премиум-эмодзи", f"a:bi:{key}"), B("🎨 Цвет", f"a:bs:{key}")],
    ]
    if key in HIDEABLE:
        hid = is_hidden(key)
        text += f"\n👁 В боте: {'🙈 скрыта' if hid else 'показана'}"
        rows.append([B("👁 Показать кнопку" if hid else "🙈 Убрать кнопку из бота", f"a:bh:{key}",
                       style="success" if hid else "danger")])
    await render(target, text, kb(rows + [

        [B("♻️ Сбросить по умолчанию", f"a:br:{key}")],
        back("a:btns:0"),
    ]))


@router.callback_query(F.data.startswith("a:bh:"))
async def cb_btn_hide(call: CallbackQuery):
    key = call.data[5:]
    err = toggle_hidden(key)
    if err:
        return await call.answer(err, show_alert=True)
    await show_btn(call, key)
    await call.answer("Кнопка скрыта" if is_hidden(key) else "Кнопка снова показана")


def toggle_hidden(key):
    """Скрывает / возвращает кнопку бота. Возвращает текст ошибки, если действие запрещено."""
    if key not in HIDEABLE:
        return "Эту кнопку нельзя скрыть"
    if key in ("pay_balance", "pay_sbp") and not is_hidden(key):
        other = "pay_sbp" if key == "pay_balance" else "pay_balance"
        if is_hidden(other):
            return "Нельзя скрыть оба способа оплаты — покупатели не смогут платить"
    db.set_setting(f"bh:{key}", None if is_hidden(key) else "1")
    return None


@router.callback_query(F.data.startswith("a:bk:"))
async def cb_btn(call: CallbackQuery):
    await show_btn(call, call.data[5:])
    await call.answer()


@router.callback_query(F.data.startswith("a:bt:"))
async def cb_btn_text(call: CallbackQuery, state: FSMContext):
    _, _, key, lang = call.data.split(":")
    await ask(call, state, "bt", f"✏️ Отправьте новый текст кнопки ({lang.upper()}).\n\n"
                                 "💎 Если в начале поставить <b>премиум-эмодзи</b> — оно станет иконкой кнопки.",
              cancel=f"a:bk:{key}", key=key, lang=lang)


@inp("bt")
async def i_btn_text(m, state, d, txt, bot):
    text, icon = split_custom_emoji(m)
    if not text:
        return await m.answer("Кнопке нужен текст (кроме эмодзи). Попробуйте ещё раз:")
    db.set_setting(f"b:{d['key']}:{d['lang']}", text[:60])
    if icon:
        db.set_setting(f"bi:{d['key']}", icon)
    await state.clear()
    await show_btn(m, d["key"], "✅ Сохранено\n\n")


@router.callback_query(F.data.startswith("a:bi:"))
async def cb_btn_icon(call: CallbackQuery, state: FSMContext):
    key = call.data[5:]
    await ask(call, state, "bi", "💎 Отправьте <b>одно премиум-эмодзи</b> — оно появится слева от текста кнопки.\n"
                                 "<code>-</code> — убрать эмодзи.", cancel=f"a:bk:{key}", key=key)


@inp("bi")
async def i_btn_icon(m, state, d, txt, bot):
    if txt == "-":
        db.set_setting(f"bi:{d['key']}", None)
    else:
        _, icon = split_custom_emoji(m)
        if not icon:
            return await m.answer("Это не премиум-эмодзи. Отправьте эмодзи из премиум-набора (или <code>-</code>):")
        db.set_setting(f"bi:{d['key']}", icon)
    await state.clear()
    await show_btn(m, d["key"], "✅ Сохранено\n\n")


@router.callback_query(F.data.startswith("a:bs:"))
async def cb_btn_style(call: CallbackQuery):
    key = call.data[5:]
    cur = db.get_setting(f"bs:{key}", BUTTONS[key][2])
    nxt = STYLE_ORDER[(STYLE_ORDER.index(cur) + 1) % len(STYLE_ORDER)] if cur in STYLE_ORDER else ""
    db.set_setting(f"bs:{key}", nxt)
    await show_btn(call, key)
    await call.answer(f"Цвет: {STYLE_NAMES[nxt]}")


@router.callback_query(F.data.startswith("a:br:"))
async def cb_btn_reset(call: CallbackQuery):
    key = call.data[5:]
    for k in (f"b:{key}:ru", f"b:{key}:en", f"bi:{key}", f"bs:{key}", f"bh:{key}"):
        db.set_setting(k, None)
    await show_btn(call, key)
    await call.answer("Сброшено")


# ---------- свои кнопки главного меню ----------
@router.callback_query(F.data == "a:cbtns")
async def cb_cbtns(call: CallbackQuery):
    await cbtns_view(call)
    await call.answer()


async def cbtns_view(call):
    rows = [[B(f"🗑 {c['text']}", f"a:cbdel:{c['id']}")] for c in db.custom_buttons()]
    rows.append([B("➕ Добавить кнопку", "a:cbadd", style="success")])
    rows.append(back("a:design"))
    await render(call, "🔗 <b>Свои кнопки главного меню</b>\n\nКнопки-ссылки под приветствием. Нажмите на кнопку, чтобы удалить её.", kb(rows))


@router.callback_query(F.data == "a:cbadd")
async def cb_cbadd(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "cbadd", "🔗 Отправьте кнопку в формате:\n<code>Текст | https://ссылка</code>\n\n"
                                    "Например: <code>📢 Наш канал | https://t.me/heliys</code>\n"
                                    "💎 Премиум-эмодзи в начале текста станет иконкой кнопки.", cancel="a:cbtns")


@inp("cbadd")
async def i_cbadd(m, state, d, txt, bot):
    text, icon = split_custom_emoji(m)
    if "|" not in text:
        return await m.answer("Формат: <code>Текст | https://ссылка</code>")
    label, url = [s.strip() for s in text.split("|", 1)]
    url = fix_url(url)
    if not label or not url:
        return await m.answer("Нужен текст и ссылка: https://..., t.me/... или @username")
    db.add_custom_button(label[:60], url, icon)
    await done(m, state, "✅ Кнопка добавлена в главное меню.", kb([back("a:cbtns", "◀️ К кнопкам")]))


@router.callback_query(F.data.startswith("a:cbdel:"))
async def cb_cbdel(call: CallbackQuery):
    db.delete_custom_button(int(call.data.split(":")[2]))
    await cbtns_view(call)
    await call.answer("Кнопка удалена")


# ======================= обязательная подписка =======================
async def subs_view(target, prefix=""):
    chans = db.channels()
    on = subscription.enabled()
    lines = [f"{prefix}📣 <b>Обязательная подписка</b>\n",
             f"Статус: {'✅ включена' if on else '⏸ выключена'}\n"]
    if chans:
        lines.append("Каналы (нажмите, чтобы удалить):")
        lines += [f"• {html.escape(c['title'])} — {c['url']}" for c in chans]
    else:
        lines.append("Каналов пока нет — подписка никому не требуется.")
    lines.append("\n<i>Бот должен быть администратором в канале, иначе подписку не проверить. "
                 "Админы бота подписываться не обязаны.</i>")
    rows = [[B(f"🗑 {c['title']}", f"a:subdel:{c['id']}")] for c in chans]
    rows.append([B("➕ Добавить канал", "a:subadd", style="success")])
    rows.append([B("⏸ Выключить" if on else "▶️ Включить", "a:subtog")])
    rows.append(back())
    await render(target, "\n".join(lines), kb(rows))


@router.callback_query(F.data == "a:subs")
async def cb_subs(call: CallbackQuery):
    await subs_view(call)
    await call.answer()


@router.callback_query(F.data == "a:subtog")
async def cb_subtog(call: CallbackQuery):
    db.set_setting("sub_on", "0" if subscription.enabled() else "1")
    await subs_view(call)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("a:subdel:"))
async def cb_subdel(call: CallbackQuery):
    db.delete_channel(int(call.data.split(":")[2]))
    await subs_view(call)
    await call.answer("Канал удалён")


@router.callback_query(F.data == "a:subadd")
async def cb_subadd(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "subadd",
              "➕ <b>Добавить канал</b>\n\n1. Сделайте бота <b>администратором</b> канала.\n"
              "2. Отправьте любое из:\n"
              "• <code>@username</code> или ссылку <code>https://t.me/username</code>\n"
              "• ID канала (<code>-100...</code>)\n"
              "• или просто <b>перешлите сюда любой пост</b> из канала\n\n"
              "Для приватного канала бот сам создаст пригласительную ссылку "
              "(можно указать свою: <code>-1001234567890 | https://t.me/+AbC...</code>).",
              cancel="a:subs")


def parse_chat_ref(txt):
    """Из текста админа достаёт ссылку/ID канала и необязательную свою ссылку после '|'."""
    ref, _, link = txt.partition("|")
    ref, link = ref.strip(), link.strip()
    m = re.search(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,})", ref)
    if m and not ref.split("/")[-1].startswith("+"):
        ref = "@" + m.group(1)
    if re.fullmatch(r"-?\d+", ref):
        ref = int(ref)
    return ref, link


@inp("subadd")
async def i_subadd(m, state, d, txt, bot):
    fo = m.forward_origin
    if fo is not None and fo.type == "channel":
        ref, link = fo.chat.id, ""
    elif txt:
        ref, link = parse_chat_ref(txt)
    else:
        return await m.answer("Отправьте @username, ссылку, ID или перешлите пост из канала:")
    try:
        chat = await bot.get_chat(ref)
    except Exception as e:
        return await m.answer(f"❌ Не нашёл такой канал: {html.escape(str(e))}\n\nПроверьте и отправьте ещё раз:")
    try:
        me = await bot.get_chat_member(chat.id, (await bot.me()).id)
        if me.status not in ("administrator", "creator"):
            raise ValueError("бот не администратор")
    except Exception:
        return await m.answer("❌ Бот не является администратором этого канала. Добавьте его админом и отправьте канал снова:")
    url = link or (f"https://t.me/{chat.username}" if chat.username else "")
    if not url:
        try:
            url = (await bot.create_chat_invite_link(chat.id)).invite_link
        except Exception:
            return await m.answer("❌ Канал приватный, а бот не может создать ссылку-приглашение. "
                                  "Дайте боту право «Приглашать пользователей» или укажите ссылку: "
                                  "<code>ID | https://t.me/+...</code>")
    db.add_channel(chat.id, (chat.title or str(chat.id))[:60], url)
    subscription.forget(m.from_user.id)
    await state.clear()
    await subs_view(m, "✅ Канал добавлен.\n\n")


# ======================= настройки =======================
SETTINGS = {
    "sbp_details": ("💳 Реквизиты СБП", config.SBP_DETAILS, "Отправьте реквизиты (форматирование сохранится), например:\n<code>+79001213372 — Сбербанк</code>"),
    "reviews_url": ("⭐ Ссылка «Отзывы»", config.REVIEWS_URL, "Отправьте ссылку (https://...):"),
    "support_url": ("💬 Ссылка «Поддержка»", config.SUPPORT_URL, "Отправьте ссылку (https://...):"),
    "ref_percent": ("👥 Реферальный процент", config.REF_PERCENT, "Отправьте процент с покупок рефералов (например 10):"),
    "min_withdraw": ("💸 Минимальный вывод", config.MIN_WITHDRAW, "Отправьте минимальную сумму вывода в ₽:"),
}


@router.callback_query(F.data == "a:settings")
async def cb_settings(call: CallbackQuery):
    lines = ["⚙️ <b>Настройки</b>\n"]
    rows = []
    for key, (title, default, _) in SETTINGS.items():
        lines.append(f"{title}: {db.get_setting(key, default)}")
        rows.append([B(title, f"a:set:{key}")])
    rows.append(back())
    await render(call, "\n".join(lines), kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:set:"))
async def cb_set(call: CallbackQuery, state: FSMContext):
    key = call.data[6:]
    await ask(call, state, "set", SETTINGS[key][2], cancel="a:settings", key=key)


@inp("set")
async def i_set(m, state, d, txt, bot):
    key = d["key"]
    if key == "sbp_details":
        value = m.html_text
    elif key.endswith("_url"):
        value = fix_url(txt)
        if not value:
            return await m.answer("Не похоже на ссылку. Отправьте https://t.me/... или @username")
    else:
        v = parse_amount(txt)
        if v is None or v < 0 or (key == "ref_percent" and v > 100):
            return await m.answer("Отправьте корректное число:")
        value = int(v) if v == int(v) else v
    db.set_setting(key, value)
    await done(m, state, "✅ Сохранено.", kb([back("a:settings", "◀️ К настройкам")]))
