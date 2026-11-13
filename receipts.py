"""Автопроверка чеков СБП нейросетью (Groq, модель с чтением картинок).

Нейросеть только ЧИТАЕТ чек: сумма, дата, получатель, номер операции, признаки монтажа. Решение принимает код:
  ✅ approve — всё сходится (сумма, получатель, свежая дата, чек не повторяется, сумма не выше лимита);
  ❌ reject  — это не чек, чек уже присылали, или сумма меньше нужной;
  👀 review  — сомнения (признаки монтажа, нет получателя, старая дата, не та сумма, лимит) → владельцу на проверку.

Важно: нейросеть не видит банковский счёт. Идеальную подделку она пропустить может — поэтому есть лимит суммы
автоодобрения (выше — всегда на проверку) и защита от повторного чека.

Используется и магазином (handlers/shop.py, handlers/topup.py), и конструктором (ctor/bot.py): у каждого свои
настройки в своей базе — prefix "rc_" (магазин) и "c:rc_" (конструктор).
"""
import base64
import html
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp

import db

log = logging.getLogger(__name__)
URL = "https://api.groq.com/openai/v1/chat/completions"
VISION_MODEL = "qwen/qwen3.8-27b"
MAX_BYTES = 3_500_000  # Groq принимает картинку в base64 до ~4 МБ

PROMPT = (
    "Ты — проверяющий фото/скриншотов чеков банковских переводов (СБП, переводы с карты). Ответь ТОЛЬКО JSON:\n"
    '{"is_receipt": bool, "success": bool, "amount": number|null, "datetime": "YYYY-MM-DD HH:MM"|null, '
    '"recipient_name": str|null, "recipient_phone": str|null, "recipient_card_last4": str|null, "bank": str|null, '
    '"transaction_id": str|null, "edit_signs": [str], "fake_probability": number, "comment": str}\n'
    "is_receipt — это действительно чек/экран успешного или неуспешного перевода из банка (не фото товара, не "
    "переписка, не скрин с ценой). success — перевод выполнен (не «в обработке», не «отклонён»). amount — сумма "
    "перевода в рублях без комиссии. edit_signs — конкретные признаки монтажа/подделки: разные шрифты в одной строке, "
    "смазанные или наложенные цифры, неровное выравнивание суммы, следы редактора, несоответствие интерфейса банка, "
    "время в будущем. Скриншот обычного приложения банка — НЕ признак подделки; JPEG-сжатие, обрезка и тёмная тема тоже. "
    "fake_probability — 0..1: ставь выше 0.7 только при явных следах редактирования, у обычного чека — 0.0–0.2. "
    "Не выдумывай поля, которых нет на изображении — пиши null."
)

# ======================= настройки =======================
# ns — набор настроек: SHOP («rc_*» в базе магазина) или CTOR («c:rc_*» в базе конструктора;
# если отдельного ключа нет — берётся ключ нейросети чатов c:ai_key, чтобы не вводить его дважды).
SHOP, CTOR = "rc_", "c:rc_"


def get(key, default=None, ns=SHOP):
    return db.get_setting(ns + key, default)


def put(key, value, ns=SHOP):
    db.set_setting(ns + key, value)


def api_key(ns=SHOP):
    return get("key", ns=ns) or (db.get_setting("c:ai_key") if ns == CTOR else None) or ""


def on(ns=SHOP):
    return bool(api_key(ns)) and get("on", "1", ns=ns) == "1"


def cap(ns=SHOP):
    """Выше этой суммы чек всегда идёт на ручную проверку (0 — без лимита)."""
    try:
        return max(float(get("cap", ns=ns) or 3000), 0)
    except ValueError:
        return 3000.0


def report_on(ns=SHOP):
    """Присылать владельцу короткий отчёт о каждом автоодобрении/отклонении."""
    return get("report", "1", ns=ns) == "1"


# ======================= учёт проверенных чеков (защита от повторов) =======================
def _init():
    db.conn.execute("CREATE TABLE IF NOT EXISTS receipt_checks (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, "
                    "ref_id INTEGER, file_uid TEXT, txid TEXT, amount REAL, decision TEXT, reason TEXT, created TEXT)")
    db.conn.commit()


def seen(file_uid, txid, kind, ref_id):
    """Тот же файл или номер операции уже приходил по ДРУГОЙ заявке."""
    _init()
    if file_uid and db.q1("SELECT 1 FROM receipt_checks WHERE file_uid=? AND NOT (kind=? AND ref_id=?)",
                          (file_uid, kind, ref_id)):
        return True
    if txid and db.q1("SELECT 1 FROM receipt_checks WHERE txid=? AND NOT (kind=? AND ref_id=?) "
                      "AND decision != 'reject'", (txid, kind, ref_id)):
        return True
    return False


def remember(kind, ref_id, file_uid, txid, amount, decision, reason):
    _init()
    db.x("INSERT INTO receipt_checks(kind, ref_id, file_uid, txid, amount, decision, reason, created) "
         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (kind, ref_id, file_uid, txid, amount, decision, reason, db.now()))


