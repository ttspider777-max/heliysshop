"""Админ-панель конструктора — тарифы и «📈 Рост и продажи»: чат владельцев, дополнения, партнёры, курс, FAQ,
чаты с пользователями, пуш «открой приложение», «Проверенный магазин», дни напоминаний.

Ввод значений идёт через общий механизм admin.ask → admin.on_input (обработчики регистрируются в admin.EXTRA).
"""
import html
import re

from aiogram import F, Router
from aiogram.types import CallbackQuery

import config
import db
from ctor import admin, core
from ctor.core import money
from ui import fix_url, kb, render

router = Router()
router.message.filter(F.from_user.id.in_(config.ADMINS), F.chat.type == "private")
router.callback_query.filter(F.from_user.id.in_(config.ADMINS))

B, back, ask, onoff = admin.B, admin.back, admin.ask, admin._onoff


def flag_toggle(key):
    core.put(key, "1" if not core.flag_on(key) else "0")


# ======================= 💎 тарифы =======================
async def tariffs_view(target, prefix=""):
    lines = []
    for k, (name, days, _) in core.TARIFFS.items():
        lines.append(f"{name} — <b>{money(core.tariff_price(k))}</b> · {core.tariff_period(k)} · "
                     f"{'✅ вкл' if core.tariff_on(k) else '⏸ выкл'}")
    sold = db.q("SELECT tariff, COUNT(*) n, COALESCE(SUM(amount),0) s FROM ctor_payments WHERE status='paid' "
                "AND kind!='addon' GROUP BY tariff")
    stat = "\n".join(f"{core.tariff_name(r['tariff'] or 'pro')}: {r['n']} шт. на {money(r['s'])}" for r in sold) or "пока нет"
    vip = "✅ загружен" if core.get("vip_file") else "❌ не загружен — VIP-покупателю архив пришлёте вручную"
    text = (f"{prefix}💎 <b>Тарифы</b>\n\n" + "\n".join(lines) + f"\n\n📊 Продано:\n{stat}\n\n👑 Архив VIP: {vip}\n\n"
            "<i>Описания тарифов (что видит покупатель) — кнопки «✏️ Описание». Цена Pro — это «💰 Цена» бота.</i>")
    rows = []
    for k in core.TARIFFS:
        rows.append([B(f"{core.tariff_name(k)}: {money(core.tariff_price(k))}", f"ca2:tp:{k}"),
                     B("✅" if core.tariff_on(k) else "⏸", f"ca2:tt:{k}"),
                     B("✏️ Описание", f"ca:t:tariff_{k}")])
    rows.append([B("👑 Загрузить архив VIP (.zip)", "ca2:vip", style="primary")])
    rows.append(back())
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca2:tar")
async def cb_tariffs(call: CallbackQuery):
    await tariffs_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("ca2:tt:"))
async def cb_tariff_toggle(call: CallbackQuery):
    k = call.data[7:]
    if k in core.TARIFFS:
        on = core.tariff_on(k)
        if on and len(core.tariffs_on()) == 1:
            return await call.answer("Хотя бы один тариф должен быть включён", show_alert=True)
        core.put("toff:" + k, "1" if on else None)
    await tariffs_view(call)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("ca2:tp:"))
async def cb_tariff_price(call: CallbackQuery):
    k = call.data[7:]
    if k not in core.TARIFFS:
        return await call.answer()
    await ask(call, "x_tprice", f"{core.tariff_name(k)}\n\nСейчас: <b>{money(core.tariff_price(k))}</b> · "
                                f"{core.tariff_period(k)}\n\nОтправьте новую цену в рублях (например <code>149</code>).",
              cancel="ca2:tar", key=k)


async def in_tprice(m, w, txt, finish, bot):
    try:
        v = round(float(txt.replace(",", ".").replace("₽", "")), 2)
    except ValueError:
        return await m.answer("Нужно число:")
    if v < 0 or v > 1000000:
        return await m.answer("Слишком много или меньше нуля. Ещё раз:")
    core.put("price" if w["key"] == "pro" else "tp:" + w["key"], v)
    finish()
    await tariffs_view(m, "✅ Сохранено.\n\n")


