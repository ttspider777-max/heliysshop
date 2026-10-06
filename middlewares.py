from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

import config
import db
import subscription
from texts import t
from ui import btn, has_docs, kb, legal_row, raw_btn, render


def sub_kb(channels, lang):
    rows = [[raw_btn(f"📢 {c['title']}", url=ui_url(c["url"]))] for c in channels]
    rows.append([btn("sub_check", lang, "subcheck")])
    return kb(rows)


def ui_url(u):
    from ui import fix_url
    return fix_url(u) or u


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя, проверяет бан и передаёт в хендлеры user / lang / is_new."""

    @staticmethod
    def _remember_ref(event, u, is_new):
        """Реферал не должен теряться, если новичка остановили подпиской или согласием с документами."""
        if is_new and isinstance(event, Message) and (event.text or "").startswith("/start ref_"):
            arg = event.text.split("ref_", 1)[1].strip()
            if arg.isdigit() and int(arg) != u.id and db.get_user(int(arg)):
                db.update_user(u.id, referrer_id=int(arg))

    async def __call__(self, handler, event, data):
        u = getattr(event, "from_user", None)
        if u is None or u.is_bot:
            return await handler(event, data)

        row = db.get_user(u.id)
        is_new = row is None
        if is_new:
            lang = "ru" if (u.language_code or "ru")[:2] in ("ru", "uk", "be", "kk") else "en"
            db.create_user(u.id, u.username, u.first_name, lang)
            row = db.get_user(u.id)
        elif row["username"] != u.username or row["first_name"] != u.first_name:
            db.update_user(u.id, username=u.username, first_name=u.first_name)

        if row["banned"] and u.id not in config.ADMINS:
            if isinstance(event, CallbackQuery):
                await event.answer(t("banned", row["lang"]), show_alert=True)
            else:
                await event.answer(t("banned", row["lang"]))
            return

        if u.id not in config.ADMINS and not (isinstance(event, CallbackQuery) and event.data == "subcheck"):
            lang = row["lang"] or "ru"

            # согласие с документами (включается в админ-панели → 📄 Документы)
            cb = event.data if isinstance(event, CallbackQuery) else ""
            if (db.get_setting("terms_gate") == "1" and has_docs() and not row["agreed"]
                    and not (cb == "agree" or cb.startswith("legal:"))):
                self._remember_ref(event, u, is_new)
                if isinstance(event, CallbackQuery):
                    await event.answer()
                await render(event, t("agree_prompt", lang), kb([
                    legal_row(lang),
                    [btn("agree", lang, "agree")],
                ]))
                return

            need = await subscription.missing(event.bot, u.id)
            if need:
                self._remember_ref(event, u, is_new)
                if isinstance(event, CallbackQuery):
                    await event.answer(t("sub_not_yet", lang), show_alert=True)
                await render(event, t("sub_prompt", lang), sub_kb(need, lang))
                return

        data["user"] = row
        data["lang"] = row["lang"] or "ru"
        data["is_new"] = is_new
        return await handler(event, data)
