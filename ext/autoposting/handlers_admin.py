import csv
import html
import io
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
import gate
from handlers_user import send_menu, stats_text
from loader import bot

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

BUTTONS = {"app": "Открыть приложение", "support": "Поддержка", "docs": "Документы"}


class St(StatesGroup):
    find = State()
    amount = State()
    days = State()
    greeting = State()
    button = State()
    channel = State()


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


BACK = kb([("‹ В админ-панель", "adm:home")])


def _day_start() -> int:
    """Начало сегодняшнего дня по Москве (unix time)."""
    now = time.time() + config.TZ_OFFSET
    return int(now - now % 86400 - config.TZ_OFFSET)


async def panel():
    now = int(time.time())
    s = await db.one(
        "SELECT (SELECT COUNT(*) FROM users) users, (SELECT COUNT(*) FROM users WHERE sub_until > ?1) subs, "
        "(SELECT COUNT(*) FROM users WHERE created_at >= ?2) new_today, "
        "(SELECT COUNT(*) FROM accounts WHERE alive=1) accounts, "
        "(SELECT COUNT(*) FROM mailings WHERE status='active') mailings, "
        "(SELECT COALESCE(SUM(rub),0) FROM payments WHERE status='paid') rub", now, _day_start())
    today = (await db.stats_summary())["today"]
    text = (f"<b>Админ-панель · {config.APP_NAME}</b>\n\n"
            f"👥 Пользователей: <b>{s['users']}</b> (сегодня +{s['new_today']})\n"
            f"👑 С Pro: <b>{s['subs']}</b>\n"
            f"📱 Аккаунтов подключено: <b>{s['accounts']}</b>\n"
            f"📣 Активных рассылок: <b>{s['mailings']}</b>\n"
            f"✉️ Сегодня отправлено: <b>{today['sent']}</b>, кругов: {today['rounds']}\n"
            f"💰 Оплачено: <b>{s['rub']} ₽</b>")
    markup = kb(
        [("👥 Все пользователи", "adm:users:0"), ("🔍 Найти", "adm:find")],
        [("📊 Статистика", "adm:stats"), ("📥 Выгрузить .csv", "adm:csv")],
        [("📢 Обязательная подписка", "adm:chan")],
        [("✏️ Приветствие", "adm:greet"), ("🔘 Кнопки", "adm:btns")],
    )
    return text, markup


@router.message(Command("admin"))
async def admin(message: Message, state: FSMContext):
    await state.clear()
    text, markup = await panel()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = await panel()
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


def fmt_ts(ts) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.gmtime(ts + config.TZ_OFFSET)) if ts else "—"


@router.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text = stats_text(await db.stats_summary(), "📊 <b>Статистика сервиса</b>")
    top = await db.all("SELECT s.user_id, s.sent, u.username, u.first_name FROM stats_daily s "
                       "LEFT JOIN users u ON u.id=s.user_id WHERE s.day=? ORDER BY s.sent DESC LIMIT 5", db.day())
    if top:
        text += "\n\n<b>Больше всех отправили сегодня</b>\n" + "\n".join(
            f"• {html.escape(r['first_name'] or str(r['user_id']))}"
            f"{' @' + r['username'] if r['username'] else ''} — {r['sent']}" for r in top)
    await call.message.edit_text(text, reply_markup=kb([("🔄 Обновить", "adm:stats")], [("‹ В админ-панель", "adm:home")]))
    await call.answer()


# ---------- пользователи ----------

USERS_PER_PAGE = 10


@router.callback_query(F.data.startswith("adm:users:"))
async def users_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(call.data.split(":")[2])
    total = (await db.one("SELECT COUNT(*) c FROM users"))["c"]
    pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    rows = await db.all("SELECT id, username, first_name, sub_until, banned FROM users ORDER BY created_at DESC, id DESC "
                        "LIMIT ? OFFSET ?", USERS_PER_PAGE, page * USERS_PER_PAGE)
    now = time.time()
    buttons = []
    for u in rows:
        mark = "🚫 " if u["banned"] else "👑 " if u["sub_until"] > now else ""
        name = (u["first_name"] or "—")[:18]
        nick = f" @{u['username']}" if u["username"] else ""
        buttons.append([(f"{mark}{name}{nick} · {u['id']}", f"adm:u:{u['id']}")])
    nav = []
    if page > 0:
        nav.append(("‹", f"adm:users:{page - 1}"))
    nav.append((f"{page + 1} / {pages}", "adm:noop"))
    if page < pages - 1:
        nav.append(("›", f"adm:users:{page + 1}"))
    buttons += [nav, [("🔍 Найти", "adm:find"), ("📥 .csv", "adm:csv")], [("‹ В админ-панель", "adm:home")]]
    await call.message.edit_text(f"<b>👥 Пользователи — {total}</b>\n\nСначала новые. 👑 — Pro, 🚫 — забанен.",
                                 reply_markup=kb(*buttons))
    await call.answer()