@router.callback_query(F.data == "ca2:vip")
async def cb_vip(call: CallbackQuery):
    await ask(call, "x_vip", "👑 Пришлите архив с исходным кодом (.zip) <b>файлом</b>. Бот будет отправлять его каждому, "
                             "кто купит VIP.\n\n⚠️ Перед упаковкой уберите папку <code>data/</code>, базы <code>.db</code> "
                             "и файл <code>.env</code> — там данные пользователей и токены.", cancel="ca2:tar")


async def in_vip(m, w, txt, finish, bot):
    if not m.document:
        return await m.answer("Нужен файл (архив .zip):")
    name = (m.document.file_name or "").lower()
    if name.endswith(".db") or name.endswith(".env"):
        return await m.answer("Это не похоже на архив с кодом. Пришлите .zip:")
    core.put("vip_file", m.document.file_id)
    finish()
    await tariffs_view(m, f"✅ Архив «{html.escape(m.document.file_name or 'файл')}» сохранён.\n\n")


# ======================= 📈 рост и продажи =======================
async def growth_view(target, prefix=""):
    chat = core.get("owners_chat")
    partners = db.val("SELECT COUNT(*) FROM ctor_partners") or 0
    unread = db.val("SELECT COUNT(DISTINCT user_id) FROM ctor_chat WHERE created >= datetime('now','localtime','-1 day') "
                    "AND sender='user'") or 0
    text = (f"{prefix}📈 <b>Рост и продажи</b>\n\n<blockquote>"
            f"👥 Чат владельцев: {html.escape(chat) if chat else '— не задан'}\n"
            f"🤝 Партнёров: {partners}\n"
            f"💬 Писали куратору за сутки: {unread}\n"
            f"📚 Курс: {onoff(core.flag_on('course'))} · 📲 Пуш: {onoff(core.flag_on('push'))}\n"
            f"🏅 «Проверенный магазин»: {onoff(core.flag_on('verified'))} от {_need()} продаж</blockquote>")
    await render(target, text, kb([
        [B("👥 Чат владельцев (ссылка)", "ca2:oc", style="primary")],
        [B("🛍 Дополнения", "ca2:ad"), B("🤝 Партнёры", "ca2:pl")],
        [B("📚 Бесплатный курс", "ca2:cr"), B("❓ FAQ", "ca2:fq")],
        [B(f"💬 Чаты с куратором ({unread})", "ca2:ch:0")],
        [B("📲 Пуш «открой приложение»", "ca2:pu"), B("🏅 Проверенный магазин", "ca2:vf")],
        [B("🔔 Дни напоминаний", "ca2:rd")],
        back(),
    ]))


def _need():
    from ctor import growth
    return growth.verified_need()


@router.callback_query(F.data == "ca2:grow")
async def cb_growth(call: CallbackQuery):
    await growth_view(call)
    await call.answer()


# ---------- значения одной строкой ----------
VALUES = {
    "owners_chat": ("👥 Чат владельцев", "Отправьте ссылку-приглашение в чат (<code>https://t.me/+...</code>). Её получит "
                                        "каждый, кто купит тариф, и она появится в «🧾 Мои боты». <code>-</code> — убрать."),
    "push_hours": ("📲 Через сколько часов пуш", "Через сколько часов после /start написать тем, кто не открыл "
                                                "мини-приложение (например <code>3</code>)."),
    "verified_need": ("🏅 Сколько продаж нужно", "Сколько выполненных заказов нужно магазину для значка "
                                                "«✅ Проверенный магазин» (например <code>50</code>)."),
    "remind_days": ("🔔 Дни напоминаний", "За сколько дней до конца пробного / тарифа напоминать владельцу, через запятую "
                                         "(например <code>7,4,3,2,1</code> — за 7, 4, 3 дня и дальше каждый день). За 3 часа и после выключения — всегда."),
}


@router.callback_query(F.data.in_({"ca2:oc", "ca2:rd"}))
async def cb_value(call: CallbackQuery):
    key = {"ca2:oc": "owners_chat", "ca2:rd": "remind_days"}[call.data]
    await _ask_value(call, key, "ca2:grow")


async def _ask_value(call, key, cancel):
    name, prompt = VALUES[key]
    from ctor import bot as cbot
    cur = {"owners_chat": core.get("owners_chat") or "—", "push_hours": core.get("push_hours") or "3",
           "verified_need": str(_need()), "remind_days": ", ".join(map(str, cbot.remind_days()))}[key]
    await ask(call, "x_value", f"<b>{name}</b>\n\nСейчас: {html.escape(cur)}\n\n{prompt}", cancel=cancel, key=key)


