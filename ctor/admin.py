"""Админ-панель конструктора (/admin в боте-конструкторе, только владельцы — config.ADMINS).

👋 приветствие (текст с премиум-эмодзи + фото/видео) · 🔘 кнопки (текст, премиум-эмодзи, цвет) · 📝 тексты бота
· 📱 мини-приложение (тексты с премиум-эмодзи, иконки, цвет, стиль, фон) · 💰 цена и пробный · 💳 реквизиты
· 🤖 магазины клиентов · 👥 пользователи и баланс · 📢 рассылка · чеки пополнения (✅ / ❌).
"""
import asyncio
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import appcfg
import config
import db
import hosting
from ctor import core
from ctor.core import money
from handlers.admin import mark_admin_msg
from services import broadcast
from ui import fix_url, kb, media_of, raw_btn, render, split_custom_emoji

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMINS))
router.callback_query.filter(F.from_user.id.in_(config.ADMINS))

_wait = {}  # id админа -> {"act": ..., ...}: чего ждём следующим сообщением


def B(text, cb=None, url=None, style=None, web_app=None):
    return raw_btn(text, cb, url, style=style, web_app=web_app)


def back(cb="ca:home", text="◀️ Назад"):
    return [B(text, cb)]


async def ask(call: CallbackQuery, act, prompt, cancel="ca:home", **extra):
    _wait[call.from_user.id] = {"act": act, "cancel": cancel, **extra}
    await render(call, prompt, kb([[B("❌ Отмена", f"ca:x:{cancel}", style="danger")]]))
    await call.answer()


@router.callback_query(F.data.startswith("ca:x:"))
async def cb_cancel(call: CallbackQuery):
    _wait.pop(call.from_user.id, None)
    await route_back(call, call.data[5:])
    await call.answer()


async def route_back(call: CallbackQuery, target):
    """Возврат на экран, с которого начали ввод."""
    if target.startswith("ca:b:"):
        return await btn_view(call, target[5:])
    if target.startswith("ca:t:"):
        return await text_view(call, target[5:])
    if target == "ca:app":
        return await app_view(call)
    if target == "ca:wel":
        return await welcome_view(call)
    if target == "ca:usr":
        return await users_view(call)
    if target.startswith("ca:ic:"):
        return await icon_view(call, target[6:])
    await home(call)


# ======================= главная =======================
def stats():
    users = db.val("SELECT COUNT(*) FROM ctor_users") or 0
    today = db.val("SELECT COUNT(*) FROM ctor_users WHERE joined >= date('now','localtime')") or 0
    bots = db.val("SELECT COUNT(*) FROM hosted_bots WHERE source='ctor' AND status NOT IN ('canceled','deleted')") or 0
    run = db.val("SELECT COUNT(*) FROM hosted_bots WHERE source='ctor' AND status='running'") or 0
    trials = db.val("SELECT COUNT(*) FROM hosted_bots WHERE source='ctor' AND trial_until IS NOT NULL "
                    "AND status='running'") or 0
    bal = db.val("SELECT COALESCE(SUM(balance),0) FROM ctor_users") or 0
    topped = db.val("SELECT COALESCE(SUM(amount),0) FROM ctor_topups WHERE status='done'") or 0
    pending = db.val("SELECT COUNT(*) FROM ctor_topups WHERE status='pending'") or 0
    return users, today, bots, run, trials, bal, topped, pending


async def home(target, prefix=""):
    users, today, bots, run, trials, bal, topped, pending = stats()
    from ctor import bot as cbot
    text = (f"{prefix}⚙️ <b>Админ-панель конструктора</b> @{html.escape(cbot.username() or '?')}\n\n<blockquote>"
            f"👥 Пользователей: <b>{users}</b> (+{today} сегодня)\n"
            f"🤖 Магазинов: <b>{bots}</b> · работает {run} · на пробном {trials}\n"
            f"💳 Пополнено: <b>{money(topped)}</b> · на балансах {money(bal)}\n"
            f"🔎 Чеков на проверке: <b>{pending}</b></blockquote>\n\n"
            f"💰 Цена бота: <b>{money(core.price())}</b> · 🎁 Пробный: <b>{core.trial_days() or 'выкл'}</b>"
            f"{' дн.' if core.trial_days() else ''}")
    if not cbot.app_url():
        text += ("\n\n⚠️ <i>Мини-приложение недоступно: не задан https-адрес сайта. На BotHost включите "
                 "«Использовать домен» (порт 8080) и вставьте выданный адрес кнопкой «🌐 Адрес сайта». "
                 "Пока создание идёт кнопками в чате.</i>")
    await render(target, text, kb([
        [B("👋 Приветствие", "ca:wel"), B("🔘 Кнопки", "ca:btns")],
        [B("📝 Тексты бота", "ca:txl:0"), B("📱 Мини-приложение", "ca:app", style="primary")],
        [B("💰 Цена", "ca:v:price"), B("🎁 Пробный период", "ca:v:trial_days")],
        [B("💳 Реквизиты СБП", "ca:v:sbp"), B("💬 Поддержка", "ca:v:support_url")],
        [B("💵 Мин. пополнение", "ca:v:topup_min"), B("🌐 Адрес сайта", "ca:v:site")],
        [B("👨‍💼 Куратор", "ca:v:curator")],
        [B("🤖 Магазины клиентов", "ca:hb:0", style="success")],
        [B("👥 Пользователи и баланс", "ca:usr"), B("📢 Рассылка", "ca:bc")],
        [B(f"📣 Обязательная подписка ({len(db.channels())})", "ca:subs")],
        [B("🏠 Меню конструктора", "c:menu")],
    ]))


