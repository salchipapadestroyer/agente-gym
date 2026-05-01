import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from . import sheets, config
from .handlers import send_plan, run_weekly

log = logging.getLogger(__name__)


async def morning_broadcast(bot):
    users = await asyncio.to_thread(sheets.get_all_users)
    for user in users:
        chat_id = str(user.get("telegram_chat_id"))
        try:
            await send_plan(bot, chat_id, user)
        except Exception as e:
            log.exception("morning failed for %s: %s", chat_id, e)


async def evening_prompt(bot):
    users = await asyncio.to_thread(sheets.get_all_users)
    for user in users:
        chat_id = str(user.get("telegram_chat_id"))
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Cierre del día, {user.get('nombre', '')}. "
                    "Cuando puedas, manda /checkin o un resumen corto de tu día."
                ),
            )
        except Exception as e:
            log.exception("evening failed for %s: %s", chat_id, e)


async def weekly_report(bot):
    users = await asyncio.to_thread(sheets.get_all_users)
    for user in users:
        try:
            await run_weekly(bot, user)
        except Exception as e:
            log.exception("weekly failed for %s: %s", user.get("telegram_chat_id"), e)


def start_scheduler(bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=config.TIMEZONE)
    sched.add_job(morning_broadcast,
                  CronTrigger(hour=config.MORNING_HOUR, minute=0),
                  args=[bot])
    sched.add_job(evening_prompt,
                  CronTrigger(hour=config.CHECKIN_HOUR, minute=config.CHECKIN_MINUTE),
                  args=[bot])
    sched.add_job(weekly_report,
                  CronTrigger(day_of_week=config.WEEKLY_DAY,
                              hour=config.WEEKLY_HOUR, minute=0),
                  args=[bot])
    sched.start()
    log.info("scheduler started")
    return sched