async def in_value(m, w, txt, finish, bot):
    key = w["key"]
    if key == "owners_chat":
        if txt == "-":
            core.put(key, None)
        else:
            url = fix_url(txt)
            if not url:
                return await m.answer("Нужна ссылка https://t.me/… :")
            core.put(key, url)
    elif key in ("push_hours", "verified_need"):
        try:
            v = float(txt.replace(",", "."))
        except ValueError:
            return await m.answer("Нужно число:")
        if v <= 0 or v > 100000:
            return await m.answer("Число должно быть больше нуля:")
        core.put(key, v if key == "push_hours" else int(v))
    elif key == "remind_days":
        nums = sorted({int(x) for x in re.findall(r"\d+", txt) if 0 < int(x) <= 60}, reverse=True)
        if not nums:
            return await m.answer("Нужны числа от 1 до 60 через запятую, например <code>7,3,1</code>:")
        core.put(key, ",".join(map(str, nums)))
    finish()
    if key == "push_hours":
        return await push_view(m, "✅ Сохранено.\n\n")
    if key == "verified_need":
        return await verified_view(m, "✅ Сохранено.\n\n")
    await growth_view(m, "✅ Сохранено.\n\n")


# ---------- 🛍 дополнения ----------
async def addons_view(target, prefix=""):
    paid = {r["tariff"]: r["n"] for r in db.q("SELECT tariff, COUNT(*) n FROM ctor_payments WHERE kind='addon' "
                                               "AND status='paid' GROUP BY tariff")}
    lines = [f"{name} — <b>{money(core.addon_price(k))}</b> · {'✅ вкл' if core.addon_on(k) else '⏸ выкл'} · "
             f"куплено {paid.get(k, 0)}" for k, (name, _) in core.ADDONS.items()]
    rows = [[B(f"{core.ADDONS[k][0]}: {money(core.addon_price(k))}", f"ca2:ap:{k}"),
             B("✅" if core.addon_on(k) else "⏸", f"ca2:at:{k}"), B("✏️ Описание", f"ca:t:addon_{k}")]
            for k in core.ADDONS]
    rows.append(back("ca2:grow"))
    await render(target, f"{prefix}🛍 <b>Дополнения к магазину</b>\n\n" + "\n".join(lines) +
                 "\n\n<i>Покупатель видит их в «🧾 Мои боты» и после создания магазина. Когда кто-то оплатит — "
                 "вам придёт уведомление, свяжитесь с ним и выполните заказ.</i>", kb(rows))


@router.callback_query(F.data == "ca2:ad")
async def cb_addons(call: CallbackQuery):
    await addons_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("ca2:at:"))
async def cb_addon_toggle(call: CallbackQuery):
    k = call.data[7:]
    if k in core.ADDONS:
        core.put("aoff:" + k, None if not core.addon_on(k) else "1")
    await addons_view(call)
    await call.answer("Готово")


@router.callback_query(F.data.startswith("ca2:ap:"))
async def cb_addon_price(call: CallbackQuery):
    k = call.data[7:]
    if k not in core.ADDONS:
        return await call.answer()
    await ask(call, "x_aprice", f"{core.ADDONS[k][0]}\n\nСейчас: <b>{money(core.addon_price(k))}</b>\n\n"
                                "Отправьте новую цену в рублях:", cancel="ca2:ad", key=k)


async def in_aprice(m, w, txt, finish, bot):
    try:
        v = round(float(txt.replace(",", ".").replace("₽", "")), 2)
    except ValueError:
        return await m.answer("Нужно число:")
    if v <= 0:
        return await m.answer("Цена должна быть больше нуля:")
    core.put("ap:" + w["key"], v)
    finish()
    await addons_view(m, "✅ Сохранено.\n\n")


