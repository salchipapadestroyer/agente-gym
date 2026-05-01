import logging
from telegram.ext import ApplicationBuilder
from . import config, handlers, scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


async def _on_startup(app):
    scheduler.start_scheduler(app.bot)


def main():
    for var in ("TELEGRAM_TOKEN", "ANTHROPIC_API_KEY", "GOOGLE_SHEETS_ID"):
        config.require(var)
    app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(_on_startup)
        .build()
    )
    handlers.register(app)
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
