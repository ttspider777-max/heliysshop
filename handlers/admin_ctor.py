"""Основной бот → /admin → 🏗 Конструктор: токен бота-конструктора, запуск и остановка.

Токен хранится в базе (настройка «c:token»), а не в коде — репозиторий публичный.
Всё остальное (приветствие, кнопки, мини-приложение, цены) настраивается в самом конструкторе: /admin там.
"""
import html

from aiogram import F
from aiogram.types import CallbackQuery

import admins
import config
import hosting
from handlers.admin import B, ask, back, inp, router
from ui import kb, render


def _status():
    from ctor import bot as cbot, core
    on = cbot.running()
    name = cbot.username()
    text = ("🏗 <b>Бот-конструктор</b>\n\nЧерез него клиенты сами создают магазин — копию этого бота: выбирают цвет, "
            "стиль, заголовок, описание, приветствие и присылают токен. Магазин запускается на этом сервере.\n\n"
            f"Статус: <b>{'✅ работает' if on else '⏸ выключен'}</b>"
            + (f" · @{html.escape(name)}" if name else "")
            + f"\nТокен: <b>{'задан' if core.token() else 'не задан'}</b>")
    if on:
        text += "\n\nНастройки конструктора (приветствие, кнопки, премиум-эмодзи, мини-приложение, цена) — в самом " \
                "конструкторе: откройте его и отправьте /admin."
    rows = [[B("🔑 Задать токен" if not core.token() else "🔑 Заменить токен", "a:ctok", style="primary")]]
    if core.token():
        rows.append([B("⏸ Выключить", "a:ctoff", style="danger") if on else B("▶️ Включить", "a:cton", style="success")])
    if name:
        rows.append([B(f"🔗 Открыть @{name}", url=f"https://t.me/{name}")])
    rows.append(back())
    return text, kb(rows)


@router.callback_query(F.data == "a:ctor")
async def cb_ctor(call: CallbackQuery):
    if config.CHILD or not admins.is_owner(call.from_user.id):
        return await call.answer("Только для владельца", show_alert=True)
    text, markup = _status()
    await render(call, text, markup)
    await call.answer()


@router.callback_query(F.data == "a:ctok")
async def cb_ctor_token(call: CallbackQuery, state):
    if config.CHILD or not admins.is_owner(call.from_user.id):
        return await call.answer()
    await ask(call, state, "ctok", "🔑 Отправьте токен бота-конструктора из @BotFather (сообщение я сразу удалю).",
              cancel="a:ctor")


@inp("ctok")
async def i_ctor_token(m, state, d, txt, bot):
    from ctor import bot as cbot, core
    token = hosting.find_token(txt)
    try:
        await m.delete()
    except Exception:
        pass
    if not token:
        return await m.answer("Это не похоже на токен (<code>123456:AA...</code>). Ещё раз:")
    if token == config.BOT_TOKEN:
        return await m.answer("Это токен этого же бота — нужен токен другого бота. Ещё раз:")
    try:
        await hosting.check_token(token)
    except hosting.TokenError as e:
        return await m.answer({"invalid": "Telegram не принял токен.", "network": "Нет связи с Telegram."}
                              .get(e.code, "Токен не подошёл.") + " Ещё раз:")
    old = core.get("token")
    core.put("token", token)
    err = await cbot.start()
    if err:
        core.put("token", old)
        return await m.answer(f"❌ Конструктор не запустился: {html.escape(err)}. Пришлите другой токен:")
    await state.clear()
    text, markup = _status()
    await m.answer("✅ Конструктор запущен!\n\n" + text, reply_markup=markup)


@router.callback_query(F.data == "a:cton")
async def cb_ctor_on(call: CallbackQuery):
    from ctor import bot as cbot, core
    if not admins.is_owner(call.from_user.id):
        return await call.answer()
    core.put("off", None)
    err = await cbot.start()
    text, markup = _status()
    await render(call, (f"❌ Не запустился: {html.escape(err)}\n\n" if err else "✅ Запущен.\n\n") + text, markup)
    await call.answer()


@router.callback_query(F.data == "a:ctoff")
async def cb_ctor_off(call: CallbackQuery):
    from ctor import bot as cbot, core
    if not admins.is_owner(call.from_user.id):
        return await call.answer()
    core.put("off", "1")
    await cbot.stop()
    text, markup = _status()
    await render(call, "⏸ Выключен. Уже созданные магазины продолжают работать.\n\n" + text, markup)
    await call.answer()