# ---------- 🤝 партнёры ----------
async def partners_view(target, prefix=""):
    from ctor import bot as cbot
    rows_db = db.q("SELECT * FROM ctor_partners ORDER BY id DESC LIMIT 30")
    lines = []
    for p in rows_db:
        users, buyers, due = core.partner_stats(p)
        lines.append(f"<b>{html.escape(p['name'] or p['code'])}</b> (<code>p_{html.escape(p['code'])}</code>) — "
                     f"{users} пришло · {buyers} купили · к выплате <b>{money(due)}</b>")
    u = cbot.username()
    text = (f"{prefix}🤝 <b>Партнёры (админы каналов)</b>\n\n" + ("\n".join(lines) if lines else "Пока нет партнёров.")
            + f"\n\n<i>Партнёр получает фиксированную сумму за каждого нового покупателя по своей ссылке "
              f"<code>t.me/{html.escape(u or 'бот')}?start=p_КОД</code>. Свою статистику он видит в боте "
              "(кнопка «🤝 Партнёрка»). Выплачиваете вы сами, потом жмёте «💸 Выплачено».</i>")
    rows = [[B("➕ Добавить партнёра", "ca2:pa", style="success")]]
    rows += [[B(f"{p['name'] or p['code']} · {money(core.partner_stats(p)[2])}", f"ca2:pc:{p['id']}")] for p in rows_db[:15]]
    rows.append(back("ca2:grow"))
    await render(target, text, kb(rows))


@router.callback_query(F.data == "ca2:pl")
async def cb_partners(call: CallbackQuery):
    await partners_view(call)
    await call.answer()


@router.callback_query(F.data == "ca2:pa")
async def cb_partner_add(call: CallbackQuery):
    await ask(call, "x_padd", "➕ <b>Новый партнёр</b>\n\nОтправьте одной строкой: <code>ID КОД СУММА [название]</code>\n\n"
                              "<code>123456789 neon 50 Канал Neon</code> — платим 50₽ за каждого покупателя по ссылке "
                              "<code>?start=p_neon</code>.\n\nID — Telegram ID партнёра (он должен хотя бы раз нажать "
                              "/start в конструкторе).", cancel="ca2:pl")


async def in_padd(m, w, txt, finish, bot):
    parts = txt.split(maxsplit=3)
    if len(parts) < 3 or not parts[0].isdigit():
        return await m.answer("Формат: <code>ID КОД СУММА [название]</code>")
    uid, code = int(parts[0]), parts[1].lower()
    if not re.fullmatch(r"[a-z0-9_]{2,24}", code):
        return await m.answer("Код — латиница, цифры или _ (2–24 символа):")
    try:
        reward = round(float(parts[2].replace(",", ".").replace("₽", "")), 2)
    except ValueError:
        return await m.answer("Сумма — числом, например <code>50</code>:")
    if reward <= 0:
        return await m.answer("Сумма должна быть больше нуля:")
    if not core.user(uid):
        return await m.answer("Этот человек ещё не запускал конструктор — пусть нажмёт /start, и попробуйте снова.")
    if core.partner_by_code(code):
        return await m.answer("Такой код уже занят — придумайте другой:")
    db.x("INSERT INTO ctor_partners(user_id, code, name, reward, created) VALUES (?,?,?,?,?)",
         (uid, code, (parts[3] if len(parts) > 3 else code)[:40], reward, db.now()))
    finish()
    await partners_view(m, f"✅ Партнёр <code>p_{html.escape(code)}</code> добавлен.\n\n")


async def partner_card(target, pid, prefix=""):
    from ctor import bot as cbot
    p = core.partner(pid)
    if not p:
        return await partners_view(target, "Партнёр не найден.\n\n")
    users, buyers, due = core.partner_stats(p)
    u = cbot.username()
    text = (f"{prefix}🤝 <b>{html.escape(p['name'] or p['code'])}</b>\n\n👤 {core.user_link(core.user(p['user_id']))}\n"
            f"🔗 <code>https://t.me/{html.escape(u or 'бот')}?start=p_{html.escape(p['code'])}</code>\n"
            f"💰 За покупателя: <b>{money(p['reward'])}</b>\n\n<blockquote>👥 Пришло: {users}\n💳 Купили: {buyers}\n"
            f"💵 Заработал: {money(p['earned'])}\n✅ Выплачено: {money(p['paid_out'])}\n"
            f"💸 К выплате: <b>{money(due)}</b></blockquote>")
    await render(target, text, kb([
        [B(f"💸 Выплачено {money(due)}", f"ca2:pp:{pid}", style="success")] if due > 0 else [],
        [B("🗑 Удалить партнёра", f"ca2:pd:{pid}", style="danger")],
        back("ca2:pl"),
    ]))


@router.callback_query(F.data.startswith("ca2:pc:"))
async def cb_partner_card(call: CallbackQuery):
    await partner_card(call, int(call.data[7:]))
    await call.answer()


