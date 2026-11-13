"""Cursed Casino — бот: меню, баланс, покупка CRX через поддержку, рефералка и команды владельца."""
import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp,
                           Message, WebAppInfo)

from . import config, engine, games, store
from .web import buy_url

router = Router()
log = logging.getLogger(__name__)

TERMS = ("ℹ️ <b>CRX</b> — внутриигровая валюта. Её нельзя вывести или обменять на деньги, "
         "игра только для развлечения. Только 18+.")


def brand():
    return html.escape(store.get("brand") or config.NAME)


def app_url():
    return f"{config.PUBLIC_URL}/app" if config.PUBLIC_URL else ""


def menu_kb(uid):
    rows = []
    if app_url():
        rows.append([InlineKeyboardButton(text="🎰 Играть", web_app=WebAppInfo(url=app_url()))])
    rows.append([InlineKeyboardButton(text="💎 Мой баланс", callback_data="bal"),
                 InlineKeyboardButton(text="🎁 Бонус", callback_data="daily")])
    second = []
    if buy_url(uid):
        second.append(InlineKeyboardButton(text="➕ Купить CRX", url=buy_url(uid)))
    second.append(InlineKeyboardButton(text="👥 Друзья", callback_data="ref"))
    rows.append(second)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def fmt(n):
    return f"{n:,}".replace(",", " ")


def welcome(u):
    return (f"🩸 <b>{brand()}</b>\n"
            f"Игры, кейсы и ежедневные бонусы. Все раунды честные: каждый можно проверить.\n\n"
            f"<blockquote>👋 {html.escape(u['name'] or 'Игрок')}\n💎 Баланс: <b>{fmt(u['balance'])} CRX</b></blockquote>\n"
            f"🕹 Краш · Мины · Плинко · Рулетка · Дайс · Лимбо · Монетка\n\n{TERMS}")


def is_owner(uid):
    return uid in config.OWNERS

# ---------------------------------------------------------------- игрок

@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject):
    ref = None
    arg = command.args or ""
    if arg.startswith("ref_") and arg[4:].isdigit():
        ref = int(arg[4:])
    u, new = store.touch(m.from_user.id, m.from_user.username, m.from_user.first_name, ref)
    if u["banned"]:
        return await m.answer("Доступ закрыт.")
    await m.answer(welcome(u), reply_markup=menu_kb(m.from_user.id))


@router.callback_query(F.data == "bal")
async def cb_bal(call: CallbackQuery):
    u, _ = store.touch(call.from_user.id, call.from_user.username, call.from_user.first_name)
    await call.answer(f"Баланс: {fmt(u['balance'])} CRX\nИгр: {u['games']}", show_alert=True)


@router.callback_query(F.data == "daily")
async def cb_daily(call: CallbackQuery):
    store.touch(call.from_user.id, call.from_user.username, call.from_user.first_name)
    try:
        r = games.daily(call.from_user.id)
    except engine.GameError as e:
        return await call.answer(str(e), show_alert=True)
    await call.answer(f"🎁 Вы получили {r['prize']} CRX!\nБаланс: {r['balance']} CRX", show_alert=True)


@router.callback_query(F.data == "ref")
async def cb_ref(call: CallbackQuery, bot: Bot):
    uid = call.from_user.id
    store.touch(uid, call.from_user.username, call.from_user.first_name)
    me = await bot.get_me()
    u = store.user(uid)
    n = store.q("SELECT COUNT(*) c FROM users WHERE ref_by=?", (uid,)).fetchone()["c"]
    pct = store.get("ref_percent")
    await call.message.answer(
        f"👥 <b>Приглашайте друзей</b>\nС каждой покупки CRX вашим другом вы получаете <b>{pct}%</b>.\n\n"
        f"Приглашено: <b>{n}</b> · заработано: <b>{u['ref_earned']} CRX</b>\n\n"
        f"Ваша ссылка:\n<code>https://t.me/{me.username}?start=ref_{uid}</code>")
    await call.answer()

# ---------------------------------------------------------------- владелец

HELP = ("🛠 <b>Команды владельца</b>\n"
        "/give <code>id|@ник сумма</code> — выдать купленные CRX (реферер получает свой %)\n"
        "/bonus <code>id|@ник сумма</code> — подарить CRX\n"
        "/take <code>id|@ник сумма</code> — списать CRX\n"
        "/user <code>id|@ник</code> — карточка игрока\n"
        "/ban, /unban <code>id|@ник</code>\n"
        "/stats — статистика\n"
        "/set <code>ключ значение</code> — настройки: rtp, start_coins, min_bet, max_bet, daily_scale, "
        "ref_percent, support, brand\n"
        "/cast <code>текст</code> — рассылка всем игрокам")
SETTABLE = {"rtp", "start_coins", "min_bet", "max_bet", "daily_scale", "ref_percent", "support", "brand"}