def last_check(kind, ref_id):
    _init()
    return db.q1("SELECT * FROM receipt_checks WHERE kind=? AND ref_id=? ORDER BY id DESC LIMIT 1", (kind, ref_id))


def stats():
    _init()
    rows = db.q("SELECT decision, COUNT(*) n FROM receipt_checks GROUP BY decision")
    return {r["decision"]: r["n"] for r in rows}


# ======================= нейросеть =======================
async def _ask(img_b64, mime, key, now=None):
    import asyncio
    now = now or msk_now()
    # модель не знает сегодняшнюю дату — без этого свежие чеки кажутся ей «из будущего»
    system = PROMPT + f"\n\nСегодня {now:%Y-%m-%d %H:%M} (московское время). Даты до этого момента — НЕ будущее."
    payload = {"model": VISION_MODEL, "max_tokens": 700, "temperature": 0,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": [
                                {"type": "text", "text": "Проверь этот чек."},
                                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}}]}]}
    for attempt in range(2):  # бесплатный Groq ограничивает картинки в минуту — один повтор после паузы
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
            async with s.post(URL, json=payload, headers={"Authorization": f"Bearer {key}"}) as r:
                data = await r.json(content_type=None)
                if r.status == 429 and attempt == 0:
                    try:
                        wait = min(float(r.headers.get("retry-after") or 15), 30)
                    except ValueError:
                        wait = 15
                    await asyncio.sleep(wait)
                    continue
                if r.status != 200:
                    raise RuntimeError(f"Groq {r.status}: {str(data)[:200]}")
                break
    text = data["choices"][0]["message"]["content"] or "{}"
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    raw = json.loads(text)
    # модель иногда пишет ключи с пробелами/заглавными («fake Probability»)
    return {re.sub(r"\s+", "_", str(k).strip().lower()): v for k, v in raw.items()}


