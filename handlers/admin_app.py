"""Админ-панель → 🎨 Мини-приложение и 💾 База и бэкапы.

Мини-приложение: сезонный стиль (Хэллоуин, Новый год, осень, лето…), тема по умолчанию, карточка на главной
(название, бейдж, фон-фото/видео, логотип), акцентный цвет, обои, иконки с премиум-эмодзи, тексты,
статусы покупателей, ежедневный бонус, суммы пополнения.

Бэкапы: скачать базу, восстановить из файла, автобэкап раз в сутки, экспорт/импорт оформления (.json) —
им удобно перенести оформление в бота клиента. Все настройки лежат в базе и не сбрасываются при обновлении кода.
"""
import html
import io
import json
import os
import tempfile

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import admins
import appcfg
import config
import db
from handlers.admin import B, ask, back, done, inp, parse_amount, router
from texts import APP_TEXTS, EDITABLE_TEXTS, money
from ui import kb, media_of, pager, raw_btn, render, split_custom_emoji

MEDIA_NAMES = {"photo": "фото", "video": "видео", "animation": "GIF"}


def _onoff(v):
    return "ВКЛ ✅" if v else "ВЫКЛ"


# ======================= главный экран раздела =======================
async def app_view(target, prefix=""):
    url = appcfg.app_url()
    season = appcfg.season()
    bg = db.get_setting("app_bg")
    logo = db.get_setting("app_logo")
    wall = db.get_setting("app_wall")
    custom_icons = sum(1 for k in appcfg.ICON_SLOTS if db.get_setting(f"ai:{k}"))
    lines = [
        f"{prefix}🎨 <b>Мини-приложение</b>",
        "<blockquote>"
        f"🌐 Адрес: {html.escape(url) if url else '❗ не настроен — укажите https-адрес сайта бота'}\n"
        f"🎭 Стиль: <b>{appcfg.SEASONS[season][0]}</b> · бейдж «{html.escape(appcfg.badge('ru'))}»\n"
        f"🌓 Тема по умолчанию: <b>{appcfg.THEMES[appcfg.theme()]}</b>\n"
        f"🏷 Название на карточке: <b>{html.escape(appcfg.card_title())}</b>\n"
        f"🎨 Акцент: <code>{appcfg.accent()}</code>\n"
        f"🖼 Фон карточки: {MEDIA_NAMES.get(db.get_setting('app_bg_type') or 'photo') if bg else 'стандартный'}\n"
        f"🔵 Логотип: {'свой' if logo else 'нет'} · 🌌 Обои: {'своё фото' if wall else 'чёрные как в Telegram'}\n"
        f"💎 Иконок с премиум-эмодзи: {custom_icons}\n"
        f"✨ Анимации: {_onoff(appcfg.fx_on())}\n"
        f"🎁 Бонус: {_onoff(appcfg.bonus_on())} · {money(appcfg.bonus_amount())} в сутки"
        "</blockquote>",
    ]
    if not url:
        lines.append(f"\n<i>Telegram открывает мини-приложения только по https. На BotHost в настройках бота включите "
                     f"«Использовать домен», порт <code>{config.WEB_PORT}</code>, пересоберите бота и вставьте выданный адрес "
                     "кнопкой «🌐 Адрес сайта». Пока адреса нет, кнопка «Открыть магазин» показывает каталог в самом боте.</i>")
    rows = [
        [B(f"🎭 Стиль: {appcfg.SEASONS[season][0]}", "a:apps", style="primary")],
        [B(f"🌓 Тема: {appcfg.THEMES[appcfg.theme()]}", "a:appt"), B(f"✨ Анимации: {_onoff(appcfg.fx_on())}", "a:appfx")],
        [B("🏷 Название", "a:appv:app_title"), B("🎃 Текст бейджа", "a:appbadge")],
        [B("🖼 Фон карточки", "a:appm:app_bg"), B("🔵 Логотип", "a:appm:app_logo")],
        [B("🌌 Обои", "a:appm:app_wall"), B("🎨 Акцентный цвет", "a:appv:app_accent")],
        [B("💎 Иконки и премиум-эмодзи", "a:appi:0", style="primary")],
        [B("📝 Тексты мини-приложения", "a:atxl:0")],
        [B("🏅 Статусы", "a:st"), B("🎁 Бонус", "a:bon"), B("💳 Пополнение", "a:tus")],
    ]
    if not config.CHILD:
        rows.append([B("🌐 Адрес сайта", "a:pubu")])
    if url:
        rows.append([raw_btn("👀 Открыть мини-приложение", web_app=url, style="success")])
    rows.append(back())
    await render(target, "\n".join(lines), kb(rows))