@router.callback_query(F.data.startswith("ca2:pp:"))
async def cb_partner_paid(call: CallbackQuery):
    pid = int(call.data[7:])
    db.x("UPDATE ctor_partners SET paid_out=earned WHERE id=?", (pid,))
    await partner_card(call, pid, "✅ Отмечено как выплачено.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca2:pd:"))
async def cb_partner_del(call: CallbackQuery):
    pid = int(call.data[7:])
    db.x("DELETE FROM ctor_partners WHERE id=?", (pid,))
    await partners_view(call, "🗑 Партнёр удалён (пришедшие по его ссылке остаются пользователями).\n\n")
    await call.answer()


# ---------- 📚 курс ----------
async def course_view(target, prefix=""):
    lessons = core.jget("course", core.COURSE)
    lines = [f"{i + 1}. {html.escape(x.get('t') or core.plain(x.get('x', ''))[:40])}" for i, x in enumerate(lessons)]
    rows = [[B(f"✏️ {i + 1}. {(x.get('t') or '')[:30]}", f"ca2:ce:{i}"), B("🗑", f"ca2:cd:{i}")]
            for i, x in enumerate(lessons[:15])]
    rows.append([B("➕ Добавить урок", "ca2:ce:-1", style="success"), B("👀 Как видит пользователь", "c:course:0")])
    rows.append([B(f"Кнопка «📚 Курс» в меню: {onoff(core.flag_on('course'))}", "ca2:ct"),
                 B("↩️ Как было", "ca2:cr0")])
    rows.append(back("ca2:grow"))
    await render(target, f"{prefix}📚 <b>Бесплатный курс</b> ({len(lessons)} уроков)\n\n" + "\n".join(lines) +
                 "\n\n<i>Пользователь листает уроки кнопкой «Дальше», в последнем — кнопка «Создать магазин». "
                 "Текст урока можно с форматированием и премиум-эмодзи.</i>", kb(rows))


@router.callback_query(F.data == "ca2:cr")
async def cb_course(call: CallbackQuery):
    await course_view(call)
    await call.answer()


@router.callback_query(F.data == "ca2:ct")
async def cb_course_toggle(call: CallbackQuery):
    flag_toggle("course")
    await course_view(call)
    await call.answer("Готово")


@router.callback_query(F.data == "ca2:cr0")
async def cb_course_reset(call: CallbackQuery):
    core.put("course", None)
    await course_view(call, "↩️ Вернул стандартные уроки.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca2:cd:"))
async def cb_course_del(call: CallbackQuery):
    lessons = core.jget("course", core.COURSE)
    i = int(call.data[7:])
    if 0 <= i < len(lessons):
        lessons.pop(i)
        core.jput("course", lessons)
    await course_view(call, "🗑 Урок удалён.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca2:ce:"))
async def cb_course_edit(call: CallbackQuery):
    i = int(call.data[7:])
    lessons = core.jget("course", core.COURSE)
    cur = lessons[i]["x"] if 0 <= i < len(lessons) else ""
    await ask(call, "x_lesson", ("✏️ <b>Урок " + (str(i + 1) if i >= 0 else "новый") + "</b>\n\n"
                                 + (f"Сейчас:\n{cur[:1500]}\n\n" if cur else "")
                                 + "Отправьте текст урока. Первая строка — название в списке."),
              cancel="ca2:cr", idx=i)


async def in_lesson(m, w, txt, finish, bot):
    if not txt:
        return await m.answer("Нужен текст:")
    body = m.html_text
    if len(body) > 3800:
        return await m.answer("Слишком длинно — до 3800 символов:")
    lessons = core.jget("course", core.COURSE)
    item = {"t": core.plain(txt.split("\n", 1)[0])[:60], "x": body}
    i = w["idx"]
    if 0 <= i < len(lessons):
        lessons[i] = item
    else:
        lessons.append(item)
    core.jput("course", lessons)
    finish()
    await course_view(m, "✅ Урок сохранён.\n\n")


# ---------- ❓ FAQ ----------
async def faq_view(target, prefix=""):
    faq = core.jget("faq", core.FAQ)
    rows = [[B(f"🗑 {(f.get('q') or '')[:40]}", f"ca2:fd:{i}")] for i, f in enumerate(faq[:20])]
    rows.append([B("➕ Добавить вопрос", "ca2:fa", style="success"), B("↩️ Как было", "ca2:fr")])
    rows.append(back("ca2:grow"))
    lines = "\n".join(f"{i + 1}. {html.escape(f.get('q') or '')}" for i, f in enumerate(faq))
    await render(target, f"{prefix}❓ <b>FAQ в мини-приложении</b> ({len(faq)})\n\n{lines}\n\n"
                         "<i>В приложении есть поиск по вопросам и ответам.</i>", kb(rows))