@router.callback_query(F.data == "adm:noop")
async def noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data.startswith("adm:u:"))
async def user_open(call: CallbackQuery):
    text, markup = await user_card(int(call.data.split(":")[2]))
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "adm:csv")
async def users_csv(call: CallbackQuery):
    rows = await db.all(
        "SELECT u.id, u.username, u.first_name, u.is_premium, u.created_at, u.sub_until, u.balance, u.total_sent, "
        "u.referrer_id, u.banned, (SELECT COUNT(*) FROM accounts a WHERE a.user_id=u.id) accounts, "
        "(SELECT COUNT(*) FROM mailings m WHERE m.user_id=u.id AND m.status='active') active_mailings "
        "FROM users u ORDER BY u.created_at DESC")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ID", "Юзернейм", "Имя", "Telegram Premium", "Запустил бота", "Тариф", "Pro до", "Баланс hlx",
                "Отправлено всего", "Аккаунтов", "Рассылок идёт", "Пригласил (ID)", "Забанен"])
    now = time.time()
    for r in rows:
        w.writerow([r["id"], r["username"] or "", r["first_name"] or "", "да" if r["is_premium"] else "нет",
                    fmt_ts(r["created_at"]), "Pro" if r["sub_until"] > now else "Free",
                    fmt_ts(r["sub_until"]) if r["sub_until"] > now else "", r["balance"], r["total_sent"],
                    r["accounts"], r["active_mailings"], r["referrer_id"] or "", "да" if r["banned"] else "нет"])
    data = buf.getvalue().encode("utf-8-sig")   # BOM — чтобы Excel открыл кириллицу
    await call.message.answer_document(BufferedInputFile(data, f"users_{db.day()}.csv"),
                                       caption=f"👥 Пользователей: {len(rows)}")
    await call.answer()


async def user_card(user_id):
    u = await db.get_user(user_id)
    if not u:
        return "Пользователь не найден", BACK
    accs = await db.all("SELECT name, username, alive FROM accounts WHERE user_id=? ORDER BY id", user_id)
    refs = (await db.one("SELECT COUNT(*) c FROM users WHERE referrer_id=?", user_id))["c"]
    m = await db.one("SELECT COUNT(*) total, COALESCE(SUM(status='active'),0) active FROM mailings WHERE user_id=?",
                     user_id)
    st = await db.stats_summary(user_id)
    paid = (await db.one("SELECT COALESCE(SUM(rub),0) s FROM payments WHERE user_id=? AND status='paid'", user_id))["s"]
    sub = f"👑 Pro до {fmt_ts(u['sub_until'])}" if db.sub_active(u) else "Free"
    acc_lines = "\n".join(f"   • {html.escape(a['name'])}{' @' + a['username'] if a['username'] else ''}"
                          f"{'' if a['alive'] else ' (отключён)'}" for a in accs) or "   —"
    text = (f"<b>{html.escape(u['first_name'] or '—')}</b>\n\n"
            f"ID: <code>{u['id']}</code>\n"
            f"Юзернейм: {'@' + u['username'] if u['username'] else '—'}\n"
            f"Запустил бота: {fmt_ts(u['created_at'])}\n"
            f"Telegram Premium: {'да' if u['is_premium'] else 'нет'}\n"
            f"Тариф: {sub}\n"
            f"Баланс: <b>{u['balance']} hlx</b> · оплатил всего {paid} ₽\n"
            f"Пригласил его: {('<code>' + str(u['referrer_id']) + '</code>') if u['referrer_id'] else '—'}\n"
            f"Рефералов: {refs} (заработано {u['ref_earned']} hlx)\n\n"
            f"📱 Аккаунтов: {len(accs)}\n{acc_lines}\n"
            f"📣 Рассылок: {m['total']} (идёт {m['active']})\n"
            f"✉️ Отправлено сегодня: {st['today']['sent']}, кругов: {st['today']['rounds']}\n"
            f"✉️ Отправлено всего: {st['total']['sent']}\n\n"
            f"Статус: {'🚫 забанен' if u['banned'] else 'активен'}")
    markup = kb(
        [("➕ Выдать hlx", f"adm:give:{user_id}"), ("➖ Забрать hlx", f"adm:take:{user_id}")],
        [("👑 Выдать Pro", f"adm:sub:{user_id}"), ("✖️ Забрать Pro", f"adm:unsub:{user_id}")],
        [("✅ Разбанить" if u["banned"] else "🚫 Забанить", f"adm:ban:{user_id}")],
        [("‹ К пользователям", "adm:users:0"), ("‹ В админ-панель", "adm:home")],
    )
    return text, markup