async def check_key(key):
    """Проверка ключа: крошечный запрос к модели. -> None или текст ошибки."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(URL, json={"model": VISION_MODEL, "max_tokens": 5,
                                         "messages": [{"role": "user", "content": "ping"}]},
                              headers={"Authorization": f"Bearer {key}"}) as r:
                if r.status != 200:
                    return f"Groq {r.status}: {(await r.text())[:150]}"
        return None
    except Exception as e:
        return str(e)[:150]


# ======================= правила =======================
def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


def _num(v):
    """Число из ответа модели: 300, "300,00 ₽", "1 200,50", "1,200.50" (знак валюты и пробелы отбрасываются)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.,\-]", "", str(v))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:  # последний разделитель — десятичный, остальные — тысячи
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + tail if (len(tail) == 3 and head) else head.replace(",", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def _when(v):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(str(v).strip()[:19], fmt)
        except (TypeError, ValueError):
            continue
    return None


def msk_now():
    """Текущее московское время. Сервер хостинга обычно живёт в UTC, а в чеке время московское:
    сравнивать с datetime.now() нельзя — свежий чек выглядел «из будущего» и уходил на ручную проверку."""
    return (datetime.now(timezone.utc) + timedelta(hours=3)).replace(tzinfo=None)


def _flag(v):
    """True / False / None (не знаю): модель то пишет bool, то строку."""
    if isinstance(v, bool) or v is None:
        return v
    s = str(v).strip().lower()
    if s in ("true", "yes", "да", "1"):
        return True
    if s in ("false", "no", "нет", "0"):
        return False
    return None


def recipient_ok(info, details):
    """Совпадает ли получатель в чеке с реквизитами владельца.
    True — совпал; False — в чеке ЯВНО другой номер/карта; None — проверить нечем (банк скрывает часть номера,
    в чеке виден только маскированный номер или имя — это не повод подозревать чек)."""
    det = html.unescape(re.sub(r"<[^>]+>", " ", details or ""))
    found = [_digits(x) for x in re.findall(r"\+?\d[\d\s\-()]{9,}\d", det)]
    phones = [d[-10:] for d in found if 10 <= len(d) <= 12]
    cards = [d[-4:] for d in found if 16 <= len(d) <= 19]
    rp, rc = _digits(info.get("recipient_phone")), _digits(info.get("recipient_card_last4"))
    if phones and len(rp) >= 10:
        return rp[-10:] in phones
    raw = str(info.get("recipient_phone") or "")
    if phones and len(rp) < 10 and re.search(r"[*•xх#]", raw, re.I):
        # номер замаскирован («+7 916 ***-**-67»): сверяем только видимые цифры в конце
        tail = _digits(re.split(r"[*•xх#]", raw, flags=re.I)[-1])
        if len(tail) >= 2:
            return any(p.endswith(tail) for p in phones)
    if cards and len(rc) >= 4:
        return rc[-4:] in cards
    return None


def decide(info, expected, details, dup, now=None, limit=None):
    """-> ('approve'|'reject'|'review', причина).

    Раньше на проверку уходило почти всё: достаточно было fake_probability >= 0.3 (шум модели), любого «признака
    монтажа» в списке, незнакомого получателя или времени сервера в UTC. Теперь на проверку идёт только то, что
    действительно подозрительно; подозрение на монтаж — только если модель уверена."""
    now = now or msk_now()
    limit = cap() if limit is None else limit  # cap() — настройки магазина; конструктор передаёт свой лимит
    info = info or {}
    if _flag(info.get("is_receipt")) is False or (info.get("is_receipt") is None and info.get("amount") is None):
        return "reject", "это не чек перевода"
    if dup:
        return "reject", "этот чек уже присылали по другой оплате"
    amount = _num(info.get("amount"))
    if amount is not None and amount < expected * 0.98:
        return "reject", f"в чеке {amount:g}₽, а нужно {expected:g}₽"
    reasons = []
    fp = _num(info.get("fake_probability"))
    raw_signs = info.get("edit_signs") or []
    if isinstance(raw_signs, str):
        raw_signs = [raw_signs]
    signs = [str(s).strip() for s in raw_signs if str(s).strip()]
    if fp is not None and fp > 1:  # иногда пишет в процентах
        fp = fp / 100
    if (fp is not None and fp >= 0.75) or (len(signs) >= 2 and (fp or 0) >= 0.5):
        reasons.append("похоже на монтаж: " + "; ".join(signs[:3]) if signs else f"нейросеть сомневается ({fp:g})")
    if _flag(info.get("success")) is False:
        reasons.append("перевод не завершён")
    if amount is None:
        reasons.append("сумма не видна")
    elif amount > expected * 10 + 1:
        reasons.append(f"сумма {amount:g}₽ намного больше нужной")
    when = _when(info.get("datetime"))
    if when and when > now + timedelta(hours=3):
        reasons.append("дата в будущем")
    elif when and now - when > timedelta(days=7):
        reasons.append("чек старше недели")
    if recipient_ok(info, details) is False:
        reasons.append("получатель не совпадает с реквизитами")
    if limit and expected > limit:
        reasons.append(f"сумма выше лимита автоодобрения {limit:g}₽")
    if reasons:
        return "review", "; ".join(reasons)
    return "approve", "сумма и получатель сходятся, признаков монтажа нет"


async def check(bot, message, expected, details, kind, ref_id, ns=SHOP):
    """Проверка чека из сообщения. -> dict(decision, reason, info) или None (выключено / нейросеть недоступна)."""
    if not on(ns):
        return None
    if message.photo:
        f, mime = message.photo[-1], "image/jpeg"
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        f, mime = message.document, message.document.mime_type
    else:
        res = {"decision": "review", "reason": "чек прислан не картинкой (PDF/файл) — проверь вручную", "info": {}}
        remember(kind, ref_id, getattr(message.document, "file_unique_id", None), None, None, res["decision"], res["reason"])
        return res
    if (getattr(f, "file_size", 0) or 0) > MAX_BYTES:
        res = {"decision": "review", "reason": "файл слишком большой для проверки", "info": {}}
        remember(kind, ref_id, f.file_unique_id, None, None, res["decision"], res["reason"])
        return res
    try:
        buf = io.BytesIO()
        await bot.download(f.file_id, destination=buf)
        info = await _ask(base64.b64encode(buf.getvalue()).decode(), mime, api_key(ns))
    except Exception as e:
        log.warning("чек %s #%s: нейросеть не проверила: %s", kind, ref_id, e)
        return None
    txid = str(info.get("transaction_id") or "").strip() or None
    dup = seen(f.file_unique_id, txid, kind, ref_id)
    decision, reason = decide(info, float(expected), details, dup, limit=cap(ns))
    remember(kind, ref_id, f.file_unique_id, txid, _num(info.get("amount")), decision, reason)
    return {"decision": decision, "reason": reason, "info": info}


def summary(res):
    """Строка для владельца: что увидела нейросеть."""
    i = res.get("info") or {}
    parts = []
    if i.get("amount") is not None:
        parts.append(f"сумма {i.get('amount')}")
    if i.get("recipient_name") or i.get("recipient_phone"):
        parts.append("получатель " + " ".join(str(x) for x in (i.get("recipient_name"), i.get("recipient_phone")) if x))
    if i.get("datetime"):
        parts.append(str(i.get("datetime")))
    if i.get("bank"):
        parts.append(str(i.get("bank")))
    icon = {"approve": "✅", "reject": "❌", "review": "👀"}[res["decision"]]
    head = {"approve": "одобрен автоматически", "reject": "отклонён автоматически", "review": "нужна твоя проверка"}
    return (f"🤖 <b>Нейросеть: {icon} {head[res['decision']]}</b>\n<i>{html.escape(res['reason'])}</i>"
            + (f"\n🔎 {html.escape(', '.join(parts))}" if parts else ""))
