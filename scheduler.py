import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from database import (
    get_all_users, get_watchers_of, get_active_broadcasts,
    update_broadcast_last_sent, deactivate_broadcast,
    get_all_holiday_subscriptions, get_all_custom_events,
)
from holidays import HOLIDAYS_BY_KEY, days_until_holiday
from keyboards import congrats_kb
from utils import days_until_birthday, parse_birthdate

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

BROADCAST_DATETIME_FMT = "%d.%m.%Y %H:%M"


def start_scheduler(bot: Bot):
    scheduler.add_job(check_birthdays, trigger="cron", hour=9, minute=0,
                      args=[bot], id="birthday_checker", replace_existing=True)
    scheduler.add_job(check_holidays, trigger="cron", hour=9, minute=5,
                      args=[bot], id="holiday_checker", replace_existing=True)
    scheduler.add_job(check_custom_events, trigger="cron", hour=9, minute=10,
                      args=[bot], id="custom_event_checker", replace_existing=True)
    scheduler.add_job(process_broadcasts, trigger="cron", minute="*/5",
                      args=[bot], id="broadcast_processor", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started")


# ─── Birthday reminders ───────────────────────────────────────────────────────

async def check_birthdays(bot: Bot):
    users = await get_all_users()
    for user in users:
        if not user["birthdate"]:
            continue
        bd = parse_birthdate(user["birthdate"])
        if not bd:
            continue
        days = days_until_birthday(bd)
        if days not in (0, 1, 2, 3):
            continue

        watchers = await get_watchers_of(user["telegram_id"])
        username_display = f"@{user['username']}" if user["username"] else user["first_name"]
        target_id = user["telegram_id"]

        if days == 0:
            header = f"🎂 <b>Сегодня день рождения у {username_display}!</b>"
            subtext = "Самое время поздравить — выберите вариант ниже 👇"
            show_button = True
        elif days == 1:
            header = f"🎉 <b>Завтра у {username_display} день рождения!</b>"
            subtext = "Не забудьте поздравить — можно уже сейчас! 👇"
            show_button = True
        elif days == 2:
            header = f"🎁 <b>Через 2 дня у {username_display} день рождения!</b>"
            subtext = "Самое время выбрать подарок 🛍"
            show_button = False
        else:
            header = f"📅 <b>Через 3 дня у {username_display} день рождения!</b>"
            subtext = "Не забудьте поздравить вовремя 😊"
            show_button = False

        text = f"{header}\n\n{subtext}"
        kb = congrats_kb(target_id) if show_button else None

        for watcher_id in watchers:
            try:
                await bot.send_message(
                    watcher_id, text,
                    parse_mode="HTML",
                    reply_markup=kb
                )
            except Exception as e:
                logger.warning(f"Failed to notify {watcher_id}: {e}")


# ─── Holiday reminders ────────────────────────────────────────────────────────

async def check_holidays(bot: Bot):
    all_subs = await get_all_holiday_subscriptions()
    if not all_subs:
        return

    for sub in all_subs:
        user_id = sub["user_id"]
        key = sub["holiday_key"]
        holiday = HOLIDAYS_BY_KEY.get(key)
        if not holiday:
            continue

        days = days_until_holiday(holiday["month"], holiday["day"])
        advance = holiday.get("advance_days", 3)

        if days not in (0, 1, advance):
            continue

        emoji = holiday["emoji"]
        name = holiday["name"]

        if days == 0:
            text = f"{emoji} <b>Сегодня {name}!</b>\n🎉 Поздравляем!"
        elif days == 1:
            text = f"{emoji} <b>Завтра {name}!</b>\n📅 Не забудьте поздравить близких!"
        else:
            text = f"{emoji} <b>Через {days} дней — {name}!</b>\n🗓 Самое время всё подготовить."

        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed holiday notify {user_id} ({key}): {e}")


# ─── Custom event reminders ───────────────────────────────────────────────────

async def check_custom_events(bot: Bot):
    events = await get_all_custom_events()
    today = date.today()

    for ev in events:
        date_str = ev["date_str"]
        repeat = bool(ev["repeat"])

        try:
            parts = date_str.split(".")
            day, month = int(parts[0]), int(parts[1])
            year = int(parts[2]) if len(parts) == 3 else None
        except (IndexError, ValueError):
            continue

        if year and not repeat:
            try:
                event_date = date(year, month, day)
            except ValueError:
                continue
            delta = (event_date - today).days
        else:
            delta = days_until_holiday(month, day)

        if delta not in (0, 1, 3):
            continue

        title = ev["title"]
        user_id = ev["user_id"]

        if delta == 0:
            text = f"✨ <b>Сегодня — {title}!</b>\n🎉 Ваше личное событие наступило!"
        elif delta == 1:
            text = f"✨ <b>Завтра — {title}!</b>\n📅 Ваше личное событие уже завтра!"
        else:
            text = f"✨ <b>Через {delta} дня — {title}!</b>\n🗓 Скоро ваше личное событие."

        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Failed event notify {user_id} (ev#{ev['id']}): {e}")


# ─── Broadcasts ───────────────────────────────────────────────────────────────

async def process_broadcasts(bot: Bot):
    broadcasts = await get_active_broadcasts()
    now = datetime.now()

    for bc in broadcasts:
        end_date = date.fromisoformat(bc["end_date"])
        if date.today() > end_date:
            await deactivate_broadcast(bc["id"])
            logger.info(f"Broadcast #{bc['id']} deactivated (past end date)")
            continue

        try:
            start_dt = datetime.strptime(bc["start_datetime"], BROADCAST_DATETIME_FMT)
        except (ValueError, TypeError):
            logger.warning(f"Broadcast #{bc['id']} has invalid start_datetime, skipping")
            continue

        if now < start_dt:
            continue

        interval = timedelta(days=bc["interval_days"])
        next_send_dt = start_dt
        while next_send_dt <= now - timedelta(minutes=5):
            next_send_dt += interval

        if next_send_dt > now + timedelta(minutes=5):
            continue

        slot_date = next_send_dt.date()
        last_sent_str = bc.get("last_sent")
        if last_sent_str:
            last_sent_date = date.fromisoformat(last_sent_str)
            if last_sent_date >= slot_date:
                continue

        users = await get_all_users()
        sent = 0
        photo_file_id = bc.get("photo_file_id")

        for user in users:
            try:
                if photo_file_id:
                    await bot.send_photo(
                        user["telegram_id"],
                        photo=photo_file_id,
                        caption=bc["message_text"],
                        parse_mode="HTML"
                    )
                else:
                    await bot.send_message(
                        user["telegram_id"],
                        bc["message_text"],
                        parse_mode="HTML"
                    )
                sent += 1
            except Exception as e:
                logger.warning(f"Broadcast #{bc['id']} failed for {user['telegram_id']}: {e}")

        await update_broadcast_last_sent(bc["id"], slot_date.isoformat())
        logger.info(f"Broadcast #{bc['id']} sent to {sent} users (slot={slot_date})")
