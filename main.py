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
# admin_extra, admin_app и restock регистрируют хендлеры на admin.router
from handlers import (admin, admin_app, admin_extra, builder, codex, cryptopay, legal, payments, restock, shop,  # noqa: F401
                      support, topup, user)
import crypto
from middlewares import UserMiddleware


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("Не задан токен бота: добавьте переменную окружения BOT_TOKEN (на хостинге) "
                         "или файл .env со строкой BOT_TOKEN=ваш_токен")
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    if config.CHILD:
        # вторая проверка (первая — в config.py): Telegram подтверждает, что это именно бот клиента
        me = await bot.get_me()
        if me.id != config.EXPECT_BOT_ID or me.id == config.MAIN_BOT_ID:
            await bot.session.close()
            logging.error("ОСТАНОВЛЕН: токен принадлежит @%s, а не боту клиента", me.username)
            raise SystemExit(config.EXIT_IDENTITY)
    db.init()
    dp = Dispatcher()
    mw = UserMiddleware()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    # порядок важен: /start и меню -> ввод в админке -> поддержка -> магазин
    # builder, codex, topup — до shop, чтобы чеки и токен не ушли в обработчики магазина
    dp.include_routers(user.router, legal.router, admin.router, support.router, builder.router, codex.router,
                       topup.router, payments.router, cryptopay.router, shop.router)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню / Main menu"),
        BotCommand(command="terms", description="Пользовательское соглашение"),
        BotCommand(command="privacy", description="Политика конфиденциальности"),
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    # сайт: мини-приложение (/app) и документы. У бота клиента — на внутреннем порту, наружу его выводит основной бот
    site = await web.start(bot)
    await web.setup_menu_button(bot)  # кнопка «Магазин» у поля ввода открывает мини-приложение
    tasks = [asyncio.create_task(ext.sync_loop()),                     # автообновление остатков внешних магазинов
             asyncio.create_task(admin_app.auto_backup_loop(bot)),     # автобэкап базы владельцам раз в сутки
             asyncio.create_task(crypto.checker(bot))]                 # проверка оплат CryptoBot / xRocket
    if not config.CHILD:
        hosting.start_all(bot)  # боты клиентов («🤖 Создать своего бота»)
    logging.info("%s bot started%s", config.SHOP_NAME, " (бот клиента)" if config.CHILD else "")
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()
        if not config.CHILD:
            await hosting.shutdown()
        if site:
            await site.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
