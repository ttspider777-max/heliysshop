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
    if target.startswith("ca:u:"):
        return await user_card(call, int(target[5:]))
    if target == "ca:pay":
        return await pay_view(call)
    if target.startswith("ca:ic:"):
        return await icon_view(call, target[6:])
    if target == "ca:ref":
        return await ref_view(call)
    if target == "ca:prm":
        return await promos_view(call)
    await home(call)


def _pct(v):
    return f"{int(v) if v == int(v) else v}%"


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
    pending = (db.val("SELECT COUNT(*) FROM ctor_topups WHERE status='pending'") or 0) + \
        (db.val("SELECT COUNT(*) FROM ctor_payments WHERE status='pending'") or 0)
    return users, today, bots, run, trials, bal, topped, pending


async def home(target, prefix=""):
    users, today, bots, run, trials, bal, topped, pending = stats()
    from ctor import bot as cbot
    paid_n = db.val("SELECT COUNT(*) FROM ctor_payments WHERE status='paid'") or 0
    paid_rub = db.val("SELECT COALESCE(SUM(amount),0) FROM ctor_payments WHERE status='paid' AND method!='stars'") or 0
    paid_stars = db.val("SELECT COALESCE(SUM(stars),0) FROM ctor_payments WHERE status='paid' AND method='stars'") or 0
    text = (f"{prefix}⚙️ <b>Админ-панель конструктора</b> @{html.escape(cbot.username() or '?')}\n\n<blockquote>"
            f"👥 Пользователей: <b>{users}</b> (+{today} сегодня)\n"
            f"🤖 Магазинов: <b>{bots}</b> · работает {run} · на пробном {trials}\n"
            f"💰 Оплат: <b>{paid_n}</b> на <b>{money(paid_rub)}</b> + {paid_stars} ⭐\n"
            f"🔎 Чеков на проверке: <b>{pending}</b></blockquote>\n\n"
            + ("🛠 <b>ВКЛЮЧЕНЫ ТЕХРАБОТЫ</b> — пользователи видят заглушку.\n\n" if core.get("maint") == "1" else "")
            + f"💰 Цена бота: <b>{money(core.price())}</b> · 🎁 Пробный: <b>{core.trial_days() or 'выкл'}</b>"
            f"{' дн.' if core.trial_days() else ''}")
    if not cbot.app_url():
        text += ("\n\n⚠️ <i>Мини-приложение недоступно: не задан https-адрес сайта. На BotHost включите "
                 "«Использовать домен» (порт 8080) и вставьте выданный адрес кнопкой «🌐 Адрес сайта». "
                 "Пока создание идёт кнопками в чате.</i>")
    await render(target, text, kb([
        [B("👋 Приветствие", "ca:wel"), B("🔘 Кнопки", "ca:btns")],
        [B("📝 Тексты бота", "ca:txl:0"), B("📱 Мини-приложение", "ca:app", style="primary")],
        [B("💰 Цена", "ca:v:price"), B("🎁 Пробный период", "ca:v:trial_days")],
        [B("💳 Оплата: звёзды, крипта, СБП", "ca:pay", style="primary")],
        [B("💳 Реквизиты СБП", "ca:v:sbp"), B("💬 Поддержка", "ca:v:support_url")],
        [B("💵 Мин. пополнение", "ca:v:topup_min"), B("🌐 Адрес сайта", "ca:v:site")],
        [B("👨‍💼 Куратор", "ca:v:curator")],
        [B(f"🤝 Рефералы ({_pct(core.ref_percent()) if core.ref_percent() else 'выкл'})", "ca:ref"),
         B(f"🎟 Промокоды ({db.val('SELECT COUNT(*) FROM ctor_promos') or 0})", "ca:prm")],
        [B("🔔 Напоминания и автопокупка", "ca:rem")],
        [B("🤖 Магазины клиентов", "ca:hb:0", style="success")],
        [B(f"👥 Пользователи ({users})", "ca:ul:0", style="primary"), B("📢 Рассылка", "ca:bc")],
        [B(f"📣 Обязательная подписка ({len(db.channels())})", "ca:subs")],
        [B("🛠 Техработы: ВКЛ — выключить" if core.get("maint") == "1" else "🛠 Включить техработы", "ca:maint",
           style="danger" if core.get("maint") == "1" else None)],
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
    "stars_price": ("⭐ Цена в звёздах", "Сколько звёзд стоит бот? Отправьте число (например <code>150</code>). "
                                        "<code>0</code> — считать автоматически из цены в ₽."),
    "usdt_rate": ("💱 Курс USDT", "Курс 1 USDT в рублях для счетов xRocket (например <code>95</code>). "
                                 "<code>0</code> — брать курс из CryptoBot."),
    "curator": ("👨‍💼 Куратор", "Отправьте @username или ссылку куратора — после создания магазина бот напишет "
                               "владельцу «Напиши своему куратору» с этой ссылкой. <code>-</code> — как поддержка.\n\n"
                               "Текст сообщения меняется в «📝 Тексты бота» → «Сообщение о кураторе»."),
    "topup_min": ("💵 Мин. пополнение", "Минимальная сумма пополнения в рублях (например <code>50</code>)."),
    "site": ("🌐 Адрес сайта", "Отправьте https-адрес, который BotHost выдал этому боту (например "
                              "<code>https://bot-123-heliys.bothost.tech</code>). Без него мини-приложение не откроется."),
    "app_accent": ("🎨 Цвет мини-приложения", "Отправьте цвет в формате <code>#8b5cf6</code>. "
                                             "<code>-</code> — стандартный."),
    "ref_percent": ("🤝 Процент рефералу", "Сколько % от каждой оплаты друга получает пригласивший (на баланс "
                                          "конструктора). Например <code>15</code>. <code>0</code> — выключить программу."),
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
           "stars_price": f"{core.stars_price()} ⭐", "usdt_rate": db.get_setting("crypto_usdt_rate") or "авто",
           "app_accent": core.get("app_accent") or "#8b5cf6",
           "ref_percent": _pct(core.ref_percent()),
           "site": html.escape(appcfg.public_url() or "не задан")}[key]
    await ask(call, "value", f"<b>{name}</b>\n\nСейчас: {cur}\n\n{prompt}",
              cancel="ca:app" if key == "app_accent" else "ca:pay" if key in ("stars_price", "usdt_rate")
              else "ca:ref" if key == "ref_percent" else "ca:home",
              key=key)


# ======================= рефералы =======================
async def ref_view(target, prefix=""):
    p = core.ref_percent()
    invited = db.val("SELECT COUNT(*) FROM ctor_users WHERE referrer_id IS NOT NULL") or 0
    earned = db.val("SELECT COALESCE(SUM(ref_earned),0) FROM ctor_users") or 0
    top = db.q("SELECT u.*, (SELECT COUNT(*) FROM ctor_users r WHERE r.referrer_id=u.id) AS n FROM ctor_users u "
               "WHERE u.id IN (SELECT referrer_id FROM ctor_users WHERE referrer_id IS NOT NULL) "
               "ORDER BY u.ref_earned DESC, n DESC LIMIT 10")
    lines = "\n".join(f"{i}. {core.user_link(u)} — {u['n']} чел., {money(u['ref_earned'])}"
                      for i, u in enumerate(top, 1)) or "пока никого"
    text = (f"{prefix}🤝 <b>Реферальная программа</b>\n\nСтатус: <b>{'✅ ' + _pct(p) + ' с каждой оплаты' if p else '⏸ выкл'}</b>"
            f"\n\n<blockquote>👥 Пришли по ссылкам: <b>{invited}</b>\n💰 Начислено рефералам: <b>{money(earned)}</b>"
            f"</blockquote>\n\n🏆 <b>Топ пригласивших</b>\n{lines}\n\n"
            "<i>Как работает: у каждого пользователя своя ссылка (кнопка «🤝 Пригласить друга»). Когда друг "
            "оплачивает бота (создание или покупку пробного), пригласившему приходит процент на баланс конструктора. "
            "Балансом он оплачивает своих ботов. Вывода денег нет.</i>")
    await render(target, text, kb([
        [B("✏️ Изменить процент", "ca:v:ref_percent", style="primary")],
        back(),
    ]))


@router.callback_query(F.data == "ca:ref")
async def cb_ref(call: CallbackQuery):
    await ref_view(call)
    await call.answer()


# ======================= промокоды =======================
async def promos_view(target, prefix=""):
    rows_db = db.q("SELECT * FROM ctor_promos ORDER BY created DESC LIMIT 30")
    lines = []
    for p in rows_db:
        state = ""
        if p["until"] and p["until"] <= db.now():
            state = " · ⌛ истёк"
        elif p["max_uses"] and p["used"] >= p["max_uses"]:
            state = " · ⌛ закончился"
        lim = f"{p['used']}/{p['max_uses']}" if p["max_uses"] else f"{p['used']}/∞"
        until = f" · до {p['until'][8:10]}.{p['until'][5:7]}" if p["until"] else ""
        lines.append(f"<code>{html.escape(p['code'])}</code> — {core.promo_label(p)} · {lim}{until}{state}")
    btn_on = core.flag_on("promo_btn")
    text = (f"{prefix}🎟 <b>Промокоды конструктора</b>\n\n" + ("\n".join(lines) if lines else "Пока нет промокодов.")
            + "\n\n<i>Каждый промокод — один раз на человека. Скидка действует на создание бота и на покупку "
              "пробного навсегда. «+дни» продлевают пробный (или добавляются при запуске на пробном).</i>")
    rows = [[B("➕ Создать промокод", "ca:prma", style="success")]]
    rows += [[B(f"🗑 {p['code']}", f"ca:prmd:{p['code']}")] for p in rows_db[:15]]
    rows.append([B(f"Кнопка «🎟 Промокод» у пользователей: {'✅ вкл' if btn_on else '⏸ выкл'}", "ca:prmbtn")])
    rows.append(back())
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca:prm")
async def cb_promos(call: CallbackQuery):
    await promos_view(call)
    await call.answer()


@router.callback_query(F.data == "ca:prmbtn")
async def cb_promo_btn(call: CallbackQuery):
    core.put("promo_btn", "1" if not core.flag_on("promo_btn") else "0")
    await promos_view(call)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("ca:prmd:"))
async def cb_promo_del(call: CallbackQuery):
    code = call.data[8:]
    db.x("DELETE FROM ctor_promos WHERE code=?", (code,))
    db.x("UPDATE ctor_users SET promo=NULL WHERE promo=?", (code,))
    await promos_view(call, f"🗑 Промокод {html.escape(code)} удалён.\n\n")
    await call.answer()


@router.callback_query(F.data == "ca:prma")
async def cb_promo_add(call: CallbackQuery):
    await ask(call, "promo_add", (
        "➕ <b>Новый промокод</b>\n\nОтправьте одной строкой: <code>КОД СКИДКА [ЛИМИТ] [ДНЕЙ]</code>\n\n<blockquote>"
        "<code>SALE20 20%</code> — скидка 20%, без лимита\n"
        "<code>MINUS100 100₽ 50</code> — скидка 100₽, 50 активаций\n"
        "<code>FREE 100% 5 3</code> — бесплатно, 5 активаций, действует 3 дня\n"
        "<code>WEEK +7д</code> — +7 дней пробного периода</blockquote>\n\n"
        "КОД — латиница и цифры (3–24 символа). ЛИМИТ <code>0</code> — без лимита."), cancel="ca:prm")


def parse_promo(txt):
    """'КОД 20% 50 7' -> (code, kind, value, max_uses, days) или текст ошибки."""
    parts = txt.replace(",", ".").split()
    if len(parts) < 2 or len(parts) > 4:
        return "Нужно: <code>КОД СКИДКА [ЛИМИТ] [ДНЕЙ]</code>, например <code>SALE20 20% 50</code>"
    code, val = parts[0].upper(), parts[1].lower()
    if not core.PROMO_RE.match(code):
        return "Код — латиница, цифры, _ или - (3–24 символа)."
    try:
        if val.endswith("%"):
            kind, value = "percent", float(val[:-1])
            if not 0 < value <= 100:
                return "Процент — от 1 до 100."
        elif val.startswith("+") and val.rstrip("днейьяd").lstrip("+").replace(".", "").isdigit():
            kind, value = "days", float(int(float(val.rstrip("днейьяd").lstrip("+"))))
            if not 0 < value <= 365:
                return "Дней — от 1 до 365."
        else:
            kind, value = "rub", float(val.rstrip("₽руб.r"))
            if value <= 0:
                return "Скидка должна быть больше нуля."
        max_uses = int(parts[2]) if len(parts) > 2 else 0
        days = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        return "Не понял числа. Пример: <code>SALE20 20% 50 7</code>"
    if max_uses < 0 or days < 0:
        return "Лимит и дни не могут быть отрицательными."
    return code, kind, value, max_uses, days


# ======================= напоминания и автопокупка =======================
async def remind_view(target, prefix=""):
    rem, ab = core.flag_on("remind"), core.flag_on("autobuy")
    abn = db.val("SELECT COUNT(*) FROM ctor_payments WHERE receipt='balance:auto' AND status='paid'") or 0
    text = (f"{prefix}🔔 <b>Напоминания и автопокупка</b>\n\n<blockquote>"
            f"🔔 Напоминания о пробном: <b>{_onoff(rem)}</b>\n"
            f"🔁 Автопокупка с баланса: <b>{_onoff(ab)}</b> · сработала {abn} раз</blockquote>\n\n"
            "<b>Напоминания</b> владельцам пробных магазинов: за 3 дня (если пробный длиннее 4 дней), за сутки, "
            "за 3 часа, в момент выключения и через 1, 3 и 7 дней после.\n\n"
            "<b>Автопокупка</b>: если на балансе владельца хватает денег, за час до конца пробного бот покупается "
            "навсегда сам. Если бот уже выключен — покупается сразу после пополнения баланса (чек принят или вы "
            "начислили вручную). Каждый владелец может выключить её у себя в «🧾 Мои боты».\n\n"
            "Тексты — в «📝 Тексты бота» (Напоминание…, Автопокупка…).")
    await render(target, text, kb([
        [B(f"🔔 Напоминания: {_onoff(rem)}", "ca:remt:remind"), B(f"🔁 Автопокупка: {_onoff(ab)}", "ca:remt:autobuy")],
        back(),
    ]))


@router.callback_query(F.data == "ca:rem")
async def cb_remind(call: CallbackQuery):
    await remind_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("ca:remt:"))
