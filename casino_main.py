"""Запуск Cursed Casino: `python casino_main.py` (BOT_TOKEN, OWNER_IDS, PORT, PUBLIC_URL в .env)
или как бот клиента конструктора: `python casino_main.py --child <файл.json>`."""
import asyncio
import logging

from casino import bot

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(bot.run())
