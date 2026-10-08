"""نقطه ورود و اجرای سرویس بات تلگرام مترجم زیرنویس."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from ..config import settings
from .handlers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("srt_translator.main")


async def async_main() -> None:
    token = settings.telegram_bot_token
    if not token or token == "your_telegram_bot_token_here":
        print(
            "❌ توکن بات تلگرام تنظیم نشده است!\n"
            "لطفاً توکن دریافتی از @BotFather را در فایل .env در متغیر TELEGRAM_BOT_TOKEN قرار دهید.",
            file=sys.stderr,
        )
        sys.exit(1)

    log.info("در حال راه‌اندازی ربات تلگرام...")
    bot = Bot(token=token)
    dp = Dispatcher()

    # ثبت روت‌ها و هندلرها
    dp.include_router(router)

    try:
        me = await bot.get_me()
        log.info(f"ربات با موفقیت متصل شد: @{me.username} ({me.first_name})")
        print(f"🤖 ربات با آیدی @{me.username} فعال شد و آماده دریافت پیام است...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(async_main())
    except (KeyboardInterrupt, SystemExit):
        log.info("ربات متوقف شد.")


if __name__ == "__main__":
    main()