async def cb_remind_toggle(call: CallbackQuery):
    key = call.data[8:]
    if key in ("remind", "autobuy"):
        core.put(key, "1" if not core.flag_on(key) else "0")
    await remind_view(call)
    await call.answer("Готово")


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
PER_PAGE = 8


def _user_row(u):
    bots = db.val("SELECT COUNT(*) FROM hosted_bots WHERE user_id=? AND tg_id IS NOT NULL "
                  "AND status NOT IN ('canceled','deleted')", (u["id"],)) or 0
    name = (u["first_name"] or "—")[:14]
    uname = f" @{u['username']}" if u["username"] else ""
    return (f"{'⛔' if u['banned'] else '👤'} {name}{uname}"[:34] + f" · 🤖{bots}"
            + (f" · {money(u['balance'])}" if (u["balance"] or 0) else ""))


async def users_view(target, prefix="", page=0, flt="all"):
    """Все, кто запускал конструктор: новые сверху, по 8 на страницу. flt: all / bots / banned / money."""
    where = {"all": "1=1",
             "bots": "id IN (SELECT user_id FROM hosted_bots WHERE tg_id IS NOT NULL AND status NOT IN ('canceled','deleted'))",
             "banned": "banned=1", "money": "balance > 0"}[flt]
    total = db.val(f"SELECT COUNT(*) FROM ctor_users WHERE {where}") or 0
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(max(page, 0), pages - 1)
    rows_db = db.q(f"SELECT * FROM ctor_users WHERE {where} ORDER BY joined DESC, id DESC LIMIT ? OFFSET ?",
                   (PER_PAGE, page * PER_PAGE))
    users, today, *_ = stats()
    with_bots = db.val("SELECT COUNT(DISTINCT user_id) FROM hosted_bots WHERE tg_id IS NOT NULL "
                       "AND status NOT IN ('canceled','deleted')") or 0
    banned = db.val("SELECT COUNT(*) FROM ctor_users WHERE banned=1") or 0
    names = {"all": "все", "bots": "создали бота", "banned": "в бане", "money": "с балансом"}
    text = (f"{prefix}👥 <b>Пользователи конструктора</b>\n\n<blockquote>Всего: <b>{users}</b> (+{today} сегодня)\n"
            f"🤖 Создали бота: <b>{with_bots}</b> · ⛔ в бане: <b>{banned}</b></blockquote>\n\n"
            f"Показаны: <b>{names[flt]}</b> ({total}) · стр. {page + 1}/{pages}\nНажмите на человека — откроется карточка.")
    rows = [[B(_user_row(u), f"ca:u:{u['id']}")] for u in rows_db]
    nav = []
    if page > 0:
        nav.append(B("◀️", f"ca:ul:{page - 1}:{flt}"))
    if pages > 1:
        nav.append(B(f"{page + 1}/{pages}", "ca:noop"))
    if page < pages - 1:
        nav.append(B("▶️", f"ca:ul:{page + 1}:{flt}"))
    if nav:
        rows.append(nav)
    rows.append([B(("• " if flt == k else "") + t, f"ca:ul:0:{k}") for k, t in
                 (("all", "Все"), ("bots", "С ботом"), ("banned", "Бан"), ("money", "Баланс"))])
    rows.append([B("🔎 Найти по ID / @username", "ca:ufind", style="primary")])
    rows.append(back())
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca:usr")
async def cb_users(call: CallbackQuery):
    await users_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("ca:ul:"))
