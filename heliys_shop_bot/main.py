import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import config
import db
from handlers import admin, shop, user
from middlewares import UserMiddleware


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан токен бота: добавьте переменную окружения BOT_TOKEN (на хостинге) "
                         "или файл .env со строкой BOT_TOKEN=ваш_токен")
    db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher()
    mw = UserMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    # порядок важен: /start и меню -> ввод в админке -> магазин
    dp.include_routers(user.router, admin.router, shop.router)
    await bot.set_my_commands([BotCommand(command="start", description="Главное меню / Main menu")])
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("heliys shop bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
