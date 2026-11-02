"""Ответы на вопросы в чатах через нейросеть (Groq, бесплатный ключ с console.groq.com).

Ключ вводит владелец конструктора в /admin → 💬 Чаты → 🧠 Нейросеть; хранится в базе (не в репозитории).
Нейросеть отвечает только по базе знаний — справочнику ctor/groups.HELP и FAQ из админки. Если вопрос не про
магазины или ответа в базе нет, она возвращает SKIP — и бот молчит.
"""
import html
import logging
import re
import time

import aiohttp

from ctor import core

log = logging.getLogger(__name__)
URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"
AD_MODEL = "openai/gpt-oss-120b"

PROMPT = (
    "Ты — помощник в Telegram-чате владельцев интернет-магазинов, созданных в боте-конструкторе @{bot}. "
    "Отвечай на русском, коротко и по делу (до 6 строк), без вступлений. Отвечай ТОЛЬКО по базе знаний ниже: "
    "пиши точные названия кнопок из неё, ничего не выдумывай. Если сообщение — не вопрос о магазине или "
    "конструкторе, или ответа в базе знаний нет, ответь ровно одним словом: SKIP.\n\nБаза знаний:\n{kb}"
)


def key():
    return core.get("ai_key") or ""


def model():
    return core.get("ai_model") or DEFAULT_MODEL


def on():
    return bool(key()) and core.flag_on("ai")


def knowledge():
    from ctor import groups
    out = []
    for e in groups.entries():
        a = re.sub(r"<[^>]+>", "", e["a"]).replace("{bot}", core.get("username") or "бот-конструктор")
        out.append(f"В: {e['q']}\nО: {html.unescape(a)}")
    return "\n\n".join(out)


# лимиты: не чаще раза в 15 с на чат и не больше N ответов в сутки на весь конструктор
_last_chat = {}
_day = {"date": "", "n": 0}


def daily_limit():
    try:
        return max(int(core.get("ai_daily") or 200), 0)
    except ValueError:
        return 200


def allowed(chat_id):
    today = time.strftime("%Y-%m-%d")
    if _day["date"] != today:
        _day.update(date=today, n=0)
    if _day["n"] >= daily_limit():
        return False
    now = time.monotonic()
    if now - _last_chat.get(chat_id, -1e9) < 15:
        return False
    _last_chat[chat_id] = now
    _day["n"] += 1
    return True


async def _post(path, payload, api_key, timeout=25):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.post(f"{URL}{path}", json=payload, headers={"Authorization": f"Bearer {api_key}"}) as r:
            data = await r.json(content_type=None)
            if r.status != 200:
                raise RuntimeError(f"Groq {r.status}: {str(data)[:200]}")
            return data


async def check_key(api_key):
    """Проверка ключа одним маленьким запросом. -> None или текст ошибки."""
    try:
        await _post("/chat/completions", {"model": model(), "max_tokens": 5,
                                          "messages": [{"role": "user", "content": "ping"}]}, api_key, timeout=20)
        return None
    except Exception as e:
        return str(e)[:200]


AD_PROMPT = (
    "Ты — копирайтер Telegram-магазинов. Напиши 3 РАЗНЫХ рекламных поста для магазина-бота в Telegram, чтобы "
    "владелец разместил их в каналах и чатах. Требования: русский язык; 300–600 символов каждый; живо, без "
    "канцелярита и без выдуманных фактов (гарантий, отзывов, цифр продаж, которых нет в данных); 3–6 уместных эмодзи; "
    "конкретные товары и цены из списка; в конце призыв и ссылка {link}. Стили: 1) короткий цепляющий, "
    "2) список хитов с ценами, 3) история/выгода для покупателя. Без markdown (никаких ** и #). "
    "Раздели посты строкой из трёх знаков равенства: ==="
)


async def ad_posts(title, desc, products, link):
    """Три рекламных поста для магазина. -> список текстов (экранированы для HTML) или None."""
    items = "\n".join(f"- {n} — {p:g}₽" for n, p in products[:12]) or "- (товаров пока нет — пиши про магазин в целом)"
    user = f"Магазин: {title}\nОписание: {desc or '—'}\nСсылка: {link}\nТовары:\n{items}"
    ad_model = core.get("ad_model") or AD_MODEL  # крупная модель — русский текст заметно лучше
    payload = {"model": ad_model, "max_tokens": 2500, "temperature": 0.9,
               "messages": [{"role": "system", "content": AD_PROMPT.format(link=link)},
                            {"role": "user", "content": user}]}
    if ad_model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    try:
        data = await _post("/chat/completions", payload, key(), timeout=60)
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.info("конструктор: реклама не сгенерировалась: %s", e)
        return None
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    posts = [p.strip() for p in re.split(r"\n\s*={3,}\s*\n", text) if len(p.strip()) > 40]
    return [html.escape(p[:1500]) for p in posts[:3]] or None


async def answer(question):
    """Ответ нейросети по базе знаний (текст, уже экранирован для HTML).
    "" — нейросеть решила, что вопрос не по теме (молчать); None — нейросеть недоступна."""
    payload = {"model": model(), "max_tokens": 700, "temperature": 0.2,
               "messages": [{"role": "system", "content": PROMPT.format(bot=core.get("username") or "бот",
                                                                         kb=knowledge())},
                            {"role": "user", "content": question[:1000]}]}
    if model().startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    try:
        data = await _post("/chat/completions", payload, key())
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        log.info("конструктор: нейросеть не ответила: %s", e)
        return None
    if not text or "SKIP" in text.upper()[:10]:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # markdown-жирный → обычный текст
    return html.escape(text[:1500])