async def cb_users_page(call: CallbackQuery):
    parts = call.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    flt = parts[3] if len(parts) > 3 and parts[3] in ("all", "bots", "banned", "money") else "all"
    await users_view(call, page=page, flt=flt)
    await call.answer()


STATUS_RU = {"running": "✅ работает", "stopped": "⏸ остановлен", "failed": "⚠️ упал", "expired": "⌛ пробный кончился",
             "wait_token": "🔑 ждёт токен", "pending": "🔎 проверка оплаты", "rejected": "❌ отклонён"}


async def user_card(target, uid, prefix=""):
    from handlers import builder
    u = core.user(uid)
    if not u:
        return await users_view(target, "Пользователь не найден.\n\n")
    bots = db.q("SELECT * FROM hosted_bots WHERE user_id=? AND tg_id IS NOT NULL AND status NOT IN ('canceled','deleted') "
                "ORDER BY id", (uid,))
    paid = db.q1("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN method!='stars' THEN amount END),0) rub, "
                 "COALESCE(SUM(CASE WHEN method='stars' THEN stars END),0) st FROM ctor_payments "
                 "WHERE user_id=? AND status='paid'", (uid,))
    pend = db.val("SELECT COUNT(*) FROM ctor_payments WHERE user_id=? AND status='pending'", (uid,)) or 0
    d, step = core.draft(uid)
    lines = []
    for b in bots:
        tail = (f" · 🎁 до {builder.fmt_until(b['trial_until'])}" if b["trial_until"] else " · ♾ навсегда")
        lines.append(f"• @{html.escape(b['username'] or '?')} — {STATUS_RU.get(b['status'], b['status'])}{tail}")
    text = (f"{prefix}👤 <b>{html.escape(u['first_name'] or '—')}</b>\n\n<blockquote>"
            f"🆔 ID: <code>{u['id']}</code>\n"
            f"🔗 Юзернейм: {('@' + html.escape(u['username'])) if u['username'] else '—'}\n"
            f"📅 Первый запуск: {u['joined'] or '—'}\n"
            f"💰 Баланс: <b>{money(u['balance'])}</b>\n"
            f"💳 Оплат: <b>{paid['n']}</b> на {money(paid['rub'])}" + (f" + {paid['st']} ⭐" if paid["st"] else "")
            + (f" · 🔎 на проверке: {pend}" if pend else "") + "\n"
            f"🎁 Пробный: {'использован' if db.trial_used(uid) else 'не брал'}\n"
            f"🛠 Сейчас: {('в мастере, шаг «' + step + '»') if step else ('черновик есть' if d else '—')}\n"
            f"🚦 Статус: {'⛔ <b>в бане</b>' if u['banned'] else '✅ активен'}</blockquote>\n\n"
            f"🤖 <b>Боты ({len(bots)}):</b>\n" + ("\n".join(lines) if lines else "<i>ещё не создал</i>"))
    rows = [
        [B("✅ Разбанить" if u["banned"] else "⛔ Забанить", f"ca:ub:{uid}", style="success" if u["banned"] else "danger")],
        [B("💰 Изменить баланс", f"ca:ubm:{uid}"), B("✉️ Написать", f"ca:um:{uid}")],
    ]
    for b in bots[:6]:
        rows.append([B(f"🤖 @{b['username'] or b['id']} — управление", f"ca:hv:{b['id']}")])
    rows.append([B("🔗 Открыть профиль в Telegram", url=f"tg://user?id={uid}")])
    rows.append(back("ca:ul:0", "◀️ К пользователям"))
    await render(target, text, kb(rows))


