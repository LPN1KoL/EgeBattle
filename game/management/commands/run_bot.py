import asyncio

from django.core.management.base import BaseCommand

from game.bot import get_bot, get_dispatcher


class Command(BaseCommand):
    help = 'Запуск Telegram-бота в режиме polling (для разработки)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Запуск бота в режиме polling...'))

        async def main():
            bot = get_bot()
            dp = get_dispatcher()
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)

        asyncio.run(main())