@router.callback_query(F.data == "a:app")
async def cb_app(call: CallbackQuery):
    await app_view(call)
    await call.answer()


# ---------- стиль, тема, анимации ----------
@router.callback_query(F.data == "a:apps")
async def cb_seasons(call: CallbackQuery):
    cur = appcfg.season()
    rows = [[B(("✅ " if k == cur else "") + title, f"a:appss:{k}")] for k, (title, *_rest) in appcfg.SEASONS.items()]
    rows.append(back("a:app"))
    await render(call, "🎭 <b>Сезонный стиль мини-приложения</b>\n\nСтиль меняет бейдж на карточке, анимацию "
                       "(летучие мыши, снег, листья, лепестки, сердечки…), акцентный цвет и настроение всего приложения. "
                       "Применяется сразу у всех покупателей.", kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:appss:"))
async def cb_season_set(call: CallbackQuery):
    key = call.data[8:]
    if key not in appcfg.SEASONS:
        return await call.answer("Нет такого стиля", show_alert=True)
    db.set_setting("app_season", key)
    await call.answer(f"Стиль: {appcfg.SEASONS[key][0]}")
    await app_view(call, "✅ Стиль изменён\n\n")


@router.callback_query(F.data == "a:appt")
async def cb_theme(call: CallbackQuery):
    order = list(appcfg.THEMES)
    nxt = order[(order.index(appcfg.theme()) + 1) % len(order)]
    db.set_setting("app_theme", nxt)
    await call.answer(f"Тема по умолчанию: {appcfg.THEMES[nxt]}")
    await app_view(call)


@router.callback_query(F.data == "a:appfx")
async def cb_fx(call: CallbackQuery):
    db.set_setting("app_fx", "0" if appcfg.fx_on() else "1")
    await call.answer("Готово")
    await app_view(call)


# ---------- текстовые значения ----------
APP_VALUES = {
    "app_title": ("🏷 Название на карточке", "Отправьте название магазина для карточки на главной "
                                           "(например <code>Snow Shop</code>). <code>-</code> — как у бота."),
    "app_accent": ("🎨 Акцентный цвет", "Отправьте цвет в формате <code>#ff7a1a</code> — им подсветятся кнопки и "
                                       "акценты. <code>-</code> — цвет текущего сезона."),
}


@router.callback_query(F.data.startswith("a:appv:"))
async def cb_value(call: CallbackQuery, state: FSMContext):
    key = call.data[7:]
    await ask(call, state, "appv", APP_VALUES[key][1], cancel="a:app", key=key)


@inp("appv")
async def i_value(m, state, d, txt, bot):
    key = d["key"]
    if txt == "-":
        db.set_setting(key, None)
    elif key == "app_accent":
        import re
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", txt):
            return await m.answer("Нужен цвет вида <code>#ff7a1a</code>:")
        db.set_setting(key, "#" + txt.lstrip("#").lower())
    else:
        db.set_setting(key, txt[:40])
    await state.clear()
    await app_view(m, "✅ Сохранено\n\n")


@router.callback_query(F.data == "a:appbadge")
async def cb_badge(call: CallbackQuery, state: FSMContext):
    s = appcfg.season()
    await ask(call, state, "appbadge",
              f"🎃 <b>Текст бейджа</b> для стиля {appcfg.SEASONS[s][0]}\n\nСейчас: «{html.escape(appcfg.badge('ru'))}» / "
              f"«{html.escape(appcfg.badge('en'))}»\n\nОтправьте текст в формате <code>RU | EN</code>, например "
              "<code>Хэллоуин | Halloween</code>.\n<code>-</code> — вернуть стандартный.\n\n"
              "💎 Иконку бейджа (вместо анимированной тыквы) можно поставить в «💎 Иконки» → «Бейдж сезона».",
              cancel="a:app", season=s)


@inp("appbadge")
async def i_badge(m, state, d, txt, bot):
    s = d["season"]
    if txt == "-":
        db.set_setting(f"app_badge:{s}:ru", None)
        db.set_setting(f"app_badge:{s}:en", None)
    else:
        ru, _, en = txt.partition("|")
        db.set_setting(f"app_badge:{s}:ru", ru.strip()[:24])
        db.set_setting(f"app_badge:{s}:en", (en.strip() or ru.strip())[:24])
    await state.clear()
    await app_view(m, "✅ Бейдж сохранён\n\n")


# ---------- фон, логотип, обои ----------
APP_MEDIA = {
    "app_bg": ("🖼 Фон карточки на главной", "фото, видео или GIF", True),
    "app_logo": ("🔵 Логотип (круг справа на карточке)", "фото", False),
    "app_wall": ("🌌 Обои мини-приложения", "фото (лучше тёмное, вертикальное)", False),
}


@router.callback_query(F.data.startswith("a:appm:"))
async def cb_media(call: CallbackQuery, state: FSMContext):
    key = call.data[7:]
    title, what, _ = APP_MEDIA[key]
    has = "установлено" if db.get_setting(key) else "стандартное"
    await ask(call, state, "appm", f"{title}\nСейчас: {has}\n\nОтправьте {what}.\n<code>-</code> — вернуть стандартное.",
              cancel="a:app", key=key)


@inp("appm")
async def i_media(m, state, d, txt, bot):
    key = d["key"]
    _, _, video_ok = APP_MEDIA[key]
    media = media_of(m)
    if txt == "-":
        db.set_setting(key, None)
        db.set_setting(f"{key}_type", None)
    elif media and (video_ok or media[0] == "photo"):
        db.set_setting(key, media[1])
        db.set_setting(f"{key}_type", media[0])
    else:
        return await m.answer("Отправьте " + APP_MEDIA[key][1] + " или <code>-</code>:")
    await state.clear()
    await app_view(m, "✅ Сохранено\n\n")


# ---------- иконки (премиум-эмодзи) ----------
ICON_PER = 10


@router.callback_query(F.data.startswith("a:appi:"))
async def cb_icons(call: CallbackQuery):
    keys = list(appcfg.ICON_SLOTS)
    pages = max(1, (len(keys) + ICON_PER - 1) // ICON_PER)
    page = min(max(int(call.data.split(":")[2]), 0), pages - 1)
    ic = appcfg.icons()
    rows = []
    for k in keys[page * ICON_PER:(page + 1) * ICON_PER]:
        mark = "💎 " if ic[k]["id"] else (ic[k]["e"] + " " if ic[k]["e"] else "")
        rows.append([B(f"{mark}{appcfg.ICON_SLOTS[k][0]}", f"a:appic:{k}")])
    rows.append(pager("a:appi:", page, pages))
    rows.append(back("a:app"))
    await render(call, "💎 <b>Иконки мини-приложения</b>\n\nКаждый значок можно заменить на <b>премиум-эмодзи</b> "
                       "(в мини-приложении оно анимированное) или на обычное эмодзи. 💎 — стоит премиум-эмодзи.\n\n"
                       "<i>Премиум-эмодзи в названиях категорий и товаров, описаниях и текстах тоже показываются "
                       "в мини-приложении — просто вставьте их в текст.</i>", kb(rows))
    await call.answer()


@router.callback_query(F.data.startswith("a:appic:"))
async def cb_icon(call: CallbackQuery, state: FSMContext):
    key = call.data[8:]
    title, default = appcfg.ICON_SLOTS[key]
    await ask(call, state, "appic", f"💎 <b>{title}</b>\n\nОтправьте <b>одно премиум-эмодзи</b> (или обычное эмодзи).\n"
                                    f"<code>-</code> — вернуть стандартное ({default or 'анимированная иконка сезона'}).",
              cancel="a:appi:0", key=key)


@inp("appic")
async def i_icon(m, state, d, txt, bot):
    key = d["key"]
    if txt == "-":
        db.set_setting(f"ai:{key}", None)
        db.set_setting(f"aie:{key}", None)
    else:
        _, icon = split_custom_emoji(m)
        if icon:
            db.set_setting(f"ai:{key}", icon)
            # обычное эмодзи, под которым отправлено премиум-эмодзи, — заглушка на время загрузки
            e = next(e for e in (m.entities or []) if e.type == "custom_emoji")
            enc = (m.text or "").encode("utf-16-le")
            alt = enc[e.offset * 2:(e.offset + e.length) * 2].decode("utf-16-le", errors="ignore")
            db.set_setting(f"aie:{key}", alt.strip() or None)
        elif txt and len(txt) <= 8:
            db.set_setting(f"ai:{key}", None)
            db.set_setting(f"aie:{key}", txt)
        else:
            return await m.answer("Отправьте одно эмодзи (лучше премиум) или <code>-</code>:")
    await state.clear()
    await m.answer("✅ Иконка сохранена.", reply_markup=kb([[B("💎 К иконкам", "a:appi:0")], back("a:app")]))


# ---------- тексты мини-приложения ----------
@router.callback_query(F.data.startswith("a:atxl:"))
async def cb_app_texts(call: CallbackQuery):
    keys = [k for k in APP_TEXTS if k in EDITABLE_TEXTS]
    per = 12
    pages = max(1, (len(keys) + per - 1) // per)
    page = min(max(int(call.data.split(":")[2]), 0), pages - 1)
    rows = []
    for k in keys[page * per:(page + 1) * per]:
        changed = db.get_setting(f"t:{k}:ru") is not None or db.get_setting(f"t:{k}:en") is not None
        rows.append([B(("✏️ " if changed else "") + APP_TEXTS[k][0][:40], f"a:tx:{k}")])
    rows.append(pager("a:atxl:", page, pages))
    rows.append(back("a:app"))
    await render(call, "📝 <b>Тексты мини-приложения</b>\n\nНажмите на текст, чтобы изменить его (RU и EN). "
                       "Можно вставлять <b>премиум-эмодзи</b>, жирный и курсив. ✏️ — уже изменён.", kb(rows))
    await call.answer()


# ---------- статусы ----------
def statuses_text():
    lines = []
    for s in appcfg.statuses():
        icon = "💎" if s.get("emoji_id") else (s.get("emoji") or "•")
        lines.append(f"{icon} <b>{html.escape(s['name'])}</b> — от {money(s['min'])}")
    return "\n".join(lines)


@router.callback_query(F.data == "a:st")
async def cb_statuses(call: CallbackQuery):
    await render(call, "🏅 <b>Статусы покупателей</b>\n\nСтатус зависит от суммы реальных денег, которые покупатель "
                       "внёс в бота: пополнения баланса и оплаты по СБП / звёздами (бонусы и начисления от админа не "
                       f"считаются).\n\n<blockquote>{statuses_text()}</blockquote>", kb([
        [B("✏️ Изменить список", "a:ste", style="primary")],
        [B("♻️ Вернуть стандартные", "a:str")],
        back("a:app"),
    ]))
    await call.answer()


@router.callback_query(F.data == "a:ste")
async def cb_statuses_edit(call: CallbackQuery, state: FSMContext):
    sample = "\n".join(f"{s.get('emoji') or ''} {s['name']} | {int(s['min'])}".strip() for s in appcfg.statuses())
    await ask(call, state, "ste", "✏️ Отправьте список статусов — <b>по одному в строке</b>:\n"
                                  "<code>эмодзи Название | от скольких ₽</code>\n\nСейчас:\n"
                                  f"<code>{html.escape(sample)}</code>\n\n"
                                  "💎 Эмодзи в начале строки может быть <b>премиум</b> — оно станет иконкой статуса. "
                                  "Первый статус должен начинаться с 0.", cancel="a:st")


def _line_emoji(m: Message):
    """Для каждой строки сообщения — id первого премиум-эмодзи в ней (по смещениям UTF-16)."""
    text = m.text or ""
    starts, pos = [], 0
    for line in text.split("\n"):
        starts.append(pos)
        pos += len(line.encode("utf-16-le")) // 2 + 1
    found = {}
    for e in m.entities or []:
        if e.type == "custom_emoji":
            idx = max(i for i, s in enumerate(starts) if s <= e.offset)
            found.setdefault(idx, e.custom_emoji_id)
    return found


@inp("ste")
async def i_statuses(m, state, d, txt, bot):
    icons = _line_emoji(m)
    items = []
    for i, line in enumerate((m.text or "").split("\n")):
        if not line.strip():
            continue
        name, sep, amount = line.rpartition("|")
        v = parse_amount(amount.strip())
        if not sep or v is None or v < 0:
            return await m.answer(f"Строка «{html.escape(line)}»: нужен формат <code>Название | сумма</code>. Ещё раз:")
        name = name.strip()
        emoji = ""
        parts = name.split(" ", 1)
        if len(parts) == 2 and not any(ch.isalnum() for ch in parts[0]):
            emoji, name = parts[0], parts[1].strip()
        item = {"name": name[:24], "min": v, "emoji": emoji[:8]}
        if i in icons:
            item["emoji_id"] = icons[i]
        items.append(item)
    if not items:
        return await m.answer("Список пуст. Отправьте хотя бы один статус:")
    if min(s["min"] for s in items) > 0:
        return await m.answer("Первый статус должен начинаться с 0 (например <code>🍃 Новичок | 0</code>). Ещё раз:")
    appcfg.save_statuses(items)
    await state.clear()
    await m.answer(f"✅ Статусы сохранены:\n\n<blockquote>{statuses_text()}</blockquote>",
                   reply_markup=kb([back("a:st", "◀️ К статусам")]))


@router.callback_query(F.data == "a:str")
async def cb_statuses_reset(call: CallbackQuery):
    db.set_setting("statuses", None)
    await call.answer("Вернул стандартные")
    await cb_statuses(call)


# ---------- бонус ----------
@router.callback_query(F.data == "a:bon")
async def cb_bonus(call: CallbackQuery):
    await render(call, f"🎁 <b>Ежедневный бонус</b>\n\nРаз в 24 часа покупатель может забрать бонус на баланс "
                       f"(в профиле бота и в мини-приложении).\n\nСейчас: {_onoff(appcfg.bonus_on())}, "
                       f"<b>{money(appcfg.bonus_amount())}</b>", kb([
        [B("⏸ Выключить" if appcfg.bonus_on() else "▶️ Включить", "a:bont")],
        [B("💰 Сумма бонуса", "a:bona")],
        back("a:app"),
    ]))
    await call.answer()


@router.callback_query(F.data == "a:bont")
async def cb_bonus_toggle(call: CallbackQuery):
    db.set_setting("bonus_on", "0" if appcfg.bonus_on() else "1")
    await cb_bonus(call)


@router.callback_query(F.data == "a:bona")
async def cb_bonus_amount(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "bona", "💰 Отправьте сумму ежедневного бонуса в ₽ (например <code>3</code>):", cancel="a:bon")


@inp("bona")
async def i_bonus_amount(m, state, d, txt, bot):
    v = parse_amount(txt)
    if v is None or v < 0 or v > 100000:
        return await m.answer("Отправьте число:")
    db.set_setting("bonus_amount", v)
    await done(m, state, f"✅ Бонус: {money(v)} в сутки.", kb([back("a:bon", "◀️ К бонусу")]))


# ---------- пополнение ----------
@router.callback_query(F.data == "a:tus")
async def cb_topup_settings(call: CallbackQuery):
    amounts = ", ".join(money(a) for a in appcfg.topup_amounts())
    await render(call, f"💳 <b>Пополнение баланса</b>\n\n📉 Минимум: <b>{money(appcfg.topup_min())}</b>\n"
                       f"⚡ Быстрые суммы: {amounts}\n\nОплата — по СБП (чек вам на проверку) или звёздами "
                       "(по курсу из ⚙️ Настройки).", kb([
        [B("📉 Минимум", "a:tusm"), B("⚡ Быстрые суммы", "a:tusa")],
        back("a:app"),
    ]))
    await call.answer()


@router.callback_query(F.data.in_({"a:tusm", "a:tusa"}))
async def cb_topup_edit(call: CallbackQuery, state: FSMContext):
    if call.data == "a:tusm":
        await ask(call, state, "tus", "📉 Отправьте минимальную сумму пополнения в ₽:", cancel="a:tus", key="topup_min")
    else:
        await ask(call, state, "tus", "⚡ Отправьте быстрые суммы через запятую, например <code>100, 300, 500, 1000</code>:",
                  cancel="a:tus", key="topup_amounts")


@inp("tus")
async def i_topup_edit(m, state, d, txt, bot):
    if d["key"] == "topup_min":
        v = parse_amount(txt)
        if v is None or v < 1:
            return await m.answer("Отправьте число от 1:")
        db.set_setting("topup_min", v)
    else:
        vals = [parse_amount(p) for p in txt.split(",")]
        vals = [v for v in vals if v and v > 0][:9]
        if not vals:
            return await m.answer("Отправьте суммы через запятую:")
        db.set_setting("topup_amounts", ",".join(str(int(v) if v == int(v) else v) for v in vals))
    await done(m, state, "✅ Сохранено.", kb([back("a:tus", "◀️ К пополнению")]))


# ======================= 💾 База и бэкапы =======================
def _db_size():
    try:
        return f"{os.path.getsize(config.DB_PATH) / 1024:.0f} КБ"
    except OSError:
        return "—"


async def bk_view(target, prefix=""):
    auto = db.get_setting("bk_auto", "1") == "1"
    last = db.get_setting("bk_last") or "ещё не было"
    on_disk = config.DB_PATH.startswith("/data")
    await render(target, f"{prefix}💾 <b>База и бэкапы</b>\n<blockquote>"
                         f"📁 База: <code>{html.escape(config.DB_PATH)}</code> ({_db_size()})\n"
                         f"🔁 Автобэкап раз в сутки владельцам: {_onoff(auto)}\n🕓 Последний: {last}</blockquote>\n"
                         "Всё оформление (тексты, кнопки, мини-приложение, статусы), товары, склад и пользователи "
                         "хранятся в этой базе и <b>не сбрасываются</b> при обновлении кода."
                         + ("" if on_disk or config.CHILD else
                            "\n\n⚠️ <i>База лежит не в постоянном хранилище /data. Если хостинг пересоздаёт папку "
                            "проекта при деплое, данные пропадут — держите автобэкап включённым и восстанавливайте "
                            "базу из файла.</i>"), kb([
        [B("💾 Скачать бэкап сейчас", "a:bkd", style="success")],
        [B("♻️ Восстановить из файла", "a:bkr", style="danger")],
        [B(f"🔁 Автобэкап: {_onoff(auto)}", "a:bka")],
        [B("🎨 Экспорт оформления", "a:bke"), B("📥 Импорт оформления", "a:bki")],
        back(),
    ]))


@router.callback_query(F.data == "a:bk")
async def cb_backup(call: CallbackQuery):
    await bk_view(call)
    await call.answer()


def backup_name(prefix="backup"):
    return f"{prefix}_{config.SHOP_NAME.replace(' ', '_')}_{db.now()[:16].replace(' ', '_').replace(':', '-')}.db"


@router.callback_query(F.data == "a:bkd")
async def cb_backup_download(call: CallbackQuery):
    data = db.backup_bytes()
    await call.message.answer_document(BufferedInputFile(data, backup_name()),
                                       caption="💾 Полная копия базы. Восстановить: 💾 База и бэкапы → ♻️ Восстановить из файла.")
    await call.answer("Готово")


@router.callback_query(F.data == "a:bka")
async def cb_backup_auto(call: CallbackQuery):
    db.set_setting("bk_auto", "0" if db.get_setting("bk_auto", "1") == "1" else "1")
    await bk_view(call)
    await call.answer("Готово")


async def _owner_only(call: CallbackQuery):
    if admins.is_owner(call.from_user.id):
        return True
    await call.answer("Это могут только владельцы бота.", show_alert=True)
    return False


@router.callback_query(F.data == "a:bkr")
async def cb_backup_restore(call: CallbackQuery, state: FSMContext):
    if not await _owner_only(call):
        return
    await ask(call, state, "bkr", "♻️ <b>Восстановление базы</b>\n\nОтправьте файл <code>.db</code> из бэкапа "
                                  "<b>документом</b>.\n\n⚠️ Текущая база будет полностью заменена содержимым файла "
                                  "(товары, пользователи, балансы, оформление). Перед заменой бот пришлёт вам "
                                  "копию текущей базы.", cancel="a:bk")


@inp("bkr")
async def i_backup_restore(m, state, d, txt, bot):
    if not admins.is_owner(m.from_user.id):
        return await done(m, state, "Это могут только владельцы бота.")
    if not m.document:
        return await m.answer("Отправьте файл бэкапа (.db) документом:")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        await bot.download(m.document, destination=path)
        err = db.check_backup(path)
        if err:
            return await m.answer(f"❌ Файл не подходит: {err}. Отправьте другой:")
        await m.answer_document(BufferedInputFile(db.backup_bytes(), backup_name("before_restore")),
                                caption="💾 Копия базы до восстановления — на всякий случай.")
        db.restore_from(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    await state.clear()
    await bk_view(m, "✅ База восстановлена из файла.\n\n")


# ---------- экспорт / импорт оформления ----------
DESIGN_SKIP = {"admins", "bk_last", "bk_auto", "cx_api_key", "cx_api_url", "public_url", "suppliers_cid", "mig_deposited"}


def _is_design(key):
    return key not in DESIGN_SKIP and not key.startswith(("inf:", "doc:"))


@router.callback_query(F.data == "a:bke")
async def cb_design_export(call: CallbackQuery):
    data = {r["key"]: r["value"] for r in db.q("SELECT key, value FROM settings") if _is_design(r["key"])}
    raw = json.dumps({"heliys_design": 1, "settings": data}, ensure_ascii=False, indent=1).encode("utf-8")
    await call.message.answer_document(BufferedInputFile(raw, "design.json"),
                                       caption=f"🎨 Оформление: {len(data)} настроек (тексты, кнопки, мини-приложение, "
                                               "статусы, реквизиты). Импортируйте его в любой бот на этом движке.\n"
                                               "<i>Премиум-эмодзи и картинки работают, только если бот видит эти файлы — "
                                               "фото и видео перенесутся лишь в тот же бот.</i>")
    await call.answer()


@router.callback_query(F.data == "a:bki")
async def cb_design_import(call: CallbackQuery, state: FSMContext):
    if not await _owner_only(call):
        return
    await ask(call, state, "bki", "📥 Отправьте файл <code>design.json</code> (экспорт оформления) документом.\n"
                                  "Совпадающие настройки заменятся, остальные останутся как есть.", cancel="a:bk")


@inp("bki")
async def i_design_import(m, state, d, txt, bot):
    if not m.document:
        return await m.answer("Отправьте файл design.json документом:")
    buf = io.BytesIO()
    await bot.download(m.document, destination=buf)
    try:
        data = json.loads(buf.getvalue().decode("utf-8"))
        items = data["settings"] if isinstance(data, dict) and data.get("heliys_design") else None
        if not isinstance(items, dict):
            raise ValueError
    except (ValueError, KeyError, UnicodeDecodeError):
        return await m.answer("❌ Это не файл оформления. Отправьте design.json из «🎨 Экспорт оформления»:")
    n = 0
    for k, v in items.items():
        if isinstance(k, str) and _is_design(k) and (v is None or isinstance(v, str)):
            db.set_setting(k, v)
            n += 1
    await state.clear()
    await bk_view(m, f"✅ Импортировано настроек: {n}\n\n")


# ---------- автобэкап ----------
async def auto_backup_loop(bot: Bot):
    """Раз в сутки присылает владельцам файл базы (если автобэкап включён)."""
    import asyncio
    import logging
    from datetime import datetime, timedelta
    while True:
        await asyncio.sleep(3600)
        try:
            if db.get_setting("bk_auto", "1") != "1":
                continue
            last = db.get_setting("bk_last")
            if last and datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S") < timedelta(days=1):
                continue
            data = db.backup_bytes()
            for uid in admins.owners():
                try:
                    await bot.send_document(uid, BufferedInputFile(data, backup_name("auto")),
                                            caption="💾 Автобэкап базы за сутки. Отключить: /admin → 💾 База и бэкапы.",
                                            disable_notification=True)
                except Exception as e:
                    logging.info("автобэкап владельцу %s не доставлен: %s", uid, e)
            db.set_setting("bk_last", db.now())
        except Exception as e:
            logging.warning("автобэкап не удался: %s", e)