@router.callback_query(F.data.startswith("ca:u:"))
async def cb_user_card(call: CallbackQuery):
    await user_card(call, int(call.data[5:]))
    await call.answer()


@router.callback_query(F.data.startswith("ca:ub:"))
async def cb_user_ban(call: CallbackQuery):
    uid = int(call.data[6:])
    u = core.user(uid)
    if not u:
        return await call.answer()
    if uid in config.ADMINS:
        return await call.answer("Владельца забанить нельзя 🙂", show_alert=True)
    db.x("UPDATE ctor_users SET banned=? WHERE id=?", (0 if u["banned"] else 1, uid))
    await user_card(call, uid, "✅ Разбанен.\n\n" if u["banned"] else "⛔ Забанен.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca:ubm:"))
async def cb_user_money(call: CallbackQuery):
    uid = int(call.data[7:])
    await ask(call, "ubal1", "💰 Отправьте сумму: <code>+300</code> — начислить, <code>-100</code> — списать.",
              cancel=f"ca:u:{uid}", uid=uid)


@router.callback_query(F.data.startswith("ca:um:"))
async def cb_user_msg(call: CallbackQuery):
    uid = int(call.data[6:])
    await ask(call, "umsg", "✉️ Отправьте сообщение для пользователя — текст, фото, видео или файл. Он получит его от "
                            "бота-конструктора.", cancel=f"ca:u:{uid}", uid=uid)