@router.message(Command("admin"))
async def cmd_admin(m: Message):
    _wait.pop(m.from_user.id, None)
    await home(m)


@router.callback_query(F.data == "ca:home")
async def cb_home(call: CallbackQuery):
    _wait.pop(call.from_user.id, None)
    await home(call)
    await call.answer()


# ======================= приветствие =======================
async def welcome_view(target, prefix=""):
    media = core.get("welcome_media")
    text = (f"{prefix}👋 <b>Приветствие конструктора</b>\n\nМедиа: <b>{'есть' if media else 'нет'}</b> · "
            f"текст: <b>{'свой' if core.get('t:welcome') else 'стандартный'}</b>\n\n"
            "Ниже — как его видит пользователь. Чтобы изменить, нажмите «✏️ Изменить» и пришлите сообщение: "
            "текст с форматированием и <b>премиум-эмодзи</b>, можно с фото, видео или GIF.\n\n"
            "<blockquote>Подстановки: <code>{name}</code> имя · <code>{balance}</code> баланс · <code>{bots}</code> "
            "сколько ботов · <code>{trial}</code> строка про пробный/цену · <code>{price}</code> цена · "
            "<code>{days}</code> дней пробного</blockquote>")
    rows = [[B("✏️ Изменить", "ca:welset", style="primary")], [B("👀 Показать", "ca:welpv")]]
    if media:
        rows.append([B("🗑 Убрать медиа", "ca:welnomedia", style="danger")])
    if core.get("t:welcome"):
        rows.append([B("↩️ Стандартный текст", "ca:welreset")])
    rows.append(back())
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca:wel")
async def cb_welcome(call: CallbackQuery):
    await welcome_view(call)
    await call.answer()


@router.callback_query(F.data == "ca:welpv")
async def cb_welcome_preview(call: CallbackQuery):
    from ctor import bot as cbot
    await cbot.out(call.from_user.id, cbot.welcome_text(call.from_user.id), cbot.menu_kb(call.from_user.id),
                   photo=cbot.as_media(core.get("welcome_media")))
    await call.answer()


@router.callback_query(F.data == "ca:welset")
async def cb_welcome_set(call: CallbackQuery):
    await ask(call, "welcome", "👋 Пришлите новое приветствие одним сообщением (текст + по желанию фото/видео/GIF). "
                               "Премиум-эмодзи и форматирование сохранятся.\n\n"
                               "Пришлёте только фото без подписи — текст останется прежним.", cancel="ca:wel")


@router.callback_query(F.data == "ca:welnomedia")
async def cb_welcome_nomedia(call: CallbackQuery):
    core.put("welcome_media", None)
    await welcome_view(call, "🗑 Медиа убрано.\n\n")
    await call.answer()


@router.callback_query(F.data == "ca:welreset")
async def cb_welcome_reset(call: CallbackQuery):
    core.put("t:welcome", None)
    await welcome_view(call, "↩️ Текст стандартный.\n\n")
    await call.answer()


# ======================= кнопки =======================
@router.callback_query(F.data == "ca:btns")
async def cb_buttons(call: CallbackQuery):
    rows = []
    items = list(core.BUTTONS.items())
    for i in range(0, len(items), 2):
        rows.append([B(("✨ " if core.bicon(k) else "") + core.plain(core.bt(k))[:28], f"ca:b:{k}")
                     for k, _ in items[i:i + 2]])
    rows.append(back())
    await render(call, "🔘 <b>Кнопки конструктора</b>\n\nВыберите кнопку — можно поменять текст, поставить "
                       "<b>премиум-эмодзи</b> и цвет. ✨ — у кнопки стоит премиум-эмодзи.", kb(rows))
    await call.answer()


async def btn_view(target, key, prefix=""):
    name, default, _ = core.BUTTONS[key]
    icon = core.bicon(key)
    style = core.bstyle(key) or ""
    icon_txt = f'<tg-emoji emoji-id="{icon}">⭐</tg-emoji> есть' if icon else "нет"
    text = (f"{prefix}🔘 <b>Кнопка «{html.escape(name)}»</b>\n\n<blockquote>Текст: {html.escape(core.bt(key))}\n"
            f"Стандартный: {html.escape(default)}\n"
            f"Премиум-эмодзи: {icon_txt}\n"
            f"Цвет: {core.STYLES.get(style, style)}</blockquote>\n\nПример ниже 👇")
    rows = [[raw_btn(core.bt(key), "ca:noop", icon=icon, style=core.bstyle(key))],
            [B("✏️ Текст", f"ca:bt:{key}"), B("✨ Премиум-эмодзи", f"ca:bi:{key}")],
            [B(f"🎨 Цвет: {core.STYLES.get(style, style)}", f"ca:bs:{key}")]]
    if icon:
        rows.append([B("🗑 Убрать премиум-эмодзи", f"ca:bix:{key}", style="danger")])
    if core.get("b:" + key) or core.get("bs:" + key) is not None:
        rows.append([B("↩️ Сбросить текст и цвет", f"ca:br:{key}")])
    rows.append(back("ca:btns", "◀️ К кнопкам"))
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca:noop")
async def cb_noop(call: CallbackQuery):
    await call.answer("Это пример кнопки")