@router.callback_query(F.data == "ca2:fq")
async def cb_faq(call: CallbackQuery):
    await faq_view(call)
    await call.answer()


@router.callback_query(F.data == "ca2:fr")
async def cb_faq_reset(call: CallbackQuery):
    core.put("faq", None)
    await faq_view(call, "↩️ Вернул стандартные вопросы.\n\n")
    await call.answer()


@router.callback_query(F.data.startswith("ca2:fd:"))
async def cb_faq_del(call: CallbackQuery):
    faq = core.jget("faq", core.FAQ)
    i = int(call.data[7:])
    if 0 <= i < len(faq):
        faq.pop(i)
        core.jput("faq", faq)
    await faq_view(call, "🗑 Удалено.\n\n")
    await call.answer()


@router.callback_query(F.data == "ca2:fa")
async def cb_faq_add(call: CallbackQuery):
    await ask(call, "x_faq", "➕ Отправьте вопрос и ответ: <b>первая строка — вопрос</b>, дальше — ответ.",
              cancel="ca2:fq")


async def in_faq(m, w, txt, finish, bot):
    q, _, a = txt.partition("\n")
    if not q.strip() or not a.strip():
        return await m.answer("Нужно две части: вопрос в первой строке, ответ — со второй:")
    faq = core.jget("faq", core.FAQ)
    faq.append({"q": q.strip()[:200], "a": a.strip()[:1500]})
    core.jput("faq", faq)
    finish()
    await faq_view(m, "✅ Добавлено.\n\n")


# ---------- 💬 чаты с куратором ----------
async def chats_view(target, page=0, prefix=""):
    users = db.q("SELECT user_id, MAX(id) last FROM ctor_chat GROUP BY user_id ORDER BY last DESC LIMIT 20 OFFSET ?",
                 (page * 20,))
    rows = []
    for r in users:
        u = core.user(r["user_id"])
        m = db.q1("SELECT * FROM ctor_chat WHERE id=?", (r["last"],))
        mark = "🔵 " if m and m["sender"] == "user" else ""
        name = (u["first_name"] if u else None) or str(r["user_id"])
        rows.append([B(f"{mark}{name}: {core.plain(m['text'] if m else '')[:30]}", f"ca2:cv:{r['user_id']}")])
    rows.append(back("ca2:grow"))
    await render(target, f"{prefix}💬 <b>Чаты с куратором</b>\n\n🔵 — последнее сообщение от пользователя (ждёт ответа)."
                 + ("" if users else "\n\nПока никто не писал."), kb(rows))


@router.callback_query(F.data.startswith("ca2:ch:"))
async def cb_chats(call: CallbackQuery):
    await chats_view(call, int(call.data[7:] or 0))
    await call.answer()


async def chat_view(target, uid, prefix=""):
    msgs = core.chat_list(uid, 15)
    lines = [f"{'👤' if x['sender'] == 'user' else '👨‍💼'} <i>{x['created'][5:16]}</i>\n{html.escape(x['text'])}" for x in msgs]
    body = "\n\n".join(lines)
    if len(body) > 3300:
        body = "…" + body[-3300:]
    await render(target, f"{prefix}💬 <b>Чат</b> — {core.user_link(core.user(uid))}\n\n{body or 'пусто'}", kb([
        [B("↩️ Ответить", f"ca:chr:{uid}", style="primary")],
        back("ca2:ch:0"),
    ]))


@router.callback_query(F.data.startswith("ca2:cv:"))
async def cb_chat(call: CallbackQuery):
    await chat_view(call, int(call.data[7:]))
    await call.answer()


@router.callback_query(F.data.startswith("ca:chr:"))
async def cb_chat_reply(call: CallbackQuery):
    uid = int(call.data[7:])
    await ask(call, "x_chr", f"↩️ Ответ для {core.user_link(core.user(uid))} — отправьте текст. Он придёт в чат с "
                             "ботом и появится в мини-приложении.", cancel=f"ca2:cv:{uid}", uid=uid)