@router.callback_query(F.data == "ca:maint")
async def cb_maint(call: CallbackQuery):
    on = core.get("maint") == "1"
    core.put("maint", None if on else "1")
    await home(call, "✅ Техработы выключены — бот снова доступен всем.\n\n" if on else
               "🛠 Техработы включены: пользователи видят заглушку (текст — «📝 Тексты бота» → «Техработы»). "
               "Вам бот доступен как обычно, уже созданные магазины работают.\n\n")
    await call.answer("Готово")


@router.callback_query(F.data == "ca:ubal")
async def cb_user_balance(call: CallbackQuery):
    await ask(call, "ubal", "💰 Отправьте ID пользователя и сумму, например:\n<code>123456789 +300</code> — начислить\n"
                            "<code>123456789 -100</code> — списать", cancel="ca:usr")


@router.callback_query(F.data == "ca:ufind")
async def cb_user_find(call: CallbackQuery):
    await ask(call, "ufind", "🔎 Отправьте ID или @username пользователя:", cancel="ca:usr")


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


# ======================= оплата =======================
def _onoff(v):
    return "✅ вкл" if v else "⏸ выкл"


async def pay_view(target, prefix=""):
    import crypto
    text = (f"{prefix}💳 <b>Оплата магазинов</b>\n\nЦена: <b>{money(core.price())}</b> · звёздами "
            f"<b>{core.stars_price()} ⭐</b>\n🎁 Пробный: <b>{core.trial_days() or 'выкл'}</b>"
            f"{' дн.' if core.trial_days() else ''}\n\n<blockquote>"
            f"⭐ Звёзды Telegram: {_onoff(core.pay_on('stars'))}\n"
            f"💎 CryptoBot: {'✅ подключён' if crypto.token('cryptobot') else '— нет ключа'}"
            f"{'' if not crypto.token('cryptobot') else ' · ' + _onoff(crypto.enabled('cryptobot'))}\n"
            f"🚀 xRocket: {'✅ подключён' if crypto.token('xrocket') else '— нет ключа'}"
            f"{'' if not crypto.token('xrocket') else ' · ' + _onoff(crypto.enabled('xrocket'))}\n"
            f"💳 СБП (чек → вы принимаете): {_onoff(core.pay_on('sbp'))}</blockquote>\n\n"
            "Премиум-эмодзи на кнопках оплаты — в «🔘 Кнопки» (Пробный период, Оплата звёздами, CryptoBot, "
            "xRocket, СБП), в мини-приложении — «📱 Мини-приложение → 💎 Иконки».")
    await render(target, text, kb([
        [B(f"⭐ Звёзды: {_onoff(core.pay_on('stars'))}", "ca:ptog:stars"), B("⭐ Цена в звёздах", "ca:v:stars_price")],
        [B(f"💳 СБП: {_onoff(core.pay_on('sbp'))}", "ca:ptog:sbp"), B("💳 Реквизиты", "ca:v:sbp")],
        [B("💎 CryptoBot — API-токен", "ca:cr:cryptobot"), B("🚀 xRocket — API-токен", "ca:cr:xrocket")],
        [B("💱 Курс USDT (xRocket)", "ca:v:usdt_rate"), B("💰 Цена в ₽", "ca:v:price")],
        back(),
    ]))