@router.callback_query(F.data.startswith("ca:b:"))
async def cb_btn(call: CallbackQuery):
    key = call.data[5:]
    if key not in core.BUTTONS:
        return await call.answer()
    await btn_view(call, key)
    await call.answer()


@router.callback_query(F.data.startswith("ca:bt:"))
async def cb_btn_text(call: CallbackQuery):
    key = call.data[6:]
    await ask(call, "btext", f"✏️ Пришлите новый текст кнопки (до 60 символов).\n\nЕсли в тексте будет "
                             "<b>премиум-эмодзи</b> — оно станет иконкой кнопки.", cancel=f"ca:b:{key}", key=key)


@router.callback_query(F.data.startswith("ca:bi:"))
async def cb_btn_icon(call: CallbackQuery):
    key = call.data[6:]
    await ask(call, "bicon", "✨ Пришлите одно <b>премиум-эмодзи</b> — оно встанет на кнопку вместо обычного.",
              cancel=f"ca:b:{key}", key=key)


@router.callback_query(F.data.startswith("ca:bix:"))
async def cb_btn_icon_del(call: CallbackQuery):
    key = call.data[7:]
    core.put("bi:" + key, None)
    await btn_view(call, key, "🗑 Премиум-эмодзи убрано.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca:bs:"))
async def cb_btn_style(call: CallbackQuery):
    key = call.data[6:]
    order = list(core.STYLES)
    cur = core.bstyle(key) or ""
    core.put("bs:" + key, order[(order.index(cur) + 1) % len(order)] if cur in order else "")
    await btn_view(call, key)
    await call.answer()


@router.callback_query(F.data.startswith("ca:br:"))
async def cb_btn_reset(call: CallbackQuery):
    key = call.data[6:]
    core.put("b:" + key, None)
    core.put("bs:" + key, None)
    await btn_view(call, key, "↩️ Сброшено.\n\n")
    await call.answer()


# ======================= тексты =======================
BOT_KEYS = [k for k in core.TEXTS if not k.startswith("app_") and k != "welcome"]
APP_KEYS = list(core.APP_TEXTS)
PAGE = 8


