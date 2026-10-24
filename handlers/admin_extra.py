"""Админ-панель, часть 2: внешние магазины (API), документы для оплаты и быстрое скрытие кнопок.

Хендлеры регистрируются на общем роутере админки (handlers.admin.router), поэтому доступны только админам.
"""
import html
import io
import json

from aiogram import Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import admins
import config
import db
import ext
import web
from services import safe_send
from handlers.admin import B, ask, back, done, inp, parse_amount, router, toggle_hidden  # noqa: E402
from legal_templates import TEMPLATES, has_placeholders
from texts import bt, money
from ui import VIS_GROUPS, doc_text, fix_url, has_docs, is_hidden, kb, render, strip_emoji

DOC_TITLES = {"privacy": "🔒 Политика конфиденциальности", "terms": "📜 Пользовательское соглашение"}


async def forget_message(m: Message):
    """Удаляет сообщение админа с секретом (API-ключ) из чата."""
    try:
        await m.delete()
    except Exception:
        pass


# ======================= скрытие кнопок =======================
async def vis_view(target):
    rows = []
    for title, keys in VIS_GROUPS:
        rows.append([B(title, "noop")])
        row = []
        for key in keys:
            mark = "🙈" if is_hidden(key) else "✅"
            row.append(B(f"{mark} {strip_emoji(bt(key, 'ru'))}", f"a:vt:{key}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    rows.append([B("🔗 Свои кнопки главного меню (удалить)", "a:cbtns")])
    rows.append(back())
    await render(target, "🙈 <b>Скрыть кнопки</b>\n\nНажмите на кнопку, чтобы убрать её из бота (🙈) или вернуть (✅). "
                         "Изменение действует сразу для всех покупателей.\n\n"
                         "<i>Тексты и цвета кнопок меняются в «✏️ Оформление → 🔘 Кнопки». Кнопки-ссылки, "
                         "которые вы добавили сами, удаляются в разделе «Свои кнопки».</i>", kb(rows))


@router.callback_query(F.data == "a:vis")
async def cb_vis(call: CallbackQuery):
    await vis_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("a:vt:"))
async def cb_vis_toggle(call: CallbackQuery):
    key = call.data[5:]
    err = toggle_hidden(key)
    if err:
        return await call.answer(err, show_alert=True)
    await vis_view(call)
    await call.answer("Кнопка скрыта" if is_hidden(key) else "Кнопка снова показана")


# ======================= документы =======================
def doc_status(name):
    text = doc_text(name)
    if not text:
        return "❌ не задан"
    if has_placeholders(text):
        return "⚠️ есть незаполненные поля [УКАЖИТЕ…]"
    return f"✅ опубликован ({len(text)} симв.)"


def save_doc(name, text):
    db.set_setting(f"doc:{name}", text)
    db.set_setting(f"doc:{name}:ts", db.now() if text else None)


async def docs_view(target, prefix=""):
    seller = db.get_setting("seller_info")
    base = web.public_url()
    lines = [f"{prefix}📄 <b>Документы для подключения оплаты</b>\n",
             "Платёжные системы (Robokassa, ЮKassa и др.) просят ссылки на политику конфиденциальности и "
             "пользовательское соглашение. Тексты можно менять в любой момент — в боте и на сайте они "
             "обновятся сразу.\n"]
    for name, title in DOC_TITLES.items():
        link = web.doc_link(name)
        lines.append(f"{title}: {doc_status(name)}\n   🔗 {'<code>' + html.escape(link) + '</code>' if link else 'ссылки пока нет'}")
    lines.append("")
    lines.append(f"🏢 Реквизиты продавца: {'указаны' if seller else 'не указаны'}")
    lines.append(f"🌐 Адрес сайта бота: {html.escape(base) if base else 'не указан'}")
    lines.append(f"🧾 Согласие при входе: {'включено' if db.get_setting('terms_gate') == '1' else 'выключено'}")
    if not base:
        lines.append("\n<i>Чтобы получить ссылки, укажите адрес сайта бота (например, домен проекта на хостинге) "
                     "кнопкой «🌐 Адрес сайта» — бот сам публикует страницы /privacy и /terms. Либо у каждого "
                     "документа можно указать свою ссылку (например, на Telegraph).</i>")
    gate_on = db.get_setting("terms_gate") == "1"
    rows = [
        [B("🔒 Политика", "a:doc:privacy"), B("📜 Соглашение", "a:doc:terms")],
        [B("🏢 Реквизиты продавца", "a:seller"), B("🌐 Адрес сайта", "a:pubu")],
        [B("⏸ Выключить согласие при входе" if gate_on else "✅ Требовать согласие при входе", "a:gate",
           style="danger" if gate_on else "success")],
        back(),
    ]
    await render(target, "\n".join(lines), kb(rows))


@router.callback_query(F.data == "a:docs")
async def cb_docs(call: CallbackQuery):
    await docs_view(call)
    await call.answer()


async def doc_view(target, name, prefix=""):
    text = doc_text(name)
    link = web.doc_link(name)
    own = db.get_setting(f"doc_url:{name}")
    lines = [f"{prefix}{DOC_TITLES[name]}\n", f"Статус: {doc_status(name)}",
             f"🔗 Ссылка: {'<code>' + html.escape(link) + '</code>' if link else 'нет (укажите адрес сайта или свою ссылку)'}"
             + (" (своя)" if own else "")]
    if text and has_placeholders(text):
        lines.append("\n⚠️ В тексте остались места «[УКАЖИТЕ: …]» — замените их и загрузите итоговый текст кнопкой «✏️ Загрузить текст».")
    rows = [
        [B("✏️ Загрузить текст", f"a:dtx:{name}", style="success")],
        [B("📝 Вставить шаблон", f"a:dtp:{name}"), B("👁 Как видит покупатель", f"legal:{name}:0")],
        [B("🔗 Своя ссылка", f"a:dur:{name}")] + ([B("🗑 Удалить документ", f"a:ddl:{name}", style="danger")] if text else []),
        back("a:docs", "◀️ К документам"),
    ]
    await render(target, "\n".join(lines), kb(rows))


@router.callback_query(F.data.startswith("a:doc:"))
async def cb_doc(call: CallbackQuery):
    await doc_view(call, call.data[6:])
    await call.answer()


@router.callback_query(F.data.startswith("a:dtx:"))
async def cb_doc_text(call: CallbackQuery, state: FSMContext):
    name = call.data[6:]
    await ask(call, state, "doc_text",
              f"✏️ <b>{DOC_TITLES[name]}</b>\n\nОтправьте текст документа сообщением — форматирование (жирный, курсив, ссылки) "
              "сохранится. Если текст длиннее 4000 символов, отправьте его <b>.txt файлом</b>.\n\n"
              "Старый текст будет заменён.", cancel=f"a:doc:{name}", name=name)


@inp("doc_text")
async def i_doc_text(m, state, d, txt, bot):
    name = d["name"]
    if m.document:
        if (m.document.file_size or 0) > 1_000_000:
            return await m.answer("Файл слишком большой (максимум 1 МБ). Отправьте файл поменьше:")
        buf = io.BytesIO()
        await bot.download(m.document, destination=buf)
        text = html.escape(buf.getvalue().decode("utf-8-sig", errors="ignore").replace("\r\n", "\n").strip())
    else:
        text = m.html_text if m.text else ""
    if not text:
        return await m.answer("Нужен текст документа или .txt файл:")
    save_doc(name, text)
    await state.clear()
    await doc_view(m, name, "✅ Сохранено — в боте и на сайте уже новая редакция.\n\n")


@router.callback_query(F.data.startswith("a:dtp:"))
async def cb_doc_template(call: CallbackQuery):
    name = call.data[6:]
    if doc_text(name):
        await render(call, f"{DOC_TITLES[name]}\n\nДокумент уже заполнен. Заменить его шаблоном? Текущий текст пропадёт.",
                     kb([[B("Да, заменить шаблоном", f"a:dtp2:{name}", style="danger")], back(f"a:doc:{name}", "Отмена")]))
        return await call.answer()
    await apply_template(call, name)


@router.callback_query(F.data.startswith("a:dtp2:"))
async def cb_doc_template2(call: CallbackQuery):
    await apply_template(call, call.data[7:])


async def apply_template(call, name):
    save_doc(name, TEMPLATES[name]())
    await doc_view(call, name, "📝 Шаблон вставлен. Это заготовка, а не юридическая консультация: замените места "
                                "«[УКАЖИТЕ: …]» и проверьте условия под свой магазин.\n\n")
    await call.answer("Шаблон вставлен")


@router.callback_query(F.data.startswith("a:ddl:"))
async def cb_doc_delete(call: CallbackQuery):
    name = call.data[6:]
    save_doc(name, None)
    await doc_view(call, name, "🗑 Документ удалён.\n\n")
    await call.answer("Удалено")


@router.callback_query(F.data.startswith("a:dur:"))
async def cb_doc_url(call: CallbackQuery, state: FSMContext):
    name = call.data[6:]
    await ask(call, state, "doc_url", f"🔗 Отправьте свою ссылку на «{DOC_TITLES[name]}» (например, страница в Telegraph или на вашем сайте).\n"
                                      "<code>-</code> — убрать и использовать страницу самого бота.", cancel=f"a:doc:{name}", name=name)


@inp("doc_url")
async def i_doc_url(m, state, d, txt, bot):
    if txt == "-":
        db.set_setting(f"doc_url:{d['name']}", None)
    else:
        url = fix_url(txt)
        if not url or not url.startswith("http"):
            return await m.answer("Не похоже на ссылку. Отправьте адрес вида https://… или <code>-</code>:")
        db.set_setting(f"doc_url:{d['name']}", url)
    await state.clear()
    await doc_view(m, d["name"], "✅ Сохранено\n\n")


@router.callback_query(F.data == "a:seller")
async def cb_seller(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "seller",
              "🏢 <b>Реквизиты продавца</b>\n\nОтправьте данные, которые покупатели увидят под документами и на сайте: "
              "ФИО или название ИП/ООО/самозанятого, ИНН (ОГРНИП), e-mail и/или контакт для связи.\n\n"
              "Например:\n<code>ИП Иванов Иван Иванович\nИНН 123456789012\ne-mail: shop@example.com</code>\n\n"
              "<code>-</code> — убрать.", cancel="a:docs")


@inp("seller")
async def i_seller(m, state, d, txt, bot):
    if not txt:
        return await m.answer("Отправьте реквизиты текстом:")
    if txt == "-":
        db.set_setting("seller_info", None)
    elif len(txt) > 700:
        return await m.answer("Слишком длинно (максимум 700 символов). Сократите:")
    else:
        db.set_setting("seller_info", m.html_text)
    await state.clear()
    await docs_view(m, "✅ Сохранено\n\n")


@router.callback_query(F.data == "a:pubu")
async def cb_pubu(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "pubu",
              "🌐 <b>Адрес сайта бота</b>\n\nБот сам публикует страницы <code>/privacy</code> и <code>/terms</code>. "
              "Отправьте публичный адрес вашего проекта на хостинге, например "
              "<code>https://heliys-shop.amvera.io</code> — из него получатся ссылки для платёжной системы.\n\n"
              f"<i>Бот слушает порт {config.WEB_PORT}; на Amvera включите для проекта домен (порт 80).</i>\n"
              "<code>-</code> — убрать.", cancel="a:docs")


@inp("pubu")
async def i_pubu(m, state, d, txt, bot):
    if txt == "-":
        db.set_setting("public_url", None)
    else:
        url = txt.strip().rstrip("/")
        if not url.startswith("http"):
            url = "https://" + url
        if "." not in url:
            return await m.answer("Не похоже на адрес сайта. Пример: <code>https://heliys-shop.amvera.io</code>")
        db.set_setting("public_url", url)
    await state.clear()
    await docs_view(m, "✅ Сохранено\n\n")


@router.callback_query(F.data == "a:gate")
async def cb_gate(call: CallbackQuery):
    if db.get_setting("terms_gate") != "1":
        if not has_docs():
            return await call.answer("Сначала добавьте хотя бы один документ", show_alert=True)
        db.set_setting("terms_gate", "1")  # согласие потребуется от всех, кто ещё не нажимал «Принимаю»
    else:
        db.set_setting("terms_gate", None)
    await docs_view(call)
    await call.answer("Готово")


# ======================= внешние магазины (API) =======================
def mask(key):
    return "—" if not key else "••••" + key[-4:] if len(key) > 8 else "••••"


async def xs_list(target, prefix=""):
    shops = db.ext_shops()
    lines = [f"{prefix}🔌 <b>Внешние магазины (API)</b>\n",
             "Подключайте другие магазины по API: бот загрузит их товары с вашей наценкой. Когда покупатель "
             "оплачивает такой товар, бот сам заказывает его у магазина-поставщика и выдаёт покупателю.\n"]
    if not shops:
        lines.append("Пока ничего не подключено.")
    rows = []
    for s in shops:
        n = len(db.ext_products(s["id"]))
        rows.append([B(f"{'🟢' if s['active'] else '⏸'} {s['name']} — {n} тов.", f"a:xs:{s['id']}")])
    rows.append([B("➕ Подключить магазин", "a:xsadd", style="success")])
    rows.append(back())
    await render(target, "\n".join(lines), kb(rows))


@router.callback_query(F.data == "a:xs")
async def cb_xs(call: CallbackQuery):
    await xs_list(call)
    await call.answer()


async def xs_view(target, sid, prefix=""):
    s = db.ext_shop(sid)
    if not s:
        return await xs_list(target, "Магазин не найден.\n\n")
    n = len(db.ext_products(sid))
    body = ext.DEFAULT_BUY_BODY if not s["buy_body"] else s["buy_body"]
    text = (f"{prefix}🔌 <b>{html.escape(s['name'])}</b> — {'🟢 включён' if s['active'] else '⏸ выключен'}\n\n"
            f"🌐 Адрес: <code>{html.escape(s['base_url'])}</code>\n"
            f"🔑 API-ключ: <code>{mask(s['api_key'])}</code>\n"
            f"💲 Наценка: <b>{s['markup']:g}%</b>\n"
            f"📦 Товаров импортировано: <b>{n}</b>\n"
            f"🕓 Синхронизация: {s['last_sync'] or 'ещё не было'}\n"
            f"📥 Список товаров: GET <code>{html.escape(s['list_path'])}</code>\n"
            f"🛒 Покупка: {s['buy_method']} <code>{html.escape(s['buy_path'])}</code>\n"
            f"🧾 Тело покупки: <code>{html.escape(body)}</code>")
    if s["last_error"]:
        text += f"\n\n⚠️ <b>Последняя ошибка:</b> {html.escape(s['last_error'][:400])}"
    text += "\n\n<i>Остатки и цены обновляются автоматически каждые 10 минут.</i>"
    rows = [
        [B("🔄 Синхронизировать товары", f"a:xsy:{sid}", style="success"), B("🧪 Проверить", f"a:xst:{sid}")],
        [B("💲 Наценка", f"a:xse:markup:{sid}"), B("✏️ Название", f"a:xse:name:{sid}")],
        [B("🌐 Адрес", f"a:xse:base_url:{sid}"), B("🔑 API-ключ", f"a:xse:api_key:{sid}")],
        [B("⚙️ Расширенные настройки API", f"a:xsa:{sid}")],
        [B("⏸ Выключить" if s["active"] else "▶️ Включить", f"a:xsn:{sid}"),
         B("🗑 Удалить", f"a:xsd:{sid}", style="danger")],
        back("a:xs", "◀️ К магазинам"),
    ]
    await render(target, text, kb(rows))


@router.callback_query(F.data.startswith("a:xs:"))
async def cb_xs_view(call: CallbackQuery):
    await xs_view(call, int(call.data.split(":")[2]))
    await call.answer()


# ---------- добавление ----------
@router.callback_query(F.data == "a:xsadd")
async def cb_xs_add(call: CallbackQuery, state: FSMContext):
    await ask(call, state, "xs_name", "➕ <b>Подключение магазина</b>\n\nШаг 1/4 — отправьте <b>название</b> магазина "
                                      "(по нему будет называться категория в каталоге):", cancel="a:xs")


@inp("xs_name")
async def i_xs_name(m, state, d, txt, bot):
    if not txt:
        return await m.answer("Отправьте название текстом:")
    await state.update_data(act="xs_url", name=txt[:50])
    await m.answer("Шаг 2/4 — отправьте <b>адрес API</b> магазина (из его документации), без пути метода:\n"
                   "<code>https://shop.example.com/api/v1</code>")


@inp("xs_url")
async def i_xs_url(m, state, d, txt, bot):
    if not txt.startswith(("http://", "https://")):
        return await m.answer("Адрес должен начинаться с <code>https://</code>. Попробуйте ещё раз:")
    await state.update_data(act="xs_key", url=txt.strip().rstrip("/"))
    await m.answer("Шаг 3/4 — отправьте <b>API-ключ</b> (токен) магазина. Если ключ не нужен — отправьте <code>-</code>.\n"
                   "<i>Сообщение с ключом бот сразу удалит из чата.</i>")


@inp("xs_key")
async def i_xs_key(m, state, d, txt, bot):
    if not txt:
        return await m.answer("Отправьте ключ текстом или <code>-</code>:")
    await forget_message(m)
    await state.update_data(act="xs_markup", key="" if txt == "-" else txt)
    await m.answer("Шаг 4/4 — какую <b>наценку в %</b> добавить к цене поставщика? Например <code>20</code> — "
                   "товар за 100₽ у них вы продаёте за 120₽. <code>0</code> — без наценки.")


@inp("xs_markup")
async def i_xs_markup(m, state, d, txt, bot):
    v = parse_amount(txt.replace("%", ""))
    if v is None or not 0 <= v <= 1000:
        return await m.answer("Отправьте число от 0 до 1000:")
    sid = db.add_ext_shop(d["name"], d["url"], d["key"], v)
    await state.clear()
    await m.answer("⏳ Подключаюсь и загружаю товары…")
    await sync_and_show(m, sid)


async def sync_and_show(target, sid):
    try:
        added, updated, total = await ext.sync_shop(sid)
        prefix = f"✅ Готово: найдено {total} товаров, добавлено {added}, обновлено {updated}.\n\n"
    except Exception as e:
        prefix = (f"❌ Не удалось загрузить товары: {html.escape(str(e))}\n\nПроверьте адрес и ключ, при необходимости "
                  "откройте «⚙️ Расширенные настройки API» (пути методов и способ авторизации), затем нажмите «🔄 Синхронизировать».\n\n")
    await xs_view(target, sid, prefix)


# ---------- действия ----------
@router.callback_query(F.data.startswith("a:xsy:"))
async def cb_xs_sync(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    await call.answer("⏳ Синхронизирую…")
    await sync_and_show(call, sid)


@router.callback_query(F.data.startswith("a:xst:"))
async def cb_xs_test(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    shop = db.ext_shop(sid)
    await call.answer("⏳ Проверяю…")
    try:
        prods = await ext.fetch_products(shop)
        sample = "\n".join(f"• {html.escape(p['name'])} — {money(p['cost'])}, остаток "
                           f"{'?' if p['stock'] < 0 else p['stock']}" for p in prods[:6])
        prefix = f"✅ Подключение работает: товаров в ответе — {len(prods)}.\n{sample}\n\n"
    except Exception as e:
        prefix = f"❌ Ошибка: {html.escape(str(e))}\n\n"
    await xs_view(call, sid, prefix)


@router.callback_query(F.data.startswith("a:xsn:"))
async def cb_xs_toggle(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    shop = db.ext_shop(sid)
    new = 0 if shop["active"] else 1
    db.update_ext_shop(sid, active=new)
    db.x("UPDATE products SET active=? WHERE ext_shop=?", (new, sid))  # выключенный магазин скрывает свои товары
    await xs_view(call, sid)
    await call.answer("Включён" if new else "Выключен — товары скрыты из каталога")


@router.callback_query(F.data.startswith("a:xsd:"))
async def cb_xs_del(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    await render(call, "🗑 Удалить магазин вместе со всеми его товарами в каталоге? Это нельзя отменить.\n"
                       "Прошлые заказы останутся в истории.",
                 kb([[B("Да, удалить", f"a:xsd2:{sid}", style="danger")], back(f"a:xs:{sid}", "Отмена")]))
    await call.answer()


@router.callback_query(F.data.startswith("a:xsd2:"))
async def cb_xs_del2(call: CallbackQuery):
    db.delete_ext_shop(int(call.data.split(":")[2]))
    await xs_list(call, "🗑 Магазин удалён.\n\n")
    await call.answer("Удалено")


# ---------- редактирование полей ----------
FIELD_PROMPTS = {
    "name": "✏️ Отправьте новое название магазина:",
    "base_url": "🌐 Отправьте новый адрес API (https://…):",
    "api_key": "🔑 Отправьте новый API-ключ (<code>-</code> — убрать). Сообщение с ключом бот удалит.",
    "markup": "💲 Отправьте наценку в % (например <code>20</code>). Цены всех товаров магазина пересчитаются сразу.",
    "list_path": "📥 Отправьте путь метода «список товаров» (например <code>/products</code>) или полный URL:",
    "buy_path": "🛒 Отправьте путь метода «покупка» (например <code>/buy</code>) или полный URL:",
    "auth_name": "🏷 Отправьте имя заголовка или параметра с ключом (например <code>X-Api-Key</code> или <code>api_key</code>):",
    "buy_body": "🧾 Отправьте шаблон тела запроса покупки в формате JSON. В нём <code>\"$id\"</code> заменится на ID товара "
                "у поставщика, <code>\"$qty\"</code> — на количество.\nНапример:\n"
                "<code>{\"product_id\": \"$id\", \"quantity\": \"$qty\"}</code>\n<code>-</code> — вернуть по умолчанию.",
}


@router.callback_query(F.data.startswith("a:xse:"))
async def cb_xs_edit(call: CallbackQuery, state: FSMContext):
    _, _, field, sid = call.data.split(":")
    back_cb = f"a:xsa:{sid}" if field in ("list_path", "buy_path", "auth_name", "buy_body") else f"a:xs:{sid}"
    await ask(call, state, "xs_edit", FIELD_PROMPTS[field], cancel=back_cb, field=field, sid=int(sid), back=back_cb)


@inp("xs_edit")
async def i_xs_edit(m, state, d, txt, bot):
    field, sid = d["field"], d["sid"]
    shop = db.ext_shop(sid)
    if not shop:
        return await done(m, state, "Магазин не найден.")
    if not txt:
        return await m.answer("Отправьте текст:")
    if field == "api_key":
        await forget_message(m)
        db.update_ext_shop(sid, api_key="" if txt == "-" else txt)
    elif field == "name":
        db.update_ext_shop(sid, name=txt[:50])
        if shop["category_id"] and db.category(shop["category_id"]):
            db.update_category(shop["category_id"], name=f"🔌 {txt[:50]}")
    elif field == "base_url":
        if not txt.startswith(("http://", "https://")):
            return await m.answer("Адрес должен начинаться с https://. Попробуйте ещё раз:")
        db.update_ext_shop(sid, base_url=txt.strip().rstrip("/"))
    elif field == "markup":
        v = parse_amount(txt.replace("%", ""))
        if v is None or not 0 <= v <= 1000:
            return await m.answer("Отправьте число от 0 до 1000:")
        db.update_ext_shop(sid, markup=v)
        ext.reprice(sid)
    elif field in ("list_path", "buy_path"):
        path = txt if txt.startswith(("/", "http")) else "/" + txt
        db.update_ext_shop(sid, **{field: path})
    elif field == "auth_name":
        db.update_ext_shop(sid, auth_name=txt)
    elif field == "buy_body":
        if txt == "-":
            db.update_ext_shop(sid, buy_body="")
        else:
            try:
                if not isinstance(json.loads(txt), dict):
                    raise ValueError
            except ValueError:
                return await m.answer("Это не JSON-объект. Нужен вид <code>{\"product_id\": \"$id\", \"quantity\": \"$qty\"}</code>. "
                                      "Попробуйте ещё раз:")
            db.update_ext_shop(sid, buy_body=txt)
    await state.clear()
    if d["back"].startswith("a:xsa:"):
        await xs_adv_view(m, sid, "✅ Сохранено\n\n")
    else:
        await xs_view(m, sid, "✅ Сохранено\n\n")


# ---------- расширенные настройки ----------
async def xs_adv_view(target, sid, prefix=""):
    s = db.ext_shop(sid)
    mode = s["auth_mode"] or "bearer"
    name = s["auth_name"] or ext.AUTH_DEFAULT_NAME.get(mode, "")
    text = (f"{prefix}⚙️ <b>Расширенные настройки API — {html.escape(s['name'])}</b>\n\n"
            f"Бот подстраивается под популярные форматы, но у каждого магазина API свой. Эти настройки берутся из "
            f"документации магазина.\n\n"
            f"🔐 Авторизация: <b>{ext.AUTH_TITLES[mode]}</b>"
            + (f", имя: <code>{html.escape(name)}</code>" if mode != "bearer" else "") + "\n"
            f"📥 Список товаров: GET <code>{html.escape(s['list_path'])}</code>\n"
            f"🛒 Покупка: <b>{s['buy_method']}</b> <code>{html.escape(s['buy_path'])}</code>\n"
            f"🧾 Тело покупки: <code>{html.escape(s['buy_body'] or ext.DEFAULT_BUY_BODY)}</code>\n\n"
            "<i>Ответ магазина разбирается автоматически: список товаров ищется в корне или в полях "
            "data/products/items/result, а выданный товар — в полях items/accounts/data/content.</i>")
    rows = [
        [B("🔐 Тип авторизации", f"a:xsm:{sid}")] + ([B("🏷 Имя параметра", f"a:xse:auth_name:{sid}")] if mode != "bearer" else []),
        [B("📥 Путь списка", f"a:xse:list_path:{sid}"), B("🛒 Путь покупки", f"a:xse:buy_path:{sid}")],
        [B(f"Метод покупки: {s['buy_method']} (сменить)", f"a:xsb:{sid}"), B("🧾 Тело запроса", f"a:xse:buy_body:{sid}")],
        back(f"a:xs:{sid}"),
    ]
    await render(target, text, kb(rows))


@router.callback_query(F.data.startswith("a:xsa:"))
async def cb_xs_adv(call: CallbackQuery):
    await xs_adv_view(call, int(call.data.split(":")[2]))
    await call.answer()


@router.callback_query(F.data.startswith("a:xsm:"))
async def cb_xs_auth(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    cur = db.ext_shop(sid)["auth_mode"] or "bearer"
    nxt = ext.AUTH_MODES[(ext.AUTH_MODES.index(cur) + 1) % len(ext.AUTH_MODES)]
    db.update_ext_shop(sid, auth_mode=nxt, auth_name="")
    await xs_adv_view(call, sid)
    await call.answer(ext.AUTH_TITLES[nxt])


@router.callback_query(F.data.startswith("a:xsb:"))
async def cb_xs_method(call: CallbackQuery):
    sid = int(call.data.split(":")[2])
    cur = db.ext_shop(sid)["buy_method"]
    db.update_ext_shop(sid, buy_method="GET" if cur == "POST" else "POST")
    await xs_adv_view(call, sid)
    await call.answer()


# ======================= админы =======================
def _adm_name(uid):
    u = db.get_user(uid)
    if not u:
        return f"<code>{uid}</code>"
    name = html.escape(u["first_name"] or "без имени")
    uname = f" @{html.escape(u['username'])}" if u["username"] else ""
    return f"{name}{uname} <code>{uid}</code>"


def _adm_btn_name(uid):
    u = db.get_user(uid)
    name = (u["first_name"] or u["username"] or str(uid)) if u else str(uid)
    return f"{name} ({uid})"


async def adm_view(target, prefix=""):
    owners = sorted(admins.owners())
    extra = sorted(admins.extra())
    lines = [f"{prefix}👮 <b>Админы</b>\n",
             "🔒 <b>Владельцы</b> (прописаны в config.py, удалить нельзя):"]
    lines += [f"• {_adm_name(i)}" for i in owners]
    lines.append("\n👤 <b>Добавленные админы:</b>")
    lines += [f"• {_adm_name(i)}" for i in extra] or ["— пока никого"]
    lines.append("\nАдмины видят админ-панель, получают чеки и заказы на ручную выдачу. "
                 "Добавлять и удалять админов могут только владельцы.")
    rows = [[B(f"❌ {_adm_btn_name(i)}", f"a:admdel:{i}")] for i in extra]
    rows.append([B("➕ Добавить админа", "a:admadd", style="success")])
    rows.append(back())
    await render(target, "\n".join(lines), kb(rows))


async def _owner_only(call: CallbackQuery):
    if admins.is_owner(call.from_user.id):
        return True
    await call.answer("Управлять админами могут только владельцы бота.", show_alert=True)
    return False


@router.callback_query(F.data == "a:adm")
async def cb_adm(call: CallbackQuery):
    if not await _owner_only(call):
        return
    await adm_view(call)
    await call.answer()


@router.callback_query(F.data == "a:admadd")
async def cb_adm_add(call: CallbackQuery, state: FSMContext):
    if not await _owner_only(call):
        return
    await ask(call, state, "admadd",
              "➕ <b>Новый админ</b>\n\nОтправьте одно из:\n• числовой ID (<code>123456789</code>)\n"
              "• @username — если человек уже запускал бота\n• пересланное сообщение от него",
              cancel="a:adm")


@inp("admadd")
async def i_adm_add(m: Message, state, d, txt, bot):
    if not admins.is_owner(m.from_user.id):
        return await done(m, state, "Управлять админами могут только владельцы бота.")
    uid = None
    if m.forward_from:
        uid = m.forward_from.id
    elif m.forward_origin:
        return await m.answer("У пользователя скрыт профиль при пересылке. Отправьте его числовой ID:")
    elif txt.lstrip("-").isdigit():
        uid = int(txt)
    elif txt.startswith("@") or txt.replace("_", "").isalnum():
        u = db.q1("SELECT * FROM users WHERE username=? COLLATE NOCASE", (txt.lstrip("@"),))
        if not u:
            return await m.answer("Не нашёл такого пользователя среди тех, кто запускал бота. "
                                  "Отправьте его числовой ID (узнать можно у @userinfobot):")
        uid = u["id"]
    if not uid or uid <= 0:
        return await m.answer("Нужен числовой ID пользователя, @username или пересланное сообщение:")
    if admins.is_admin(uid):
        await state.clear()
        return await adm_view(m, "ℹ️ Этот пользователь уже админ.\n\n")
    admins.add(uid)
    if db.get_user(uid) and db.get_user(uid)["banned"]:
        db.update_user(uid, banned=0)
    await state.clear()
    await safe_send(bot, uid, "👮 Вам выданы права администратора бота. Админ-панель: /admin")
    await adm_view(m, f"✅ Админ добавлен: {_adm_name(uid)}\n\n")


@router.callback_query(F.data.startswith("a:admdel:"))
async def cb_adm_del(call: CallbackQuery):
    if not await _owner_only(call):
        return
    uid = int(call.data.split(":")[2])
    await render(call, f"Убрать права админа у {_adm_name(uid)}?", kb([
        [B("✅ Да, убрать", f"a:admdelok:{uid}", style="danger")],
        [B("◀️ Назад", "a:adm")],
    ]))
    await call.answer()


@router.callback_query(F.data.startswith("a:admdelok:"))
async def cb_adm_del_ok(call: CallbackQuery, bot: Bot):
    if not await _owner_only(call):
        return
    uid = int(call.data.split(":")[2])
    if admins.is_owner(uid):
        return await call.answer("Владельца удалить нельзя.", show_alert=True)
    admins.remove(uid)
    await safe_send(bot, uid, "ℹ️ Ваши права администратора бота отозваны.")
    await adm_view(call, f"✅ Права админа сняты: {_adm_name(uid)}\n\n")
    await call.answer("Готово")