async def in_chr(m, w, txt, finish, bot):
    from ctor import growth
    if not txt:
        return await m.answer("Нужен текст:")
    finish()
    ok = await growth.chat_reply(w["uid"], txt)
    await chat_view(m, w["uid"], "✅ Отправлено.\n\n" if ok else "⚠️ В Telegram не доставлено (видно в приложении).\n\n")


# ---------- 📲 пуш ----------
async def push_view(target, prefix=""):
    from ctor import growth
    sent = db.val("SELECT COUNT(*) FROM ctor_users WHERE push_sent=1") or 0
    opened_after = db.val("SELECT COUNT(*) FROM ctor_users WHERE push_sent=1 AND app_opened IS NOT NULL") or 0
    await render(target, f"{prefix}📲 <b>Пуш «открой приложение»</b>\n\nСтатус: <b>{onoff(core.flag_on('push'))}</b>\n"
                         f"Через: <b>{growth.push_hours():g} ч.</b> после /start\nОтправлено: {sent} · открыли потом: "
                         f"{opened_after}\n\n<i>Одно сообщение тем, кто нажал /start, но не открыл мини-приложение и не "
                         "создал бота. Только новичкам (за последние 3 дня).</i>", kb([
                             [B(f"📲 Пуш: {onoff(core.flag_on('push'))}", "ca2:put"), B("⏱ Через сколько часов", "ca2:puh")],
                             [B("✏️ Текст пуша", "ca:t:push_app")],
                             back("ca2:grow"),
                         ]))


@router.callback_query(F.data == "ca2:pu")
async def cb_push(call: CallbackQuery):
    await push_view(call)
    await call.answer()


@router.callback_query(F.data == "ca2:put")
async def cb_push_toggle(call: CallbackQuery):
    flag_toggle("push")
    await push_view(call)
    await call.answer("Готово")


@router.callback_query(F.data == "ca2:puh")
async def cb_push_hours(call: CallbackQuery):
    await _ask_value(call, "push_hours", "ca2:pu")


# ---------- 🏅 проверенный магазин ----------
async def verified_view(target, prefix=""):
    n = db.val("SELECT COUNT(*) FROM hosted_bots WHERE source='ctor' AND verified=1") or 0
    await render(target, f"{prefix}🏅 <b>«Проверенный магазин»</b>\n\nСтатус: <b>{onoff(core.flag_on('verified'))}</b>\n"
                         f"Нужно продаж: <b>{_need()}</b>\nУже получили: {n}\n\n<i>Магазин, набравший нужное число "
                         "выполненных заказов, получает значок «✅ Проверенный магазин» — он виден покупателям в "
                         "приветствии и мини-приложении. Проверка — раз в полчаса.</i>", kb([
                             [B(f"🏅 Значок: {onoff(core.flag_on('verified'))}", "ca2:vft"),
                              B("🔢 Сколько продаж", "ca2:vfn")],
                             back("ca2:grow"),
                         ]))


@router.callback_query(F.data == "ca2:vf")
async def cb_verified(call: CallbackQuery):
    await verified_view(call)
    await call.answer()


@router.callback_query(F.data == "ca2:vft")
async def cb_verified_toggle(call: CallbackQuery):
    flag_toggle("verified")
    await verified_view(call)
    await call.answer("Готово")


@router.callback_query(F.data == "ca2:vfn")
async def cb_verified_need(call: CallbackQuery):
    await _ask_value(call, "verified_need", "ca2:vf")


# ======================= возврат и ввод =======================
async def route(call: CallbackQuery, target):
    """Отмена ввода: вернуть на экран, откуда начали (admin.route_back → сюда для «ca2:…»)."""
    views = {"ca2:tar": tariffs_view, "ca2:grow": growth_view, "ca2:ad": addons_view, "ca2:pl": partners_view,
             "ca2:cr": course_view, "ca2:fq": faq_view, "ca2:pu": push_view, "ca2:vf": verified_view}
    if target in views:
        return await views[target](call)
    if target.startswith("ca2:cv:"):
        return await chat_view(call, int(target[7:]))
    if target.startswith("ca2:ch:"):
        return await chats_view(call)
    await growth_view(call)


admin.EXTRA.update({
    "x_tprice": in_tprice, "x_vip": in_vip, "x_value": in_value, "x_aprice": in_aprice, "x_padd": in_padd,
    "x_lesson": in_lesson, "x_faq": in_faq, "x_chr": in_chr,
})