def _text_list(keys, page, prefix_cb, back_cb, title):
    pages = max((len(keys) + PAGE - 1) // PAGE, 1)
    page = min(max(page, 0), pages - 1)
    rows = [[B(("✏️ " if core.get("t:" + k) is not None else "") + core.TEXTS[k][0][:40], f"ca:t:{k}")]
            for k in keys[page * PAGE:(page + 1) * PAGE]]
    nav = []
    if page > 0:
        nav.append(B("◀️", f"{prefix_cb}{page - 1}"))
    if pages > 1:
        nav.append(B(f"{page + 1}/{pages}", "ca:noop"))
    if page < pages - 1:
        nav.append(B("▶️", f"{prefix_cb}{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(back(back_cb))
    return f"{title}\n\n✏️ — текст изменён. Везде можно вставлять <b>премиум-эмодзи</b>.", kb(rows)


@router.callback_query(F.data.startswith("ca:txl:"))
async def cb_texts(call: CallbackQuery):
    text, markup = _text_list(BOT_KEYS, int(call.data[7:]), "ca:txl:", "ca:home", "📝 <b>Тексты бота-конструктора</b>")
    await render(call, text, markup)
    await call.answer()


@router.callback_query(F.data.startswith("ca:atx:"))
async def cb_app_texts(call: CallbackQuery):
    text, markup = _text_list(APP_KEYS, int(call.data[7:]), "ca:atx:", "ca:app", "📝 <b>Тексты мини-приложения</b>")
    await render(call, text, markup)
    await call.answer()


async def text_view(target, key, prefix=""):
    name, default = core.TEXTS[key]
    own = core.get("t:" + key)
    is_app = key.startswith("app_")
    text = (f"{prefix}📝 <b>{html.escape(name)}</b>\n\n<b>Сейчас:</b>\n{own if own is not None else default}\n\n"
            + ("" if own is None else f"<b>Стандартный:</b>\n{default}\n\n")
            + "Нажмите «✏️ Изменить» и пришлите новый текст (форматирование и премиум-эмодзи сохранятся). "
              "Слова в фигурных скобках вроде <code>{price}</code> подставляются автоматически — оставьте их.")
    rows = [[B("✏️ Изменить", f"ca:te:{key}", style="primary")]]
    if own is not None:
        rows.append([B("↩️ Вернуть стандартный", f"ca:tr:{key}")])
    rows.append(back("ca:atx:0" if is_app else "ca:txl:0"))
    try:
        await render(target, text, kb(rows))
    except Exception:  # сломанный HTML в старом тексте — показываем без разметки
        await render(target, html.escape(core.plain(text)), kb(rows))


@router.callback_query(F.data.startswith("ca:t:"))
async def cb_text(call: CallbackQuery):
    key = call.data[5:]
    if key not in core.TEXTS:
        return await call.answer()
    await text_view(call, key)
    await call.answer()


@router.callback_query(F.data.startswith("ca:te:"))
async def cb_text_edit(call: CallbackQuery):
    key = call.data[6:]
    await ask(call, "text", f"✏️ Пришлите новый текст для «{html.escape(core.TEXTS[key][0])}».",
              cancel=f"ca:t:{key}", key=key)


@router.callback_query(F.data.startswith("ca:tr:"))
async def cb_text_reset(call: CallbackQuery):
    key = call.data[6:]
    core.put("t:" + key, None)
    await text_view(call, key, "↩️ Вернул стандартный.\n\n")
    await call.answer()


# ======================= мини-приложение =======================
async def app_view(target, prefix=""):
    from ctor import bot as cbot
    url = cbot.app_url()
    season = core.get("app_season", "none")
    text = (f"{prefix}📱 <b>Мини-приложение конструктора</b>\n\n<blockquote>"
            f"🎨 Цвет: <code>{html.escape(core.get('app_accent') or '#8b5cf6')}</code>\n"
            f"🎭 Стиль: {appcfg.SEASONS.get(season, appcfg.SEASONS['none'])[0]}\n"
            f"🖼 Фон карточки: {'есть' if core.get('app_bg') else 'нет'}\n"
            f"🔗 Адрес: {html.escape(url or 'нет (нужен https-адрес сайта в основном боте)')}</blockquote>\n\n"
            "Тексты и иконки мини-приложения поддерживают <b>премиум-эмодзи</b> — в приложении они анимированные.")
    rows = [
        [B("📝 Тексты", "ca:atx:0", style="primary"), B("💎 Иконки", "ca:icl")],
        [B("🎨 Цвет", "ca:v:app_accent"), B("🎭 Стиль", "ca:asty")],
        [B("🖼 Фон карточки", "ca:abg")],
    ]
    if core.get("app_bg"):
        rows.append([B("🗑 Убрать фон", "ca:abgx", style="danger")])
    if url:
        rows.append([B("👀 Открыть мини-приложение", web_app=url, style="success")])
    rows.append(back())
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca:app")
async def cb_app(call: CallbackQuery):
    await app_view(call)
    await call.answer()


@router.callback_query(F.data == "ca:asty")
async def cb_app_style(call: CallbackQuery):
    items = list(appcfg.SEASONS.items())
    rows = [[B(v[0], f"ca:asty:{k}") for k, v in items[i:i + 2]] for i in range(0, len(items), 2)]
    rows.append(back("ca:app"))
    await render(call, "🎭 <b>Стиль мини-приложения конструктора</b> — анимация и значок на карточке:", kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("ca:asty:"))
async def cb_app_style_set(call: CallbackQuery):
    key = call.data[8:]
    if key in appcfg.SEASONS:
        core.put("app_season", key)
    await app_view(call, "✅ Стиль сохранён.\n\n")
    await call.answer()


@router.callback_query(F.data == "ca:abg")
async def cb_app_bg(call: CallbackQuery):
    await ask(call, "appbg", "🖼 Пришлите фото или видео для фона главной карточки мини-приложения.", cancel="ca:app")


@router.callback_query(F.data == "ca:abgx")
async def cb_app_bg_del(call: CallbackQuery):
    core.put("app_bg", None)
    await app_view(call, "🗑 Фон убран.\n\n")
    await call.answer()


@router.callback_query(F.data == "ca:icl")
async def cb_icons(call: CallbackQuery):
    rows = [[B(("✨ " if core.get("ai:" + k) else d + " ") + n, f"ca:ic:{k}")]
            for k, (n, d) in core.ICON_SLOTS.items()]
    rows.append(back("ca:app"))
    await render(call, "💎 <b>Иконки мини-приложения</b>\n\nВыберите место и пришлите премиум-эмодзи. "
                       "✨ — уже стоит премиум-эмодзи.", kb(rows))
    await call.answer()


async def icon_view(target, slot, prefix=""):
    name, default = core.ICON_SLOTS[slot]
    eid = core.get("ai:" + slot)
    text = (f"{prefix}💎 <b>{html.escape(name)}</b>\n\nСейчас: "
            + (f'<tg-emoji emoji-id="{eid}">{default}</tg-emoji> (премиум)' if eid else f"{default} (обычное)"))
    rows = [[B("✨ Поставить премиум-эмодзи", f"ca:ics:{slot}", style="primary")]]
    if eid:
        rows.append([B("🗑 Убрать", f"ca:icx:{slot}", style="danger")])
    rows.append(back("ca:icl", "◀️ К иконкам"))
    await render(target, text, kb(rows))


@router.callback_query(F.data.startswith("ca:ic:"))
async def cb_icon(call: CallbackQuery):
    slot = call.data[6:]
    if slot not in core.ICON_SLOTS:
        return await call.answer()
    await icon_view(call, slot)
    await call.answer()


@router.callback_query(F.data.startswith("ca:ics:"))
async def cb_icon_set(call: CallbackQuery):
    slot = call.data[7:]
    await ask(call, "icon", "✨ Пришлите одно премиум-эмодзи.", cancel=f"ca:ic:{slot}", slot=slot)


@router.callback_query(F.data.startswith("ca:icx:"))
async def cb_icon_del(call: CallbackQuery):
    slot = call.data[7:]
    core.put("ai:" + slot, None)
    await icon_view(call, slot, "🗑 Убрано.\n\n")
    await call.answer()


# ======================= значения =======================
VALUES = {
    "price": ("💰 Цена бота", "Отправьте цену создания бота в рублях (например <code>300</code>). "
                              "<code>0</code> — бесплатно."),
    "trial_days": ("🎁 Пробный период", "Сколько дней бот работает бесплатно? Отправьте число "
                                        "(<code>3</code>). <code>0</code> — без пробного периода."),
    "sbp": ("💳 Реквизиты СБП", "Отправьте реквизиты для пополнения баланса (например "
                               "<code>+79990000000</code> — Т-Банк). Можно с форматированием. "
                               "<code>-</code> — как в основном боте."),
    "support_url": ("💬 Поддержка", "Отправьте ссылку или @username поддержки конструктора. "
                                   "<code>-</code> — как в основном боте."),
    "curator": ("👨‍💼 Куратор", "Отправьте @username или ссылку куратора — после создания магазина бот напишет "
                               "владельцу «Напиши своему куратору» с этой ссылкой. <code>-</code> — как поддержка.\n\n"
                               "Текст сообщения меняется в «📝 Тексты бота» → «Сообщение о кураторе»."),
    "topup_min": ("💵 Мин. пополнение", "Минимальная сумма пополнения в рублях (например <code>50</code>)."),
    "site": ("🌐 Адрес сайта", "Отправьте https-адрес, который BotHost выдал этому боту (например "
                              "<code>https://bot-123-heliys.bothost.tech</code>). Без него мини-приложение не откроется."),
    "app_accent": ("🎨 Цвет мини-приложения", "Отправьте цвет в формате <code>#8b5cf6</code>. "
                                             "<code>-</code> — стандартный."),
}


@router.callback_query(F.data.startswith("ca:v:"))
async def cb_value(call: CallbackQuery):
    key = call.data[5:]
    if key not in VALUES:
        return await call.answer()
    name, prompt = VALUES[key]
    cur = {"price": money(core.price()), "trial_days": core.trial_days(), "sbp": core.sbp(),
           "support_url": html.escape(core.support_url() or "—"), "topup_min": money(core.topup_min()),
           "curator": html.escape(core.curator() or "—"),
           "app_accent": core.get("app_accent") or "#8b5cf6",
           "site": html.escape(appcfg.public_url() or "не задан")}[key]
    await ask(call, "value", f"<b>{name}</b>\n\nСейчас: {cur}\n\n{prompt}",
              cancel="ca:app" if key == "app_accent" else "ca:home", key=key)


# ======================= магазины клиентов =======================
@router.callback_query(F.data.startswith("ca:hb:"))
async def cb_bots(call: CallbackQuery):
    page = int(call.data[6:] or 0)
    bots = db.q("SELECT * FROM hosted_bots WHERE source='ctor' AND status NOT IN ('canceled','deleted') "
                "ORDER BY id DESC")
    per = 10
    pages = max((len(bots) + per - 1) // per, 1)
    page = min(max(page, 0), pages - 1)
    from ctor.bot import STATUS_ICON
    rows = [[B(f"{STATUS_ICON.get(b['status'], '•')} #{b['id']} @{b['username'] or '—'}"
               + (" 🎁" if b["trial_until"] else ""), f"ca:hv:{b['id']}")]
            for b in bots[page * per:(page + 1) * per]]
    nav = []
    if page > 0:
        nav.append(B("◀️", f"ca:hb:{page - 1}"))
    if pages > 1:
        nav.append(B(f"{page + 1}/{pages}", "ca:noop"))
    if page < pages - 1:
        nav.append(B("▶️", f"ca:hb:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append(back())
    await render(call, f"🤖 <b>Магазины, созданные через конструктор</b> ({len(bots)})\n\n"
                       "✅ работает · ⏸ остановлен · ⚠️ упал · ⌛ пробный закончился · 🎁 на пробном\n\n"
                       "<i>Полное управление (лог, база, статистика) — в основном боте: /admin → 🤖 Боты клиентов.</i>"
                       + ("" if bots else "\n\nПока никто не создал магазин."), kb(rows))
    await call.answer()


async def bot_view(target, bid, prefix=""):
    from handlers import builder
    b = db.hosted(bid)
    if not b:
        return await render(target, "Не найден.", kb([back("ca:hb:0")]))
    u = core.user(b["user_id"])
    text = (f"{prefix}🤖 <b>Магазин #{b['id']}</b> @{html.escape(b['username'] or '—')}\n\n"
            f"👤 Владелец: {core.user_link(u) if u else b['user_id']}\n"
            f"📍 Статус: {b['status']}{' (процесс работает)' if hosting.is_alive(b['id']) else ''}\n"
            + (f"🎁 Пробный до {builder.fmt_until(b['trial_until'])}\n" if b["trial_until"]
               else f"♾ Навсегда · оплачено {money(b['price'])}\n")
            + f"📅 Создан: {b['created']}")
    rows = []
    if b["status"] == "running":
        rows.append([B("⏸ Остановить", f"ca:hs:{bid}", style="danger"), B("🔄 Перезапустить", f"ca:hr:{bid}")])
    elif b["status"] in ("stopped", "failed") and b["token"]:
        rows.append([B("▶️ Запустить", f"ca:hr:{bid}", style="success")])
    if b["trial_until"] and b["token"]:
        rows.append([B(f"🎁 +{core.trial_days() or 3} дн.", f"ca:hx:{bid}"),
                     B("♾ Навсегда", f"ca:hp:{bid}", style="success")])
    if b["username"]:
        rows.append([B(f"🔗 @{b['username']} (/admin)", url=f"https://t.me/{b['username']}", style="primary")])
    rows.append(back("ca:hb:0", "◀️ К списку"))
    await render(target, text, kb(rows))


@router.callback_query(F.data.startswith("ca:hv:"))
async def cb_bot(call: CallbackQuery):
    await bot_view(call, int(call.data[6:]))
    await call.answer()


@router.callback_query(F.data.startswith("ca:hs:"))
async def cb_bot_stop(call: CallbackQuery):
    bid = int(call.data[6:])
    db.set_hosted(bid, status="stopped")
    await hosting.stop(bid)
    await bot_view(call, bid, "⏸ Остановлен.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca:hr:"))
async def cb_bot_run(call: CallbackQuery):
    bid = int(call.data[6:])
    b = db.hosted(bid)
    if not b or not b["token"]:
        return await call.answer("Нет токена", show_alert=True)
    await call.answer("Запускаю…")
    db.set_hosted(bid, status="running")
    ok = await (hosting.restart(bid) if hosting.is_alive(bid) else hosting.launch(bid))
    await bot_view(call, bid, "✅ Работает.\n\n" if ok else "⚠️ Не запустился — лог в основном боте.\n\n")


@router.callback_query(F.data.startswith("ca:hx:"))
async def cb_bot_extend(call: CallbackQuery):
    from handlers import builder
    from ctor import bot as cbot
    bid = int(call.data[6:])
    b = db.hosted(bid)
    if not b or not b["trial_until"]:
        return await call.answer("Уже не пробный", show_alert=True)
    await call.answer("Продлеваю…")
    until = builder.add_days(core.trial_days() or 3, b["trial_until"])
    db.set_hosted(bid, trial_until=until, trial_warned=0)
    if b["status"] == "expired" and b["token"]:
        db.set_hosted(bid, status="running")
        await hosting.launch(bid)
    await cbot.send(b["user_id"], f"🎁 Пробный период бота @{html.escape(b['username'] or '?')} продлён до "
                                  f"<b>{builder.fmt_until(until)}</b>.")
    await bot_view(call, bid, f"🎁 Продлён до {builder.fmt_until(until)}.\n\n")


@router.callback_query(F.data.startswith("ca:hp:"))
async def cb_bot_permanent(call: CallbackQuery, bot: Bot):
    from handlers import builder
    from ctor import bot as cbot
    bid = int(call.data[6:])
    b = db.hosted(bid)
    if not b or not b["trial_until"]:
        return await call.answer("Уже навсегда", show_alert=True)
    await call.answer("Готово")
    await builder.make_permanent(bot, b)
    await cbot.send(b["user_id"], core.tx("bought", username=html.escape(b["username"] or "?")))
    await bot_view(call, bid, "♾ Теперь навсегда.\n\n")


# ======================= пользователи =======================
async def users_view(target, prefix=""):
    users, today, *_ = stats()
    top = db.q("SELECT * FROM ctor_users WHERE balance > 0 ORDER BY balance DESC LIMIT 10")
    text = (f"{prefix}👥 <b>Пользователи конструктора</b>: {users} (+{today} сегодня)\n\n"
            + ("<b>С балансом:</b>\n" + "\n".join(f"• {core.user_link(u)} — {money(u['balance'])}" for u in top)
               if top else "<i>Ни у кого нет денег на балансе.</i>"))
    await render(target, text, kb([
        [B("💰 Изменить баланс", "ca:ubal", style="primary")],
        [B("🔎 Найти по ID", "ca:ufind"), B("⛔ Блок / разблок", "ca:uban")],
        back(),
    ]))


@router.callback_query(F.data == "ca:usr")
async def cb_users(call: CallbackQuery):
    await users_view(call)
    await call.answer()


@router.callback_query(F.data == "ca:ubal")
async def cb_user_balance(call: CallbackQuery):
    await ask(call, "ubal", "💰 Отправьте ID пользователя и сумму, например:\n<code>123456789 +300</code> — начислить\n"
                            "<code>123456789 -100</code> — списать", cancel="ca:usr")


@router.callback_query(F.data == "ca:ufind")
async def cb_user_find(call: CallbackQuery):
    await ask(call, "ufind", "🔎 Отправьте ID пользователя:", cancel="ca:usr")


@router.callback_query(F.data == "ca:uban")
async def cb_user_ban(call: CallbackQuery):
    await ask(call, "uban", "⛔ Отправьте ID пользователя — если он не заблокирован, заблокирую; если заблокирован — "
                            "разблокирую.", cancel="ca:usr")


# ======================= обязательная подписка =======================
async def subs_view(target, prefix=""):
    import subscription
    chans = db.channels()
    on = subscription.enabled()
    text = (f"{prefix}📣 <b>Обязательная подписка</b>\n\nСтатус: <b>{'✅ включена' if on else '⏸ выключена'}</b>\n"
            "Пока пользователь не подписан на все каналы и чаты из списка, конструктор показывает ему только "
            "кнопки подписки (и в боте, и в мини-приложении). Вас, владельца, это не касается.\n\n")
    text += ("<b>Каналы и чаты:</b>\n" + "\n".join(f"• {html.escape(c['title'] or '')} — {html.escape(c['url'] or '')}"
                                                   for c in chans)) if chans else "<i>Список пуст — подписка не нужна.</i>"
    rows = [[B(f"🗑 {c['title'] or c['chat_id']}"[:60], f"ca:subdel:{c['id']}", style="danger")] for c in chans]
    rows.append([B("➕ Добавить канал / чат", "ca:subadd", style="success")])
    rows.append([B("⏸ Выключить" if on else "▶️ Включить", "ca:subtog")])
    rows.append(back())
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca:subs")
async def cb_subs(call: CallbackQuery):
    await subs_view(call)
    await call.answer()


@router.callback_query(F.data == "ca:subtog")
async def cb_subs_toggle(call: CallbackQuery):
    import subscription
    db.set_setting("sub_on", "0" if subscription.enabled() else "1")
    await subs_view(call)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("ca:subdel:"))
async def cb_subs_del(call: CallbackQuery):
    db.delete_channel(int(call.data.split(":")[2]))
    await subs_view(call, "🗑 Удалено.\n\n")
    await call.answer()


@router.callback_query(F.data == "ca:subadd")
async def cb_subs_add(call: CallbackQuery):
    await ask(call, "subadd", "➕ <b>Добавить канал или чат</b>\n\n1. Сделайте бота-конструктора "
                              "<b>администратором</b> канала / чата.\n2. Отправьте сюда:\n"
                              "• <code>@username</code> или ссылку <code>https://t.me/username</code>\n"
                              "• или ID (<code>-100...</code>)\n• или просто <b>перешлите пост</b> из канала\n\n"
                              "Для приватного канала бот сам создаст ссылку-приглашение (можно указать свою: "
                              "<code>-1001234567890 | https://t.me/+AbC...</code>).", cancel="ca:subs")


async def _sub_add(m: Message, txt, bot: Bot):
    import subscription
    from handlers.admin import parse_chat_ref
    fo = m.forward_origin
    if fo is not None and fo.type == "channel":
        ref, link = fo.chat.id, ""
    elif fo is not None and fo.type == "chat" and getattr(fo, "sender_chat", None):
        ref, link = fo.sender_chat.id, ""
    elif txt:
        ref, link = parse_chat_ref(txt)
    else:
        return False, "Отправьте @username, ссылку, ID или перешлите пост:"
    try:
        chat = await bot.get_chat(ref)
    except Exception as e:
        return False, f"❌ Не нашёл такой канал или чат: {html.escape(str(e))}\n\nПроверьте и отправьте ещё раз:"
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status not in ("administrator", "creator"):
            raise ValueError
    except Exception:
        return False, "❌ Бот-конструктор не администратор там. Добавьте его админом и отправьте снова:"
    url = link or (f"https://t.me/{chat.username}" if chat.username else "")
    if not url:
        try:
            url = (await bot.create_chat_invite_link(chat.id)).invite_link
        except Exception:
            return False, ("❌ Это приватный канал, а бот не может создать приглашение. Дайте ему право "
                           "«Приглашать пользователей» или пришлите: <code>ID | https://t.me/+...</code>")
    db.add_channel(chat.id, (chat.title or str(chat.id))[:60], url)
    subscription.forget(m.from_user.id)
    return True, ""


# ======================= рассылка =======================
@router.callback_query(F.data == "ca:bc")
async def cb_broadcast(call: CallbackQuery):
    await ask(call, "bc", f"📢 <b>Рассылка всем пользователям конструктора</b> ({len(core.user_ids())} чел.)\n\n"
                          "Отправьте сообщение — текст, фото, видео или файл (премиум-эмодзи сохранятся).")


# ======================= чеки пополнения =======================
@router.callback_query(F.data.startswith("ca:tok:") | F.data.startswith("ca:tno:"))
async def cb_topup_receipt(call: CallbackQuery):
    from ctor import bot as cbot
    ok = call.data.startswith("ca:tok:")
    tid = int(call.data[7:])
    t = core.topup(tid)
    if not t or t["status"] != "pending":
        await mark_admin_msg(call, "ℹ️ Уже обработан")
        return await call.answer("Уже обработан", show_alert=True)
    who = html.escape(call.from_user.first_name or "admin")
    if ok:
        core.set_topup(tid, status="done")
        core.add_balance(t["user_id"], t["amount"])
        u = core.user(t["user_id"])
        await cbot.send(t["user_id"], core.tx("topup_ok", amount=money(t["amount"]), balance=money(u["balance"])),
                        kb([[cbot.B("create", "c:new")], [cbot.B("menu", "c:menu")]]))
        await mark_admin_msg(call, f"✅ Зачислено ({who})")
        await call.answer("Зачислено")
    else:
        core.set_topup(tid, status="rejected")
        await cbot.send(t["user_id"], core.tx("topup_no", amount=money(t["amount"])),
                        kb([[cbot.B("support", "c:sup")]]))
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")


# ======================= ввод =======================
def _waiting(m: Message):
    return bool(m.from_user) and m.from_user.id in _wait


@router.message(_waiting)
async def on_input(m: Message, bot: Bot):
    uid = m.from_user.id
    w = _wait.get(uid) or {}
    act = w.get("act")
    txt = (m.text or m.caption or "").strip()
    if txt.startswith("/") and act not in ("text", "welcome", "bc"):
        _wait.pop(uid, None)
        return await home(m)

    def finish():
        _wait.pop(uid, None)

    if act == "welcome":
        media = media_of(m)
        if m.text or m.caption:
            core.put("t:welcome", m.html_text)
        if media:
            core.put("welcome_media", f"{media[0]}|{media[1]}")
        if not (m.text or m.caption or media):
            return await m.answer("Пришлите текст и/или фото, видео, GIF:")
        finish()
        return await welcome_view(m, "✅ Приветствие сохранено.\n\n")
    if act == "btext":
        rest, icon = split_custom_emoji(m)
        if not rest or len(rest) > 60:
            return await m.answer("Нужен текст до 60 символов:")
        core.put("b:" + w["key"], rest)
        if icon:
            core.put("bi:" + w["key"], icon)
        finish()
        return await btn_view(m, w["key"], "✅ Сохранено.\n\n")
    if act in ("bicon", "icon"):
        _, icon = split_custom_emoji(m)
        if not icon:
            return await m.answer("Это не премиум-эмодзи. Пришлите именно премиум-эмодзи (нужен Telegram Premium):")
        finish()
        if act == "bicon":
            core.put("bi:" + w["key"], icon)
            return await btn_view(m, w["key"], "✅ Премиум-эмодзи стоит.\n\n")
        core.put("ai:" + w["slot"], icon)
        return await icon_view(m, w["slot"], "✅ Сохранено.\n\n")
    if act == "text":
        if not txt:
            return await m.answer("Пришлите текст:")
        body = m.html_text
        if len(body) > 3800:
            return await m.answer("Слишком длинно — до 3800 символов:")
        core.put("t:" + w["key"], body)
        finish()
        return await text_view(m, w["key"], "✅ Сохранено.\n\n")
    if act == "subadd":
        ok, msg = await _sub_add(m, txt, bot)
        if not ok:
            return await m.answer(msg)
        finish()
        return await subs_view(m, "✅ Добавлено.\n\n")
    if act == "appbg":
        media = media_of(m)
        if not media or media[0] == "animation":
            return await m.answer("Пришлите фото или видео:")
        core.put("app_bg", f"{media[0]}|{media[1]}")
        finish()
        return await app_view(m, "✅ Фон сохранён.\n\n")
    if act == "value":
        return await _on_value(m, w, txt, finish)
    if act == "ubal":
        parts = txt.replace(",", ".").split()
        try:
            target, amount = int(parts[0]), round(float(parts[1]), 2)
        except (IndexError, ValueError):
            return await m.answer("Формат: <code>123456789 +300</code>")
        u = core.user(target)
        if not u:
            return await m.answer("Такого пользователя нет в конструкторе (он должен хотя бы раз нажать /start).")
        core.add_balance(target, amount)
        finish()
        u = core.user(target)
        from ctor import bot as cbot
        if amount > 0:
            await cbot.send(target, core.tx("topup_ok", amount=money(amount), balance=money(u["balance"])))
        return await users_view(m, f"✅ Баланс {core.user_link(u)}: {money(u['balance'])}\n\n")
    if act in ("ufind", "uban"):
        if not txt.lstrip("-").isdigit():
            return await m.answer("Нужен числовой ID:")
        u = core.user(int(txt))
        if not u:
            return await m.answer("Не найден. Ещё раз:")
        finish()
        if act == "uban":
            db.x("UPDATE ctor_users SET banned=? WHERE id=?", (0 if u["banned"] else 1, u["id"]))
            u = core.user(u["id"])
        bots = db.q("SELECT * FROM hosted_bots WHERE user_id=? AND status NOT IN ('canceled','deleted')", (u["id"],))
        return await users_view(m, f"👤 {core.user_link(u)}\n💰 Баланс: {money(u['balance'])}\n"
                                   f"📅 С {u['joined']}{' · ⛔ заблокирован' if u['banned'] else ''}\n🤖 Ботов: "
                                   + (", ".join(f"@{html.escape(b['username'] or '?')}" for b in bots) or "нет")
                                   + "\n\n")
    if act == "bc":
        finish()
        ids = core.user_ids()
        from ctor import bot as cbot

        async def send_one(b, to):
            await b.copy_message(to, m.chat.id, m.message_id)

        asyncio.create_task(broadcast(cbot.bot() or bot, ids, send_one, uid))
        return await m.answer(f"📢 Рассылка запущена на {len(ids)} чел. Когда закончится — пришлю отчёт.",
                              reply_markup=kb([back()]))


async def _on_value(m, w, txt, finish):
    key = w["key"]
    if key in ("price", "topup_min"):
        try:
            v = round(float(txt.replace(",", ".")), 2)
        except ValueError:
            return await m.answer("Нужно число:")
        if v < 0 or (key == "topup_min" and v < 1):
            return await m.answer("Слишком мало. Ещё раз:")
        core.put(key, v)
    elif key == "trial_days":
        if not txt.isdigit() or int(txt) > 365:
            return await m.answer("Нужно целое число от 0 до 365:")
        core.put(key, int(txt))
    elif key == "sbp":
        core.put(key, None if txt == "-" else m.html_text)
    elif key in ("support_url", "curator"):
        if txt == "-":
            core.put(key, None)
        else:
            url = fix_url(txt)
            if not url:
                return await m.answer("Нужна ссылка https://… или @username:")
            core.put(key, txt if txt.startswith("@") else url)
    elif key == "site":
        url = txt.strip().rstrip("/")
        if not url.startswith("https://") or " " in url:
            return await m.answer("Нужен адрес, который начинается с https://")
        db.set_setting("public_url", url)
        from ctor import bot as cbot
        await cbot.setup_menu_button()
    elif key == "app_accent":
        if txt == "-":
            core.put(key, None)
        else:
            h = core.norm_hex(txt)
            if not h:
                return await m.answer("Нужен цвет вида <code>#8b5cf6</code>:")
            core.put(key, h)
    finish()
    if key == "app_accent":
        return await app_view(m, "✅ Сохранено.\n\n")
    await home(m, "✅ Сохранено.\n\n")