def _target_amount(command):
    parts = (command.args or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        raise engine.GameError("Формат: /команда id|@ник сумма")
    u = store.find(parts[0])
    if not u:
        raise engine.GameError("Игрок не найден (он должен хотя бы раз запустить бота)")
    return u, int(parts[1])


async def _notify(bot, uid, text):
    try:
        await bot.send_message(uid, text)
    except Exception:
        pass


@router.message(Command("admin"))
async def cmd_admin(m: Message):
    if is_owner(m.from_user.id):
        await m.answer(HELP)


@router.message(Command("give"))
async def cmd_give(m: Message, command: CommandObject, bot: Bot):
    if not is_owner(m.from_user.id):
        return
    try:
        u, amount = _target_amount(command)
        bal, reward = store.give(u["id"], amount, paid=True, note=f"owner {m.from_user.id}")
    except engine.GameError as e:
        return await m.answer(f"❌ {e}")
    extra = f"\nРеферер получил +{reward} CRX." if reward else ""
    await m.answer(f"✅ Выдано <b>{amount} CRX</b> → {u['id']} (@{u['username'] or '—'}). Баланс: {bal}.{extra}")
    await _notify(bot, u["id"], f"💎 Зачислено <b>{amount} CRX</b>. Баланс: <b>{bal} CRX</b>. Удачной игры!")
    if reward:
        await _notify(bot, u["ref_by"], f"👥 Ваш друг купил CRX — вам <b>+{reward} CRX</b>.")


@router.message(Command("bonus"))
async def cmd_bonus(m: Message, command: CommandObject, bot: Bot):
    if not is_owner(m.from_user.id):
        return
    try:
        u, amount = _target_amount(command)
        bal, _ = store.give(u["id"], amount, paid=False, note=f"owner {m.from_user.id}")
    except engine.GameError as e:
        return await m.answer(f"❌ {e}")
    await m.answer(f"✅ Подарено <b>{amount} CRX</b> → {u['id']}. Баланс: {bal}.")
    await _notify(bot, u["id"], f"🎁 Вам подарили <b>{amount} CRX</b>. Баланс: <b>{bal} CRX</b>.")


@router.message(Command("take"))
async def cmd_take(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id):
        return
    try:
        u, amount = _target_amount(command)
        bal = store.change(u["id"], -abs(amount), "take", f"owner {m.from_user.id}")
    except engine.GameError as e:
        return await m.answer(f"❌ {e}")
    await m.answer(f"✅ Списано {abs(amount)} CRX у {u['id']}. Баланс: {bal}.")


@router.message(Command("user"))
async def cmd_user(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id):
        return
    u = store.find(command.args or "")
    if not u:
        return await m.answer("Игрок не найден")
    await m.answer(f"👤 <b>{html.escape(u['name'] or '—')}</b> @{u['username'] or '—'} · <code>{u['id']}</code>\n"
                   f"💎 {u['balance']} CRX · игр {u['games']} · поставлено {u['wagered']} · выиграно {u['won']}\n"
                   f"🚫 бан: {'да' if u['banned'] else 'нет'}")


@router.message(Command("ban", "unban"))
async def cmd_ban(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id):
        return
    u = store.find(command.args or "")
    if not u:
        return await m.answer("Игрок не найден")
    flag = m.text.startswith("/ban")
    store.ban(u["id"], flag)
    await m.answer(f"{'🚫 Заблокирован' if flag else '✅ Разблокирован'}: {u['id']}")


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if not is_owner(m.from_user.id):
        return
    s = store.stats()
    await m.answer(f"📊 Игроков: <b>{s['n']}</b>\n💎 Всего CRX на руках: {s['bal']}\n🎲 Раундов: {s['g']}\n"
                   f"Поставлено: {s['wag']} · выиграно игроками: {s['won']}\n🛒 Продано CRX: {s['bought']}")


@router.message(Command("set"))
async def cmd_set(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id):
        return
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or parts[0] not in SETTABLE:
        return await m.answer("Формат: /set ключ значение\nКлючи: " + ", ".join(sorted(SETTABLE)))
    store.put(parts[0], parts[1].strip().lstrip("@") if parts[0] == "support" else parts[1].strip())
    await m.answer(f"✅ {parts[0]} = {parts[1]}")


@router.message(Command("cast"))
async def cmd_cast(m: Message, command: CommandObject, bot: Bot):
    if not is_owner(m.from_user.id) or not command.args:
        return
    ids = [r["id"] for r in store.q("SELECT id FROM users WHERE banned=0").fetchall()]
    ok = 0
    for uid in ids:
        try:
            await bot.send_message(uid, command.args)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await m.answer(f"📣 Доставлено {ok} из {len(ids)}")

# ---------------------------------------------------------------- запуск

async def run():
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN")
    store.connect(config.DB_PATH)
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
    await bot.delete_webhook(drop_pending_updates=True)
    site = await __import__("casino.web", fromlist=["start"]).start()
    if app_url():
        try:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Играть", web_app=WebAppInfo(url=app_url())))
        except Exception as e:
            log.warning("кнопка меню не установлена: %s", e)
    logging.info("%s запущен", config.NAME)
    try:
        await dp.start_polling(bot)
    finally:
        await site.cleanup()
