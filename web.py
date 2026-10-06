"""Встроенный мини-сайт: публичные страницы /privacy и /terms.

Платёжные системы (Robokassa, ЮKassa и т. п.) при подключении просят ссылки на политику конфиденциальности
и пользовательское соглашение. Эти страницы всегда показывают актуальные тексты из админ-панели бота.
"""
import html
import logging

from aiohttp import web

import config
import db
from ui import doc_text

log = logging.getLogger(__name__)

DOCS = {
    "privacy": "Политика конфиденциальности",
    "terms": "Пользовательское соглашение",
}

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {shop}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 0; font: 16px/1.65 -apple-system, "Segoe UI", Roboto, sans-serif; background: #f5f5f7; color: #1d1d1f; }}
main {{ max-width: 760px; margin: 0 auto; padding: 28px 18px 60px; }}
h1 {{ font-size: 26px; line-height: 1.25; margin: 0 0 6px; }}
.brand {{ color: #6e6e73; margin-bottom: 22px; }}
.doc {{ background: #fff; border-radius: 14px; padding: 20px 22px; white-space: pre-wrap; word-wrap: break-word; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.seller {{ margin-top: 18px; padding: 16px 22px; border-radius: 14px; background: #ececf0; white-space: pre-wrap; font-size: 15px; }}
footer {{ margin-top: 18px; color: #6e6e73; font-size: 13px; }}
a {{ color: #0a66d6; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #111113; color: #f2f2f4; }}
  .doc {{ background: #1c1c1f; box-shadow: none; }}
  .seller {{ background: #26262a; }}
  .brand, footer {{ color: #9a9aa1; }}
  a {{ color: #6cb2ff; }}
}}
</style></head>
<body><main>
<h1>{title}</h1>
<div class="brand">{shop}</div>
<div class="doc">{body}</div>
{seller}
<footer>{footer}</footer>
</main></body></html>"""


def public_url():
    return (db.get_setting("public_url") or config.PUBLIC_URL or "").strip().rstrip("/")


def doc_link(name):
    """Ссылка на документ для платёжной системы: своя ссылка админа, иначе страница встроенного сайта."""
    own = db.get_setting(f"doc_url:{name}")
    if own:
        return own
    base = public_url()
    return f"{base}/{name}" if base else None


def _render(title, body, seller="", footer=""):
    seller_html = f'<div class="seller">{seller}</div>' if seller else ""
    return PAGE.format(title=html.escape(title), shop=html.escape(config.SHOP_NAME), body=body,
                       seller=seller_html, footer=footer)


async def page(request):
    name = request.match_info["name"]
    text = doc_text(name)
    if name not in DOCS or not text:
        return web.Response(status=404, content_type="text/html", charset="utf-8",
                            text=_render("Документ не найден", "Этот документ пока не опубликован."))
    ts = db.get_setting(f"doc:{name}:ts") or ""
    footer = f"Редакция от {ts[8:10]}.{ts[5:7]}.{ts[:4]}" if len(ts) >= 10 else ""
    return web.Response(content_type="text/html", charset="utf-8",
                        text=_render(DOCS[name], text, db.get_setting("seller_info") or "", footer))


async def index(request):
    links = "\n".join(f'<a href="/{n}">{html.escape(t)}</a>' for n, t in DOCS.items() if doc_text(n))
    return web.Response(content_type="text/html", charset="utf-8",
                        text=_render(config.SHOP_NAME, links or "Документы пока не опубликованы."))


async def health(request):
    return web.Response(text="ok")


async def start():
    """Запускает сайт рядом с ботом. Если порт занят или недоступен — просто пишет предупреждение."""
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/{name:privacy|terms}", page)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", config.WEB_PORT).start()
    except OSError as e:
        log.warning("мини-сайт с документами не запущен (порт %s): %s", config.WEB_PORT, e)
        await runner.cleanup()
        return None
    log.info("мини-сайт с документами: порт %s", config.WEB_PORT)
    return runner