@router.callback_query(F.data == "ca:pay")
async def cb_pay(call: CallbackQuery):
    await pay_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("ca:ptog:"))
async def cb_pay_toggle(call: CallbackQuery):
    m = call.data[8:]
    core.put("pay_off:" + m, None if core.get("pay_off:" + m) == "1" else "1")
    await pay_view(call)
    await call.answer("Готово")


async def crypto_view(target, method, prefix=""):
    import crypto
    name = crypto.SERVICES[method]
    has = bool(crypto.token(method))
    how = ("CryptoBot: откройте @CryptoBot → Crypto Pay → Создать приложение → скопируйте API-токен."
           if method == "cryptobot" else
           "xRocket: откройте @xRocket → Rocket Pay → Создать приложение → скопируйте API-ключ.")
    text = (f"{prefix}{'💎' if method == 'cryptobot' else '🚀'} <b>{name}</b>\n\nСтатус: "
            f"<b>{('✅ подключён · ' + _onoff(crypto.enabled(method))) if has else 'не подключён'}</b>\n\n{how}\n\n"
            "Ключ хранится в базе бота, не в коде.")
    rows = [[B("🔑 Вставить API-токен" if not has else "🔑 Заменить токен", f"ca:crk:{method}", style="primary")]]
    if has:
        rows.append([B("⏸ Выключить" if crypto.enabled(method) else "▶️ Включить", f"ca:crt:{method}"),
                     B("🗑 Удалить ключ", f"ca:crd:{method}", style="danger")])
    rows.append(back("ca:pay", "◀️ К оплате"))
    await render(target, text, kb(rows))


