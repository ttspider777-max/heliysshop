import asyncio
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web

import api
import config
import db
import handlers_admin
import handlers_user
import mailing
import payments
from loader import bot

log = logging.getLogger(__name__)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    await db.init()

    runner = web.AppRunner(api.build_app())
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
        log.info("Mini App: http://localhost:%s", config.PORT)
    except OSError as e:
        # бот должен работать, даже если порт занят — без Mini App
        log.error("Mini App не запущен, порт %s занят: %s. Задайте другой порт в WEB_PORT", config.PORT, e)

    if config.WEBAPP_URL:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=config.WEBAPP_URL)))
    else:
        log.warning("WEBAPP_URL не задан — кнопка «Открыть приложение» скрыта")
    if not config.API_ID or not config.API_HASH:
        log.warning("API_ID/API_HASH не заданы — подключение аккаунтов недоступно")

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(handlers_user.UserMiddleware())
    dp.include_routers(handlers_admin.router, handlers_user.router)

    tasks = [asyncio.create_task(mailing.scheduler()), asyncio.create_task(payments.checker())]
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
