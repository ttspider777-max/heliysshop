import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import config
import db
import ext
import hosting
import web
from handlers import admin, admin_extra, builder, codex, legal, payments, restock, shop, user  # noqa: F401  (admin_extra и restock регистрируют хендлеры на admin.router)
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
    # builder — «🤖 Создать своего бота»: до shop, чтобы чек за бота и токен не ушли в обработчики магазина
    dp.include_routers(user.router, legal.router, admin.router, builder.router, codex.router, payments.router, shop.router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню / Main menu"),
        BotCommand(command="terms", description="Пользовательское соглашение"),
        BotCommand(command="privacy", description="Политика конфиденциальности"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    # бот клиента: сайт не запускаем (порт один на весь сервер) и чужих ботов не хостим
    site = None if config.CHILD else await web.start()  # страницы /privacy и /terms для платёжной системы
    sync_task = asyncio.create_task(ext.sync_loop())  # автообновление остатков внешних магазинов
    if not config.CHILD:
        hosting.start_all(bot)  # боты клиентов («🤖 Создать своего бота»)
    logging.info("%s bot started%s", config.SHOP_NAME, " (бот клиента)" if config.CHILD else "")
    try:
        await dp.start_polling(bot)
    finally:
        sync_task.cancel()
        if not config.CHILD:
            await hosting.shutdown()
        if site:
            await site.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