@router.callback_query(F.data == "adm:find")
async def find(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.find)
    await call.message.edit_text("Отправьте ID или @юзернейм пользователя.", reply_markup=BACK)
    await call.answer()


@router.message(St.find, F.text)
async def find_input(message: Message, state: FSMContext):
    query = message.text.strip().lstrip("@")
    if query.isdigit():
        user = await db.get_user(int(query))
    else:
        user = await db.one("SELECT * FROM users WHERE username = ? COLLATE NOCASE", query)
    if not user:
        return await message.answer("Не нашёл такого пользователя. Он должен хотя бы раз запустить бота.",
                                    reply_markup=BACK)
    await state.clear()
    text, markup = await user_card(user["id"])
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:ban:"))
async def ban(call: CallbackQuery):
    user_id = int(call.data.split(":")[2])
    user = await db.get_user(user_id)
    banned = 0 if user["banned"] else 1
    await db.run("UPDATE users SET banned=? WHERE id=?", banned, user_id)
    if banned:
        await db.run("UPDATE mailings SET status='stopped' WHERE user_id=?", user_id)
    text, markup = await user_card(user_id)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer("Забанен" if banned else "Разбанен")


@router.callback_query(F.data.startswith(("adm:give:", "adm:take:")))
async def amount(call: CallbackQuery, state: FSMContext):
    _, action, user_id = call.data.split(":")
    await state.set_state(St.amount)
    await state.update_data(user_id=int(user_id), sign=1 if action == "give" else -1)
    await call.message.edit_text(f"Сколько hlx {'выдать' if action == 'give' else 'забрать'}?", reply_markup=BACK)
    await call.answer()


@router.message(St.amount, F.text)
async def amount_input(message: Message, state: FSMContext):
    if not message.text.strip().isdigit() or int(message.text) == 0:
        return await message.answer("Нужно целое число больше нуля.")
    data = await state.get_data()
    await state.clear()
    value = int(message.text) * data["sign"]
    await db.add_balance(data["user_id"], value, "admin", "Начисление администратором" if value > 0
                         else "Списание администратором")
    text, markup = await user_card(data["user_id"])
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:sub:"))
async def sub(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.days)
    await state.update_data(user_id=int(call.data.split(":")[2]))
    await call.message.edit_text("На сколько дней выдать Pro?", reply_markup=BACK)
    await call.answer()


@router.message(St.days, F.text)
async def days_input(message: Message, state: FSMContext):
    if not message.text.strip().isdigit() or not 0 < int(message.text) <= 3650:
        return await message.answer("Нужно число дней от 1 до 3650.")
    data = await state.get_data()
    await state.clear()
    await db.add_sub_days(data["user_id"], int(message.text))
    text, markup = await user_card(data["user_id"])
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:unsub:"))
async def unsub(call: CallbackQuery):
    user_id = int(call.data.split(":")[2])
    await db.run("UPDATE users SET sub_until=0 WHERE id=?", user_id)
    text, markup = await user_card(user_id)
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer("Pro снят")


# ---------- обязательная подписка ----------

async def channels_view():
    channels = await db.all("SELECT * FROM channels")
    lines = [f"• {html.escape(c['title'])}" for c in channels] or ["Каналов нет — проверка выключена."]
    rows = [[(f"🗑 {c['title'][:30]}", f"adm:chan_del:{c['chat_id']}")] for c in channels]
    rows += [[("➕ Добавить канал", "adm:chan_add")], [("‹ В админ-панель", "adm:home")]]
    return "<b>Обязательная подписка</b>\n\n" + "\n".join(lines), kb(*rows)


@router.callback_query(F.data == "adm:chan")
async def chan(call: CallbackQuery, state: FSMContext):
    await state.clear()
    text, markup = await channels_view()
    await call.message.edit_text(text, reply_markup=markup)
    await call.answer()