@router.callback_query(F.data.startswith("ca:cr:"))
async def cb_crypto(call: CallbackQuery):
    await crypto_view(call, call.data[6:])
    await call.answer()


@router.callback_query(F.data.startswith("ca:crk:"))
async def cb_crypto_key(call: CallbackQuery):
    method = call.data[7:]
    await ask(call, "crkey", "🔑 Отправьте API-токен — я проверю его и сразу удалю сообщение.",
              cancel="ca:pay", method=method)


@router.callback_query(F.data.startswith("ca:crt:"))
async def cb_crypto_toggle(call: CallbackQuery):
    import crypto
    method = call.data[7:]
    db.set_setting(f"crypto_on:{method}", "0" if crypto.enabled(method) else "1")
    await crypto_view(call, method)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("ca:crd:"))
async def cb_crypto_del(call: CallbackQuery):
    method = call.data[7:]
    db.set_setting(f"crypto_token:{method}", None)
    await crypto_view(call, method, "🗑 Ключ удалён.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca:pok:") | F.data.startswith("ca:pno:"))
async def cb_payment_receipt(call: CallbackQuery):
    """Чек СБП: ✅ Принять — бот создаёт магазин (или делает бессрочным); ❌ Отклонить — заявка отклонена."""
    from ctor import bot as cbot
    ok = call.data.startswith("ca:pok:")
    pid = int(call.data[7:])
    p = core.payment(pid)
    if not p or p["status"] != "pending":
        await mark_admin_msg(call, f"ℹ️ Уже обработана: {p['status'] if p else '—'}")
        return await call.answer("Уже обработана", show_alert=True)
    who = html.escape(call.from_user.first_name or "admin")
    if ok:
        await call.answer("Принято — создаю")
        await mark_admin_msg(call, f"✅ Принято ({who})")
        await cbot.on_paid(pid, p["receipt"])
    else:
        core.set_payment(pid, status="rejected")
        await cbot.send(p["user_id"], core.tx("pay_rejected", id=pid), kb([[cbot.B("support", "c:sup")]]))
        await mark_admin_msg(call, f"❌ Отклонено ({who})")
        await call.answer("Отклонено")


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
        await cbot.autobuy_user(t["user_id"])  # хватает на пробного бота — купить сразу
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
    if txt.startswith("/") and act not in ("text", "welcome", "bc", "umsg"):
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
    if act == "crkey":
        import crypto
        method = w["method"]
        try:
            await m.delete()
        except Exception:
            pass
        tok = txt.strip()
        if not tok or " " in tok:
            return await m.answer("Отправьте токен одним словом:")
        try:
            info = await crypto.test(method, tok)
        except Exception as e:
            return await m.answer(f"❌ Ключ не подошёл: {html.escape(str(e))[:200]}\n\nОтправьте другой:")
        db.set_setting(f"crypto_token:{method}", tok)
        db.set_setting(f"crypto_on:{method}", "1")
        finish()
        return await crypto_view(m, method, f"✅ Подключено: {info}\n\n")
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
    if act == "promo_add":
        res = parse_promo(txt)
        if isinstance(res, str):
            return await m.answer(res)
        code, kind, value, max_uses, days = res
        if core.promo(code):
            return await m.answer("Такой код уже есть — придумайте другой:")
        until = None
        if days:
            from datetime import datetime, timedelta
            until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db.x("INSERT INTO ctor_promos(code, kind, value, max_uses, used, until, created) VALUES (?,?,?,?,0,?,?)",
             (code, kind, value, max_uses, until, db.now()))
        finish()
        return await promos_view(m, f"✅ Промокод <code>{html.escape(code)}</code> создан: "
                                    f"{core.promo_label(core.promo(code))}.\n\n")
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
            await cbot.autobuy_user(target)
        return await users_view(m, f"✅ Баланс {core.user_link(u)}: {money(u['balance'])}\n\n")
    if act == "ufind":
        q = txt.strip().lstrip("@")
        u = core.user(int(q)) if q.lstrip("-").isdigit() else \
            db.q1("SELECT * FROM ctor_users WHERE LOWER(username)=LOWER(?)", (q,))
        if not u:
            return await m.answer("Не найден — он должен хотя бы раз запустить конструктор. Ещё раз:")
        finish()
        return await user_card(m, u["id"])
    if act == "ubal1":
        try:
            amount = round(float(txt.replace(",", ".").replace("₽", "").strip()), 2)
        except ValueError:
            return await m.answer("Нужно число, например <code>+300</code>:")
        uid2 = w["uid"]
        core.add_balance(uid2, amount)
        finish()
        u = core.user(uid2)
        from ctor import bot as cbot
        if amount > 0:
            await cbot.send(uid2, core.tx("topup_ok", amount=money(amount), balance=money(u["balance"])))
            await cbot.autobuy_user(uid2)
        return await user_card(m, uid2, f"✅ Баланс: {money(u['balance'])}\n\n")
    if act == "umsg":
        from ctor import bot as cbot
        finish()
        try:
            await (cbot.bot() or bot).copy_message(w["uid"], m.chat.id, m.message_id)
            note = "✅ Отправлено.\n\n"
        except Exception as e:
            note = f"❌ Не доставлено: {html.escape(str(e))[:120]}\n\n"
        return await user_card(m, w["uid"], note)
    if act == "uban":
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
    elif key == "stars_price":
        if not txt.isdigit() or int(txt) > 100000:
            return await m.answer("Нужно целое число звёзд:")
        core.put(key, int(txt) or None)
    elif key == "usdt_rate":
        try:
            v = round(float(txt.replace(",", ".")), 2)
        except ValueError:
            return await m.answer("Нужно число:")
        db.set_setting("crypto_usdt_rate", v or None)
    elif key == "trial_days":
        if not txt.isdigit() or int(txt) > 365:
            return await m.answer("Нужно целое число от 0 до 365:")
        core.put(key, int(txt))
    elif key == "ref_percent":
        try:
            v = round(float(txt.replace(",", ".").replace("%", "")), 2)
        except ValueError:
            return await m.answer("Нужно число от 0 до 100:")
        if not 0 <= v <= 100:
            return await m.answer("Нужно число от 0 до 100:")
        core.put(key, v)
        finish()
        return await ref_view(m, "✅ Сохранено.\n\n")
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
    if key in ("stars_price", "usdt_rate"):
        return await pay_view(m, "✅ Сохранено.\n\n")
    await home(m, "✅ Сохранено.\n\n")