@router.callback_query(F.data == "adm:chan_add")
async def chan_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.channel)
    await call.message.edit_text(
        "Сначала добавьте бота администратором в канал, затем отправьте сюда @юзернейм канала "
        "или перешлите из него любой пост.", reply_markup=BACK)
    await call.answer()


@router.message(St.channel)
async def chan_input(message: Message, state: FSMContext):
    if message.forward_from_chat:
        ref = message.forward_from_chat.id
    elif message.text:
        ref = message.text.strip()
        ref = int(ref) if ref.lstrip("-").isdigit() else "@" + ref.split("/")[-1].lstrip("@")
    else:
        return await message.answer("Отправьте @юзернейм или перешлите пост из канала.")
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status != "administrator":
            raise ValueError
        url = f"https://t.me/{chat.username}" if chat.username else \
            (chat.invite_link or (await bot.create_chat_invite_link(chat.id)).invite_link)
    except Exception:
        return await message.answer("Не получилось: бот должен быть администратором этого канала "
                                    "с правом приглашать пользователей.", reply_markup=BACK)
    await db.run("INSERT OR REPLACE INTO channels(chat_id, title, url) VALUES(?,?,?)", chat.id, chat.title, url)
    gate.reset_cache()
    await state.clear()
    text, markup = await channels_view()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:chan_del:"))
async def chan_del(call: CallbackQuery, state: FSMContext):
    await db.run("DELETE FROM channels WHERE chat_id=?", int(call.data.split(":")[2]))
    await chan(call, state)


# ---------- приветствие ----------

@router.callback_query(F.data == "adm:greet")
async def greet(call: CallbackQuery, state: FSMContext):
    await state.set_state(St.greeting)
    await call.message.edit_text(
        "Отправьте новый текст приветствия. Форматирование и премиум-эмодзи сохранятся.\n"
        "<code>{name}</code> заменится на имя пользователя.",
        reply_markup=kb([("↺ Сбросить на стандартное", "adm:greet_reset")], [("‹ В админ-панель", "adm:home")]))
    await call.answer()


@router.callback_query(F.data == "adm:greet_reset")
async def greet_reset(call: CallbackQuery, state: FSMContext):
    await db.reset_setting("greeting")
    await home(call, state)


@router.message(St.greeting, F.text)
async def greet_input(message: Message, state: FSMContext):
    await db.set_setting("greeting", message.html_text)
    await state.clear()
    await message.answer("Сохранено. Так это увидят пользователи:")
    await send_menu(message, message.from_user.first_name)


# ---------- кнопки ----------

@router.callback_query(F.data == "adm:btns")
async def btns(call: CallbackQuery, state: FSMContext):
    await state.clear()
    settings = await db.get_settings()
    rows = [[(f"{'✨ ' if settings[f'btn_{k}_emoji'] else ''}{settings[f'btn_{k}_text']}", f"adm:btn:{k}")]
            for k in BUTTONS]
    await call.message.edit_text("Какую кнопку главного меню изменить?",
                                 reply_markup=kb(*rows, [("‹ В админ-панель", "adm:home")]))
    await call.answer()


@router.callback_query(F.data.startswith("adm:btn:"))
async def btn(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[2]
    await state.set_state(St.button)
    await state.update_data(key=key)
    await call.message.edit_text(
        f"Кнопка «{BUTTONS[key]}».\n\nОтправьте новый текст. Если поставить премиум-эмодзи в самое начало, "
        "он станет иконкой кнопки.",
        reply_markup=kb([("↺ Сбросить", f"adm:btn_reset:{key}")], [("‹ Назад", "adm:btns")]))
    await call.answer()


@router.callback_query(F.data.startswith("adm:btn_reset:"))
async def btn_reset(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[2]
    await db.reset_setting(f"btn_{key}_text")
    await db.reset_setting(f"btn_{key}_emoji")
    await btns(call, state)


@router.message(St.button, F.text)
async def btn_input(message: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    text, emoji_id = message.text, ""
    lead = next((e for e in message.entities or [] if e.type == "custom_emoji" and e.offset == 0), None)
    if lead:
        emoji_id = lead.custom_emoji_id
        text = text[len(lead.extract_from(text)):]
    text = text.strip()
    if not text or len(text) > 60:
        return await message.answer("Текст кнопки должен быть от 1 до 60 символов.")
    await db.set_setting(f"btn_{key}_text", text)
    await db.set_setting(f"btn_{key}_emoji", emoji_id)
    await state.clear()
    await message.answer("Сохранено. Так это увидят пользователи:")
    await send_menu(message, message.from_user.first_name)
