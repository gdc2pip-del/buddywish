import logging
from datetime import date, datetime

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

from config import ADMIN_IDS
from database import (
    upsert_user, get_user_by_id, get_user_by_username,
    get_all_users, get_users_count,
    add_tracking, remove_tracking, is_tracking,
    get_tracking_count, get_watchers_count, get_invited_count,
    get_all_channels, add_channel, remove_channel,
    add_broadcast, get_all_broadcasts, deactivate_broadcast,
    wishlist_add, wishlist_get, wishlist_delete, wishlist_clear,
    holiday_subscribe, holiday_unsubscribe, holiday_is_subscribed,
    get_user_holiday_subscriptions,
    custom_event_add, custom_event_get_all, custom_event_delete,
    has_congratulated_this_year, record_congrats, get_congrats_stats,
    toggle_stats_public,
)
from holidays import HOLIDAYS, HOLIDAYS_BY_KEY, days_until_holiday
from keyboards import (
    main_menu_kb, admin_menu_kb, profile_kb,
    channel_management_kb, cancel_kb,
    wishlist_view_kb, users_list_kb,
    holidays_main_kb, holidays_catalog_kb, my_holidays_kb,
    my_events_kb, event_repeat_kb,
    congrats_kb, CONGRATS_TEMPLATES,
)
from utils import parse_birthdate, calculate_age, days_until_birthday

logger = logging.getLogger(__name__)
router = Router()

USERS_PAGE_SIZE = 20

# ─── Titles ───────────────────────────────────────────────────────────────────

TITLES = [
    (0,  "🌱 Новичок"),
    (1,  "🤝 Первый шаг"),
    (3,  "⭐ Активист"),
    (5,  "🌟 Коннектор"),
    (10, "💫 Амбассадор"),
    (20, "🏆 Легенда"),
    (50, "👑 Гроссмейстер"),
]

STREAK_MILESTONES = {
    2:  "🔥 Серия 2 поздравления подряд!",
    5:  "🔥🔥 Серия 5 поздравлений подряд!",
    10: "🔥🔥🔥 Серия 10 поздравлений подряд!",
    20: "💎 Невероятная серия — 20 поздравлений подряд!",
    50: "👑 Легендарная серия — 50 поздравлений подряд!",
}


def get_title(invited_count: int) -> str:
    title = TITLES[0][1]
    for threshold, name in TITLES:
        if invited_count >= threshold:
            title = name
    return title


def next_title_info(invited_count: int) -> tuple[str, int] | None:
    for threshold, name in TITLES:
        if invited_count < threshold:
            return name, threshold - invited_count
    return None


def streak_milestone_text(streak: int) -> str | None:
    return STREAK_MILESTONES.get(streak)


def streak_display(streak: int) -> str:
    if streak == 0:
        return "—"
    if streak < 5:
        fire = "🔥"
    elif streak < 10:
        fire = "🔥🔥"
    elif streak < 20:
        fire = "🔥🔥🔥"
    else:
        fire = "💎"
    return f"{fire} {streak}"


# ─── FSM States ──────────────────────────────────────────────────────────────

class Registration(StatesGroup):
    waiting_birthdate = State()

class EditBirthdate(StatesGroup):
    waiting_new_birthdate = State()

class Search(StatesGroup):
    waiting_username = State()

class WishlistAdd(StatesGroup):
    waiting_item = State()

class AdminBroadcast(StatesGroup):
    waiting_photo = State()
    waiting_text = State()
    waiting_interval = State()
    waiting_start_datetime = State()
    waiting_end_date = State()

class AdminChannel(StatesGroup):
    waiting_channel = State()

class CustomEvent(StatesGroup):
    waiting_title = State()
    waiting_date = State()
    waiting_repeat = State()

class CongratsCustom(StatesGroup):
    waiting_text = State()


# ─── Глобальный обработчик кнопки «❌ Отмена» ────────────────────────────────
# Должен быть объявлен ДО всех FSM-хэндлеров.
# Срабатывает в любом состоянии, включая отсутствие состояния.

@router.message(F.text == "❌ Отмена", StateFilter("*"))
async def global_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("Действие отменено.", reply_markup=main_menu_kb())
    else:
        await message.answer("Главное меню", reply_markup=main_menu_kb())


# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def check_subscriptions(bot: Bot, user_id: int) -> list[dict]:
    channels = await get_all_channels()
    not_subscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ("left", "kicked", "banned"):
                not_subscribed.append(ch)
        except Exception:
            not_subscribed.append(ch)
    return not_subscribed


def subscription_kb(channels: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        cid = ch["channel_id"]
        link = f"https://t.me/c/{cid[4:]}" if cid.startswith("-100") else f"https://t.me/{cid.lstrip('@')}"
        buttons.append([InlineKeyboardButton(text=f"📢 {ch['title']}", url=link)])
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def require_registration(message: Message) -> bool:
    user = await get_user_by_id(message.from_user.id)
    if not user:
        await message.answer("Вы не зарегистрированы. Введите /start.")
        return False
    return True


def make_profile_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=profile_{user_id}"


# ─── Profile builder ─────────────────────────────────────────────────────────

_default_avatar_file_id: dict = {}


async def send_profile(
    message: Message,
    viewer_id: int,
    user: dict,
    bot: Bot,
    is_self: bool = False,
    auto_track: bool = False,
):
    bd = parse_birthdate(user["birthdate"])
    age = calculate_age(bd)
    days = days_until_birthday(bd)
    username_display = f"@{user['username']}" if user["username"] else user["first_name"]

    # Title
    invited_count = await get_invited_count(user["telegram_id"])
    user_title = get_title(invited_count)

    if days == 0:
        birthday_line = "🎂 Сегодня день рождения!"
    elif days == 1:
        birthday_line = "🎉 Завтра день рождения!"
    else:
        birthday_line = f"📅 До дня рождения: {days} дн."

    text = (
        f"👤 <b>{user['first_name']}</b>"
        + (f" ({username_display})" if user["username"] else "") + "\n"
        f"🏅 {user_title}\n"
        f"🎂 Дата рождения: <b>{user['birthdate']}</b>\n"
        f"🔢 Возраст: <b>{age} лет</b>\n"
        f"{birthday_line}"
    )

    tracking = await is_tracking(viewer_id, user["telegram_id"])

    if auto_track and not is_self and not tracking:
        await add_tracking(viewer_id, user["telegram_id"])
        tracking = True
        text += "\n\n✅ Вы автоматически начали отслеживать этого пользователя."

    stats_public = bool(user.get("stats_public", 0))
    kb = profile_kb(user["telegram_id"], tracking, is_self, stats_public=stats_public)

    photo_to_send = None
    try:
        photos = await bot.get_user_profile_photos(user["telegram_id"], limit=1)
        if photos.total_count > 0:
            photo_to_send = photos.photos[0][-1].file_id
    except Exception as e:
        logger.warning(f"Could not get avatar for {user['telegram_id']}: {e}")

    if photo_to_send:
        await message.answer_photo(
            photo=photo_to_send, caption=text, parse_mode="HTML", reply_markup=kb
        )
    else:
        default_fid = _default_avatar_file_id.get("fid")
        if default_fid:
            await message.answer_photo(
                photo=default_fid, caption=text, parse_mode="HTML", reply_markup=kb
            )
        else:
            import os
            avatar_path = os.path.join(os.path.dirname(__file__), "default_avatar.png")
            if os.path.exists(avatar_path):
                from aiogram.types import FSInputFile
                sent = await message.answer_photo(
                    photo=FSInputFile(avatar_path), caption=text,
                    parse_mode="HTML", reply_markup=kb
                )
                if sent.photo:
                    _default_avatar_file_id["fid"] = sent.photo[-1].file_id
            else:
                await message.answer(text, parse_mode="HTML", reply_markup=kb)


# ─── /start ───────────────────────────────────────────────────────────────────

WELCOME_TEXT = """\
🎂 <b>Добро пожаловать в BuddyWish!</b>

Я помогу вам никогда не забыть важные даты — дни рождения друзей, \
популярные праздники и ваши личные события.

<b>🔥 Что умею:</b>

👤 <b>Профиль</b> — зарегистрируйтесь по дате рождения, поделитесь профилем
🔔 <b>Отслеживание</b> — напоминания за 1, 2 и 3 дня до ДР друга
🎉 <b>Поздравления</b> — поздравьте прямо из уведомления! Шаблоны, своё или эмодзи
🔥 <b>Серия поздравлений</b> — поздравляйте друзей подряд и бейте рекорды!
🎁 <b>Вишлист</b> — список подарков, который видят ваши друзья
🗓 <b>Праздники</b> — Новый год, 8 Марта, День победы и другие
✨ <b>Свои события</b> — личные события с ежегодным напоминанием
📊 <b>Статистика</b> — поздравления, серия, рекорд, достижения
🔗 <b>Рефералы</b> — поделитесь профилем, друзья зарегистрируются — вам зачтётся!

<b>📌 Команды:</b>
/me — мой профиль
/holidays — праздники и события
/mystats — моя статистика
/invite — моя ссылка для приглашения
/search — найти пользователя
/friend — друзья на отслеживании
/help — все команды

<i>Введите вашу дату рождения в формате <b>дд.мм.гггг</b></i> 👇\
"""


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    args = message.text.split(maxsplit=1)
    deep_link_param = args[1].strip() if len(args) > 1 else None

    profile_target_id: int | None = None
    invited_by: int | None = None

    if deep_link_param and deep_link_param.startswith("profile_"):
        try:
            profile_target_id = int(deep_link_param.replace("profile_", ""))
            if profile_target_id != message.from_user.id:
                invited_by = profile_target_id
        except ValueError:
            pass

    user = await get_user_by_id(message.from_user.id)

    if user:
        not_subscribed = await check_subscriptions(bot, message.from_user.id)
        if not_subscribed:
            if deep_link_param:
                await state.update_data(deep_link=deep_link_param)
            await message.answer(
                "📢 Для использования бота подпишитесь на каналы:",
                reply_markup=subscription_kb(not_subscribed)
            )
            return
        await message.answer(
            f"👋 С возвращением, {message.from_user.first_name}!",
            reply_markup=main_menu_kb()
        )
        if profile_target_id:
            await _show_profile_by_id(message, message.from_user.id, profile_target_id, bot, auto_track=True)
    else:
        if deep_link_param:
            await state.update_data(deep_link=deep_link_param)
        if invited_by:
            await state.update_data(invited_by=invited_by)
        await message.answer(WELCOME_TEXT, parse_mode="HTML", reply_markup=cancel_kb())
        await state.set_state(Registration.waiting_birthdate)


async def _show_profile_by_id(
    message: Message, viewer_id: int, target_id: int, bot: Bot, auto_track: bool = False
):
    target = await get_user_by_id(target_id)
    if target:
        await send_profile(message, viewer_id, target, bot, auto_track=auto_track)


# ─── Subscription check ───────────────────────────────────────────────────────

@router.callback_query(F.data == "check_sub")
async def callback_check_sub(call: CallbackQuery, bot: Bot, state: FSMContext):
    not_subscribed = await check_subscriptions(bot, call.from_user.id)
    if not_subscribed:
        await call.answer("❌ Вы ещё не подписались на все каналы!", show_alert=True)
        return
    await call.message.delete()
    user = await get_user_by_id(call.from_user.id)
    data = await state.get_data()
    deep_link = data.get("deep_link")

    profile_target_id: int | None = None
    if deep_link and deep_link.startswith("profile_"):
        try:
            profile_target_id = int(deep_link.replace("profile_", ""))
        except ValueError:
            pass

    if user:
        await call.message.answer("✅ Отлично! Теперь вы можете пользоваться ботом.", reply_markup=main_menu_kb())
        if profile_target_id:
            await _show_profile_by_id(call.message, call.from_user.id, profile_target_id, bot, auto_track=True)
    else:
        await call.message.answer(
            "📅 Введите вашу дату рождения в формате <b>дд.мм.гггг</b>:",
            parse_mode="HTML", reply_markup=cancel_kb()
        )
        await state.set_state(Registration.waiting_birthdate)


# ─── Registration ─────────────────────────────────────────────────────────────

@router.message(Registration.waiting_birthdate)
async def process_birthdate(message: Message, state: FSMContext, bot: Bot):
    # «❌ Отмена» handled by global_cancel above; but keep local just in case
    bd = parse_birthdate(message.text)
    if not bd:
        await message.answer(
            "❌ Неверный формат. Введите дату в формате <b>дд.мм.гггг</b>, например: 15.03.1995",
            parse_mode="HTML"
        )
        return
    if bd > date.today():
        await message.answer("❌ Дата рождения не может быть в будущем.")
        return

    data = await state.get_data()
    deep_link = data.get("deep_link")
    invited_by = data.get("invited_by")
    await state.clear()

    await upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        bd.strftime("%d.%m.%Y"),
        invited_by=invited_by,
    )

    not_subscribed = await check_subscriptions(bot, message.from_user.id)
    if not_subscribed:
        if deep_link:
            await state.update_data(deep_link=deep_link)
        await message.answer(
            "✅ Регистрация завершена!\n\n📢 Подпишитесь на каналы для продолжения:",
            reply_markup=subscription_kb(not_subscribed)
        )
        return

    inviter_note = ""
    if invited_by:
        inviter = await get_user_by_id(invited_by)
        if inviter:
            inviter_name = f"@{inviter['username']}" if inviter.get("username") else inviter["first_name"]
            inviter_note = f"\n🤝 Вас пригласил {inviter_name} — спасибо за компанию!"

    await message.answer(
        f"✅ Отлично! Дата рождения <b>{bd.strftime('%d.%m.%Y')}</b> сохранена.\n"
        f"Вам сейчас <b>{calculate_age(bd)}</b> лет.{inviter_note}\n\n"
        f"💡 Отправьте /help чтобы увидеть список всех команд.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

    if deep_link and deep_link.startswith("profile_"):
        try:
            target_id = int(deep_link.replace("profile_", ""))
            await _show_profile_by_id(message, message.from_user.id, target_id, bot, auto_track=True)
        except ValueError:
            pass


# ─── My Profile (/me) ────────────────────────────────────────────────────────

@router.message(F.text == "📋 Мой профиль")
@router.message(Command("me"))
async def my_profile(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if not await require_registration(message):
        return
    user = await get_user_by_id(message.from_user.id)
    await send_profile(message, message.from_user.id, user, bot, is_self=True)


# ─── Edit birthdate ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "edit_birthdate")
async def callback_edit_birthdate(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "✏️ Введите новую дату рождения в формате <b>дд.мм.гггг</b>:",
        parse_mode="HTML", reply_markup=cancel_kb()
    )
    await state.set_state(EditBirthdate.waiting_new_birthdate)


@router.message(EditBirthdate.waiting_new_birthdate)
async def process_edit_birthdate(message: Message, state: FSMContext, bot: Bot):
    bd = parse_birthdate(message.text)
    if not bd:
        await message.answer(
            "❌ Неверный формат. Введите дату в формате <b>дд.мм.гггг</b>:", parse_mode="HTML"
        )
        return
    if bd > date.today():
        await message.answer("❌ Дата рождения не может быть в будущем.")
        return

    await upsert_user(
        message.from_user.id, message.from_user.username,
        message.from_user.first_name, bd.strftime("%d.%m.%Y")
    )
    await state.clear()
    await message.answer(
        f"✅ Дата рождения обновлена: <b>{bd.strftime('%d.%m.%Y')}</b>\n"
        f"Возраст: <b>{calculate_age(bd)} лет</b>",
        parse_mode="HTML", reply_markup=main_menu_kb()
    )
    user = await get_user_by_id(message.from_user.id)
    await send_profile(message, message.from_user.id, user, bot, is_self=True)


# ─── Toggle stats public ─────────────────────────────────────────────────────

@router.callback_query(F.data == "toggle_stats_public")
async def callback_toggle_stats_public(call: CallbackQuery, bot: Bot):
    new_val = await toggle_stats_public(call.from_user.id)
    status = "🔓 открыта для всех" if new_val else "🔒 скрыта"
    await call.answer(f"Статистика {status}")
    # Refresh the keyboard in place
    user = await get_user_by_id(call.from_user.id)
    if user:
        tracking = await is_tracking(call.from_user.id, call.from_user.id)
        kb = profile_kb(call.from_user.id, tracking, is_self=True, stats_public=new_val)
        try:
            await call.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass


# ─── View someone's public stats ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("view_stats:"))
async def callback_view_stats(call: CallbackQuery):
    target_id = int(call.data.split(":")[1])

    # Own profile — redirect to /mystats logic inline
    if target_id == call.from_user.id:
        await call.answer()
        user = await get_user_by_id(target_id)
        if not user:
            return
        await _send_my_stats_message(call.message, user)
        return

    target = await get_user_by_id(target_id)
    if not target:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    if not target.get("stats_public"):
        await call.answer("🔒 Этот пользователь скрыл свою статистику.", show_alert=True)
        return

    name = f"@{target['username']}" if target.get("username") else target["first_name"]
    invited_count = await get_invited_count(target_id)
    title = get_title(invited_count)
    tracking_count = await get_tracking_count(target_id)
    watchers_count = await get_watchers_count(target_id)
    cstats = await get_congrats_stats(target_id)

    await call.answer()
    await call.message.answer(
        f"📊 <b>Статистика {name}</b>\n\n"
        f"🏅 Титул: <b>{title}</b>\n\n"
        f"🔔 Отслеживает: <b>{tracking_count}</b> чел.\n"
        f"👁 Отслеживают его: <b>{watchers_count}</b> чел.\n"
        f"🤝 Пригласил: <b>{invited_count}</b> чел.\n\n"
        f"🎉 Всего поздравлений: <b>{cstats['total_sent']}</b>\n"
        f"🔥 Текущая серия: <b>{streak_display(cstats['current_streak'])}</b> подряд\n"
        f"🏆 Рекорд серии: <b>{cstats['best_streak']}</b> подряд",
        parse_mode="HTML"
    )


async def _send_my_stats_message(message: Message, user: dict):
    """Shared helper to render the personal stats block."""
    uid = user["telegram_id"]
    invited_count = await get_invited_count(uid)
    title = get_title(invited_count)
    nt = next_title_info(invited_count)
    tracking_count = await get_tracking_count(uid)
    watchers_count = await get_watchers_count(uid)
    holiday_subs = await get_user_holiday_subscriptions(uid)
    events = await custom_event_get_all(uid)
    cstats = await get_congrats_stats(uid)
    streak = cstats["current_streak"]
    best = cstats["best_streak"]

    next_line = ""
    if nt:
        next_title_name, needed = nt
        next_line = f"\n⬆️ До титула <b>{next_title_name}</b>: ещё <b>{needed}</b> приглашений"

    await message.answer(
        f"📊 <b>Ваша личная статистика</b>\n\n"
        f"🏅 Титул: <b>{title}</b>{next_line}\n\n"
        f"🔔 Вы отслеживаете: <b>{tracking_count}</b> чел.\n"
        f"👁 Вас отслеживают: <b>{watchers_count}</b> чел.\n"
        f"🤝 Приглашено вами: <b>{invited_count}</b> чел.\n\n"
        f"🎉 Всего поздравлений: <b>{cstats['total_sent']}</b>\n"
        f"🔥 Текущая серия: <b>{streak_display(streak)}</b> подряд\n"
        f"🏆 Рекорд серии: <b>{best}</b> подряд\n\n"
        f"🗓 Подписок на праздники: <b>{len(holiday_subs)}</b>\n"
        f"✨ Личных событий: <b>{len(events)}</b>",
        parse_mode="HTML"
    )


# ─── Search ──────────────────────────────────────────────────────────────────

@router.message(F.text == "🔍 Найти пользователя")
@router.message(Command("search"))
async def search_start(message: Message, state: FSMContext):
    await state.clear()
    if not await require_registration(message):
        return
    await message.answer("🔍 Введите username пользователя (с @ или без):", reply_markup=cancel_kb())
    await state.set_state(Search.waiting_username)


@router.message(Search.waiting_username)
async def process_search(message: Message, state: FSMContext, bot: Bot):
    target = await get_user_by_username(message.text.strip())
    await state.clear()
    if not target:
        await message.answer(
            f"❌ Пользователь <b>{message.text}</b> не найден.",
            parse_mode="HTML", reply_markup=main_menu_kb()
        )
        return
    await message.answer("Вот что я нашёл:", reply_markup=main_menu_kb())
    await send_profile(message, message.from_user.id, target, bot)


# ─── Share / referral ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("share:"))
async def callback_share(call: CallbackQuery, bot: Bot):
    target_id = int(call.data.split(":")[1])
    target = await get_user_by_id(target_id)
    if not target:
        await call.answer("Профиль не найден.", show_alert=True)
        return

    me = await bot.get_me()
    name = f"@{target['username']}" if target["username"] else target["first_name"]
    link = make_profile_link(me.username, target_id)
    is_self = call.from_user.id == target_id

    note = (
        "👆 Это твоя реферальная ссылка!\n"
        "Поделись ею — когда друг зарегистрируется по ней, тебе зачтётся приглашение. 🎁"
        if is_self else
        "Перешли это сообщение тому, кому хочешь показать профиль."
    )

    await call.answer()
    await call.message.answer(
        f"🔗 <b>Ссылка на профиль {name}:</b>\n\n"
        f"<code>{link}</code>\n\n{note}",
        parse_mode="HTML"
    )


# ─── /invite ─────────────────────────────────────────────────────────────────

@router.message(Command("invite"))
async def cmd_invite(message: Message, bot: Bot):
    if not await require_registration(message):
        return
    me = await bot.get_me()
    uid = message.from_user.id
    link = make_profile_link(me.username, uid)
    invited_count = await get_invited_count(uid)
    title = get_title(invited_count)
    nt = next_title_info(invited_count)
    next_line = f"\n⬆️ До следующего титула: ещё <b>{nt[1]}</b> приглашений" if nt else ""

    rows = "\n".join(
        f"{'✅' if invited_count >= t else '⬜'} {n} — от {t} приглашений"
        for t, n in TITLES
    )
    await message.answer(
        f"🔗 <b>Ваша реферальная / профильная ссылка:</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Поделитесь ссылкой — когда новый пользователь зарегистрируется по ней, "
        f"вам автоматически зачтётся приглашение! 🎁\n\n"
        f"🏅 Ваш титул: <b>{title}</b>{next_line}\n"
        f"🤝 Уже пригласили: <b>{invited_count}</b> чел.\n\n"
        f"<b>Система титулов:</b>\n{rows}",
        parse_mode="HTML"
    )


# ─── Track / Untrack ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("track:"))
async def callback_track(call: CallbackQuery, bot: Bot):
    target_id = int(call.data.split(":")[1])
    target = await get_user_by_id(target_id)
    if not target:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    tracking = await is_tracking(call.from_user.id, target_id)
    username_display = f"@{target['username']}" if target["username"] else target["first_name"]
    is_self = call.from_user.id == target_id
    if tracking:
        await remove_tracking(call.from_user.id, target_id)
        await call.answer(f"❌ Вы больше не отслеживаете {username_display}")
        new_kb = profile_kb(target_id, False, is_self, stats_public=bool(target.get("stats_public", 0)))
    else:
        await add_tracking(call.from_user.id, target_id)
        await call.answer(f"✅ Вы начали отслеживать {username_display}")
        new_kb = profile_kb(target_id, True, is_self, stats_public=bool(target.get("stats_public", 0)))
    await call.message.edit_reply_markup(reply_markup=new_kb)


# ─── Back to profile ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("back_profile:"))
async def callback_back_profile(call: CallbackQuery, bot: Bot):
    target_id = int(call.data.split(":")[1])
    target = await get_user_by_id(target_id)
    if not target:
        await call.answer("Профиль не найден.", show_alert=True)
        return
    await call.message.delete()
    is_self = call.from_user.id == target_id
    await send_profile(call.message, call.from_user.id, target, bot, is_self=is_self)


# ─── Congrats ─────────────────────────────────────────────────────────────────

async def _do_congratulate(
    sender_id: int,
    target_id: int,
    congrats_text: str,
    bot: Bot,
    reply_to: Message | None = None,
    answer_to: CallbackQuery | None = None,
):
    target = await get_user_by_id(target_id)
    if not target:
        msg = "Пользователь не найден."
        if answer_to:
            await answer_to.answer(msg, show_alert=True)
        return

    birthday_year = date.today().year
    already = await has_congratulated_this_year(sender_id, target_id, birthday_year)
    if already:
        msg = "✅ Вы уже поздравляли этого человека в этом году!"
        if answer_to:
            await answer_to.answer(msg, show_alert=True)
        elif reply_to:
            await reply_to.answer(msg)
        return

    sender = await get_user_by_id(sender_id)
    sender_display = (
        f"@{sender['username']}" if (sender and sender.get("username"))
        else (sender["first_name"] if sender else "Кто-то")
    )

    try:
        await bot.send_message(
            target_id,
            f"🎉 <b>{sender_display} поздравляет тебя с днём рождения!</b>\n\n{congrats_text}",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Could not deliver congrats to {target_id}: {e}")

    stats = await record_congrats(sender_id, target_id, birthday_year)
    total = stats["total_sent"]
    streak = stats["current_streak"]
    best = stats["best_streak"]
    milestone = streak_milestone_text(streak)

    lines = [
        f"✅ Поздравление отправлено <b>{target['first_name']}</b>! 🎊",
        "",
        f"🎉 Всего поздравлений: <b>{total}</b>",
        f"🔥 Серия: <b>{streak_display(streak)}</b> подряд",
    ]
    if best > streak:
        lines.append(f"🏆 Рекорд: <b>{best}</b> поздравлений подряд")
    if milestone:
        lines += ["", f"🎆 <b>{milestone}</b>", "Вы настоящий мастер поздравлений! 🌟"]

    feedback = "\n".join(lines)

    if answer_to:
        await answer_to.answer("✅ Поздравление отправлено!")
        try:
            await answer_to.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await answer_to.message.answer(feedback, parse_mode="HTML")
    elif reply_to:
        await reply_to.answer(feedback, parse_mode="HTML")


@router.callback_query(F.data.startswith("congrats_tmpl:"))
async def callback_congrats_template(call: CallbackQuery, bot: Bot):
    _, target_str, idx_str = call.data.split(":")
    target_id = int(target_str)
    idx = int(idx_str)
    if idx < 0 or idx >= len(CONGRATS_TEMPLATES):
        await call.answer("Шаблон не найден.", show_alert=True)
        return
    _, text = CONGRATS_TEMPLATES[idx]
    await _do_congratulate(call.from_user.id, target_id, text, bot, answer_to=call)


@router.callback_query(F.data.startswith("congrats_emoji:"))
async def callback_congrats_emoji(call: CallbackQuery, bot: Bot):
    target_id = int(call.data.split(":")[1])
    await _do_congratulate(call.from_user.id, target_id, "🎂🎉🎊🥳🎈", bot, answer_to=call)


@router.callback_query(F.data.startswith("congrats_custom:"))
async def callback_congrats_custom_start(call: CallbackQuery, state: FSMContext):
    target_id = int(call.data.split(":")[1])
    await state.update_data(congrats_target_id=target_id)
    await call.answer()
    await call.message.answer(
        "✍️ Напишите своё поздравление — оно будет отправлено имениннику:",
        reply_markup=cancel_kb()
    )
    await state.set_state(CongratsCustom.waiting_text)


@router.message(CongratsCustom.waiting_text)
async def process_congrats_custom_text(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    if not text:
        await message.answer("❌ Текст не может быть пустым.")
        return
    if len(text) > 1000:
        await message.answer("❌ Слишком длинный текст. Максимум 1000 символов.")
        return
    data = await state.get_data()
    target_id = data.get("congrats_target_id")
    await state.clear()
    if not target_id:
        await message.answer("Ошибка: именинник не найден. Попробуйте снова.", reply_markup=main_menu_kb())
        return
    await message.answer("Отправляю поздравление...", reply_markup=main_menu_kb())
    await _do_congratulate(message.from_user.id, target_id, text, bot, reply_to=message)


# ─── Wishlist ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("wishlist_view:"))
async def callback_wishlist_view(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    owner = await get_user_by_id(owner_id)
    if not owner:
        await call.answer("Пользователь не найден.", show_alert=True)
        return
    items = await wishlist_get(owner_id)
    viewer_id = call.from_user.id
    is_owner = owner_id == viewer_id
    if not items:
        text = (
            "🎁 <b>Ваш вишлист пуст.</b>\n\nДобавьте пожелания — друзья увидят, что подарить!"
            if is_owner else f"🎁 <b>Вишлист {owner['first_name']} пуст.</b>"
        )
    else:
        name_part = "Ваш вишлист" if is_owner else f"Вишлист {owner['first_name']}"
        lines = [f"🎁 <b>{name_part}:</b>\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['item']}")
        text = "\n".join(lines)
    await call.answer()
    await call.message.answer(text, parse_mode="HTML",
                               reply_markup=wishlist_view_kb(items, owner_id, viewer_id))


@router.callback_query(F.data == "wish_add")
async def callback_wish_add(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("✏️ Введите пожелание:", reply_markup=cancel_kb())
    await state.set_state(WishlistAdd.waiting_item)


@router.message(WishlistAdd.waiting_item)
async def process_wish_add(message: Message, state: FSMContext):
    item_text = message.text.strip()
    if len(item_text) > 300:
        await message.answer("❌ Слишком длинно. Максимум 300 символов.")
        return
    if not item_text:
        await message.answer("❌ Пожелание не может быть пустым.")
        return
    await wishlist_add(message.from_user.id, item_text)
    await state.clear()
    items = await wishlist_get(message.from_user.id)
    lines = ["✅ Добавлено!\n\n🎁 <b>Ваш вишлист:</b>", ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['item']}")
    await message.answer("\n".join(lines), parse_mode="HTML",
                         reply_markup=wishlist_view_kb(items, message.from_user.id, message.from_user.id))


@router.callback_query(F.data.startswith("wish_del:"))
async def callback_wish_del(call: CallbackQuery):
    item_id = int(call.data.split(":")[1])
    await wishlist_delete(item_id, call.from_user.id)
    await call.answer("🗑 Удалено")
    items = await wishlist_get(call.from_user.id)
    text = (
        "🎁 <b>Ваш вишлист пуст.</b>\n\nДобавьте пожелания!"
        if not items else
        "\n".join(["🎁 <b>Ваш вишлист:</b>", ""] + [f"{i}. {it['item']}" for i, it in enumerate(items, 1)])
    )
    await call.message.edit_text(text, parse_mode="HTML",
                                  reply_markup=wishlist_view_kb(items, call.from_user.id, call.from_user.id))


@router.callback_query(F.data == "wish_clear")
async def callback_wish_clear(call: CallbackQuery):
    await wishlist_clear(call.from_user.id)
    await call.answer("🗑 Вишлист очищен")
    await call.message.edit_text(
        "🎁 <b>Ваш вишлист пуст.</b>\n\nДобавьте пожелания — друзья увидят, что подарить!",
        parse_mode="HTML",
        reply_markup=wishlist_view_kb([], call.from_user.id, call.from_user.id)
    )


# ─── My Trackings ────────────────────────────────────────────────────────────

@router.message(F.text == "⭐ Мои отслеживания")
@router.message(Command("friend"))
async def my_trackings(message: Message, state: FSMContext):
    await state.clear()
    if not await require_registration(message):
        return
    from database import DATABASE_PATH
    import aiosqlite
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.* FROM users u
            JOIN tracking t ON t.target_id = u.telegram_id
            WHERE t.watcher_id = ?
        """, (message.from_user.id,)) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    if not rows:
        await message.answer("У вас нет отслеживаемых пользователей.\n\nНайдите кого-нибудь через /search.")
        return
    lines = ["⭐ <b>Вы отслеживаете:</b>\n"]
    for u in rows:
        bd = parse_birthdate(u["birthdate"])
        days = days_until_birthday(bd)
        name = f"@{u['username']}" if u["username"] else u["first_name"]
        label = "🎂 сегодня!" if days == 0 else ("🎉 завтра!" if days == 1 else f"через {days} дн.")
        lines.append(f"• {name} — {label}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── My Stats (/mystats) ─────────────────────────────────────────────────────

@router.message(F.text == "📊 Моя статистика")
@router.message(Command("mystats"))
async def my_stats(message: Message, bot: Bot):
    if not await require_registration(message):
        return
    uid = message.from_user.id
    invited_count = await get_invited_count(uid)
    title = get_title(invited_count)
    nt = next_title_info(invited_count)
    tracking_count = await get_tracking_count(uid)
    watchers_count = await get_watchers_count(uid)
    holiday_subs = await get_user_holiday_subscriptions(uid)
    events = await custom_event_get_all(uid)
    cstats = await get_congrats_stats(uid)
    streak = cstats["current_streak"]
    best = cstats["best_streak"]

    me = await bot.get_me()
    link = make_profile_link(me.username, uid)

    next_line = ""
    if nt:
        next_title_name, needed = nt
        next_line = f"\n⬆️ До титула <b>{next_title_name}</b>: ещё <b>{needed}</b> приглашений"

    await message.answer(
        f"📊 <b>Ваша личная статистика</b>\n\n"
        f"🏅 Титул: <b>{title}</b>{next_line}\n\n"
        f"🔔 Вы отслеживаете: <b>{tracking_count}</b> чел.\n"
        f"👁 Вас отслеживают: <b>{watchers_count}</b> чел.\n"
        f"🤝 Приглашено вами: <b>{invited_count}</b> чел.\n\n"
        f"🎉 Всего поздравлений: <b>{cstats['total_sent']}</b>\n"
        f"🔥 Текущая серия: <b>{streak_display(streak)}</b> подряд\n"
        f"🏆 Рекорд серии: <b>{best}</b> подряд\n\n"
        f"🗓 Подписок на праздники: <b>{len(holiday_subs)}</b>\n"
        f"✨ Личных событий: <b>{len(events)}</b>\n\n"
        f"🔗 <b>Ваша ссылка (профиль + реферал):</b>\n"
        f"<code>{link}</code>",
        parse_mode="HTML"
    )


# ─── Праздники (/holidays) ───────────────────────────────────────────────────

@router.message(F.text == "🗓 Праздники")
@router.message(Command("holidays"))
async def cmd_holidays(message: Message, state: FSMContext):
    await state.clear()
    if not await require_registration(message):
        return
    await message.answer(
        "🗓 <b>Праздники и события</b>\n\n"
        "Подпишитесь на популярные праздники — и я напомню заранее.\n"
        "Или создайте своё личное событие! 🎉",
        parse_mode="HTML", reply_markup=holidays_main_kb()
    )


@router.callback_query(F.data == "holidays_back")
async def callback_holidays_back(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "🗓 <b>Праздники и события</b>\n\n"
        "Подпишитесь на популярные праздники — и я напомню заранее.\n"
        "Или создайте своё личное событие! 🎉",
        parse_mode="HTML", reply_markup=holidays_main_kb()
    )


@router.callback_query(F.data == "holidays_catalog")
async def callback_holidays_catalog(call: CallbackQuery):
    await call.answer()
    subs = set(await get_user_holiday_subscriptions(call.from_user.id))
    sorted_h = sorted(HOLIDAYS, key=lambda h: days_until_holiday(h["month"], h["day"]))
    await call.message.edit_text(
        "🌍 <b>Популярные праздники</b>\n\n✅ — подписаны | ➕ — нажмите чтобы подписаться",
        parse_mode="HTML", reply_markup=holidays_catalog_kb(sorted_h, subs)
    )


@router.callback_query(F.data.startswith("hcat_page:"))
async def callback_hcat_page(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    subs = set(await get_user_holiday_subscriptions(call.from_user.id))
    sorted_h = sorted(HOLIDAYS, key=lambda h: days_until_holiday(h["month"], h["day"]))
    await call.answer()
    await call.message.edit_text(
        "🌍 <b>Популярные праздники</b>\n\n✅ — подписаны | ➕ — нажмите чтобы подписаться",
        parse_mode="HTML", reply_markup=holidays_catalog_kb(sorted_h, subs, page=page)
    )


@router.callback_query(F.data.startswith("htoggle:"))
async def callback_holiday_toggle(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    holiday = HOLIDAYS_BY_KEY.get(key)
    if not holiday:
        await call.answer("Праздник не найден.", show_alert=True)
        return
    uid = call.from_user.id
    if await holiday_is_subscribed(uid, key):
        await holiday_unsubscribe(uid, key)
        await call.answer(f"❌ Отписались от «{holiday['name']}»")
    else:
        await holiday_subscribe(uid, key)
        days = days_until_holiday(holiday["month"], holiday["day"])
        await call.answer(f"✅ Подписались! Через {days} дн.")
    subs = set(await get_user_holiday_subscriptions(uid))
    sorted_h = sorted(HOLIDAYS, key=lambda h: days_until_holiday(h["month"], h["day"]))
    try:
        await call.message.edit_text(
            "🌍 <b>Популярные праздники</b>\n\n✅ — подписаны | ➕ — нажмите чтобы подписаться",
            parse_mode="HTML", reply_markup=holidays_catalog_kb(sorted_h, subs)
        )
    except Exception:
        pass


@router.callback_query(F.data == "holidays_my")
async def callback_holidays_my(call: CallbackQuery):
    await call.answer()
    sub_keys = await get_user_holiday_subscriptions(call.from_user.id)
    subscribed = sorted(
        [HOLIDAYS_BY_KEY[k] for k in sub_keys if k in HOLIDAYS_BY_KEY],
        key=lambda h: days_until_holiday(h["month"], h["day"])
    )
    if not subscribed:
        text = "✨ <b>Ваши подписки пусты.</b>\n\nПерейдите в каталог и выберите праздники!"
    else:
        lines = ["✨ <b>Ваши подписки на праздники:</b>\n"]
        for h in subscribed:
            d = days_until_holiday(h["month"], h["day"])
            lines.append(f"{h['emoji']} <b>{h['name']}</b> — через {d} дн.")
        text = "\n".join(lines)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=my_holidays_kb(subscribed))


# ─── Custom events ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "events_my")
async def callback_events_my(call: CallbackQuery):
    await call.answer()
    events = await custom_event_get_all(call.from_user.id)
    if not events:
        text = "📅 <b>У вас нет личных событий.</b>\n\nСоздайте своё событие — и я напомню заранее!"
    else:
        lines = ["📅 <b>Ваши личные события:</b>\n"]
        for ev in events:
            ri = "🔁" if ev["repeat"] else "1️⃣"
            try:
                day, month = int(ev["date_str"].split(".")[0]), int(ev["date_str"].split(".")[1])
                d = days_until_holiday(month, day)
                ds = f"через {d} дн."
            except Exception:
                ds = ev["date_str"]
            lines.append(f"{ri} <b>{ev['title']}</b> ({ev['date_str']}) — {ds}")
        text = "\n".join(lines)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=my_events_kb(events))


@router.callback_query(F.data == "event_create")
async def callback_event_create(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "✨ <b>Создание личного события</b>\n\nВведите название события:",
        parse_mode="HTML", reply_markup=cancel_kb()
    )
    await state.set_state(CustomEvent.waiting_title)


@router.callback_query(F.data == "event_create_cancel")
async def callback_event_create_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer("Отменено")
    await call.message.edit_text(
        "🗓 <b>Праздники и события</b>", parse_mode="HTML", reply_markup=holidays_main_kb()
    )


@router.message(CustomEvent.waiting_title)
async def process_event_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not title or len(title) > 100:
        await message.answer("❌ Название должно быть от 1 до 100 символов.")
        return
    await state.update_data(event_title=title)
    await message.answer("📅 Введите дату: <b>дд.мм</b> или <b>дд.мм.гггг</b>:", parse_mode="HTML")
    await state.set_state(CustomEvent.waiting_date)


@router.message(CustomEvent.waiting_date)
async def process_event_date(message: Message, state: FSMContext):
    raw = message.text.strip()
    date_str = None
    for fmt in ("%d.%m.%Y", "%d.%m"):
        try:
            datetime.strptime(raw, fmt)
            date_str = raw
            break
        except ValueError:
            pass
    if date_str is None:
        await message.answer("❌ Неверный формат. Введите дд.мм или дд.мм.гггг.")
        return
    await state.update_data(event_date=date_str)
    await message.answer("🔁 <b>Как повторять?</b>", parse_mode="HTML", reply_markup=event_repeat_kb())
    await state.set_state(CustomEvent.waiting_repeat)


@router.callback_query(F.data.startswith("event_repeat:"))
async def process_event_repeat(call: CallbackQuery, state: FSMContext):
    repeat = int(call.data.split(":")[1])
    data = await state.get_data()
    await state.clear()
    title = data.get("event_title", "")
    date_str = data.get("event_date", "")
    await custom_event_add(call.from_user.id, title, date_str, bool(repeat))
    await call.answer("✅ Событие создано!")
    repeat_label = "ежегодно 🔁" if repeat else "один раз 1️⃣"
    await call.message.edit_text(
        f"✅ <b>Событие создано!</b>\n\n"
        f"📌 <b>{title}</b>\n📅 Дата: <b>{date_str}</b>\n🔄 Повтор: {repeat_label}\n\n"
        f"Я напомню за 3 дня до события!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мои события", callback_data="events_my")],
            [InlineKeyboardButton(text="◀️ Меню праздников", callback_data="holidays_back")],
        ])
    )


@router.callback_query(F.data.startswith("event_del:"))
async def callback_event_del(call: CallbackQuery):
    event_id = int(call.data.split(":")[1])
    await custom_event_delete(event_id, call.from_user.id)
    await call.answer("🗑 Удалено")
    events = await custom_event_get_all(call.from_user.id)
    text = (
        "📅 <b>У вас нет личных событий.</b>" if not events else
        "\n".join(["📅 <b>Ваши личные события:</b>\n"] +
                  [f"{'🔁' if ev['repeat'] else '1️⃣'} <b>{ev['title']}</b> ({ev['date_str']})"
                   for ev in events])
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=my_events_kb(events))


# ─── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Все команды BuddyWish:</b>\n\n"
        "👤 <b>Профиль и поиск</b>\n"
        "/start — начало работы / регистрация\n"
        "/me — мой профиль\n"
        "/search — найти пользователя по @username\n"
        "/friend — список отслеживаемых друзей\n\n"
        "🎉 <b>Поздравления</b>\n"
        "В уведомлении о ДР нажмите кнопку — выберите шаблон,\n"
        "напишите своё или отправьте эмодзи!\n"
        "Поздравляйте друзей подряд и бейте рекорды серии 🔥\n\n"
        "🗓 <b>Праздники и события</b>\n"
        "/holidays — меню праздников и личных событий\n\n"
        "📊 <b>Статистика и рефералы</b>\n"
        "/mystats — статистика, серия и рекорд поздравлений\n"
        "/invite — реферальная ссылка + система титулов\n\n"
        "ℹ️ <b>Прочее</b>\n"
        "/help — это сообщение\n"
        "/admin — панель администратора (только для админов)\n\n"
        "🔒 <b>Открытая статистика</b>\n"
        "В своём профиле нажмите кнопку «🔒 Статистика: скрыта»,\n"
        "чтобы разрешить другим смотреть вашу статистику.",
        parse_mode="HTML"
    )


# ─── Admin ────────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    logger.info(f"/admin от user_id={message.from_user.id} | ADMIN_IDS={ADMIN_IDS}")
    if not is_admin(message.from_user.id):
        await message.answer(
            f"❌ Доступ запрещён.\n\n"
            f"<i>Ваш ID: <code>{message.from_user.id}</code>\n"
            f"Добавьте его в ADMIN_IDS в файле .env</i>",
            parse_mode="HTML"
        )
        return
    await message.answer("🛡 <b>Панель администратора</b>", parse_mode="HTML", reply_markup=admin_menu_kb())


@router.message(F.text == "🔙 Главное меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню", reply_markup=main_menu_kb())


@router.message(F.text == "👥 Статистика пользователей")
@router.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён.")
        return
    from database import DATABASE_PATH
    import aiosqlite
    total = await get_users_count()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM tracking") as cur:
            total_trackings = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM wishlist") as cur:
            total_wishes = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM broadcasts WHERE active = 1") as cur:
            active_broadcasts = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM holiday_tracking") as cur:
            total_holiday_subs = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM congrats_log") as cur:
            total_congrats = (await cur.fetchone())[0]
        async with db.execute("SELECT MAX(best_streak) FROM congrats_stats") as cur:
            top_streak = (await cur.fetchone())[0] or 0

    await message.answer(
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"⭐ Подписок на ДР: <b>{total_trackings}</b>\n"
        f"🎁 Пожеланий в вишлистах: <b>{total_wishes}</b>\n"
        f"🗓 Подписок на праздники: <b>{total_holiday_subs}</b>\n"
        f"🎉 Всего поздравлений: <b>{total_congrats}</b>\n"
        f"🔥 Рекордная серия в боте: <b>{top_streak}</b> подряд\n"
        f"📢 Активных рассылок: <b>{active_broadcasts}</b>",
        parse_mode="HTML"
    )


@router.message(Command("users"))
async def admin_users_list(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён.")
        return
    await _send_users_page(message, page=0)


async def _send_users_page(message: Message, page: int):
    users = await get_all_users()
    total = len(users)
    total_pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = users[page * USERS_PAGE_SIZE:(page + 1) * USERS_PAGE_SIZE]
    lines = [f"👥 <b>Пользователи ({total}) — стр. {page + 1}/{total_pages}:</b>\n"]
    for i, u in enumerate(chunk, page * USERS_PAGE_SIZE + 1):
        username = f" (@{u['username']})" if u["username"] else ""
        lines.append(f"{i}. {u['first_name']}{username} | {u.get('birthdate') or '—'}")
    await message.answer("\n".join(lines), parse_mode="HTML",
                         reply_markup=users_list_kb(page, total_pages))


@router.callback_query(F.data.startswith("users_page:"))
async def callback_users_page(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    page = int(call.data.split(":")[1])
    users = await get_all_users()
    total = len(users)
    total_pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = users[page * USERS_PAGE_SIZE:(page + 1) * USERS_PAGE_SIZE]
    lines = [f"👥 <b>Пользователи ({total}) — стр. {page + 1}/{total_pages}:</b>\n"]
    for i, u in enumerate(chunk, page * USERS_PAGE_SIZE + 1):
        username = f" (@{u['username']})" if u["username"] else ""
        lines.append(f"{i}. {u['first_name']}{username} | {u.get('birthdate') or '—'}")
    await call.answer()
    await call.message.edit_text("\n".join(lines), parse_mode="HTML",
                                  reply_markup=users_list_kb(page, total_pages))


@router.callback_query(F.data == "noop")
async def callback_noop(call: CallbackQuery):
    await call.answer()


# ─── Admin: broadcast ────────────────────────────────────────────────────────

def _broadcast_skip_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⏩ Без фото")], [KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


@router.message(F.text == "📢 Создать рассылку")
async def admin_broadcast_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🖼 <b>Шаг 1/5:</b> Отправьте фото или нажмите «⏩ Без фото»",
        parse_mode="HTML", reply_markup=_broadcast_skip_kb()
    )
    await state.set_state(AdminBroadcast.waiting_photo)


@router.message(AdminBroadcast.waiting_photo)
async def admin_broadcast_photo(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(photo_file_id=message.photo[-1].file_id)
    elif message.text == "⏩ Без фото":
        await state.update_data(photo_file_id=None)
    else:
        await message.answer("❌ Отправьте фото или нажмите «⏩ Без фото».")
        return
    await message.answer("✏️ <b>Шаг 2/5:</b> Введите текст рассылки:",
                         parse_mode="HTML", reply_markup=cancel_kb())
    await state.set_state(AdminBroadcast.waiting_text)


@router.message(AdminBroadcast.waiting_text)
async def admin_broadcast_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("🔄 <b>Шаг 3/5:</b> Периодичность в днях (1 = каждый день, 7 = раз в неделю):",
                         parse_mode="HTML")
    await state.set_state(AdminBroadcast.waiting_interval)


@router.message(AdminBroadcast.waiting_interval)
async def admin_broadcast_interval(message: Message, state: FSMContext):
    try:
        interval = int(message.text)
        if interval < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число ≥ 1.")
        return
    await state.update_data(interval=interval)
    await message.answer(
        "📅 <b>Шаг 4/5:</b> Дата и время первой отправки:\n"
        "Формат: <b>дд.мм.гггг чч:мм</b>  Пример: <code>15.06.2025 09:00</code>",
        parse_mode="HTML"
    )
    await state.set_state(AdminBroadcast.waiting_start_datetime)


@router.message(AdminBroadcast.waiting_start_datetime)
async def admin_broadcast_start_datetime(message: Message, state: FSMContext):
    try:
        start_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Формат: <code>дд.мм.гггг чч:мм</code>", parse_mode="HTML")
        return
    if start_dt < datetime.now():
        await message.answer("❌ Дата уже прошла.")
        return
    await state.update_data(start_datetime=message.text.strip())
    await message.answer("📅 <b>Шаг 5/5:</b> Дата окончания (дд.мм.гггг):", parse_mode="HTML")
    await state.set_state(AdminBroadcast.waiting_end_date)


@router.message(AdminBroadcast.waiting_end_date)
async def admin_broadcast_end_date(message: Message, state: FSMContext):
    ed = parse_birthdate(message.text)
    if not ed or ed <= date.today():
        await message.answer("❌ Введите будущую дату дд.мм.гггг.")
        return
    data = await state.get_data()
    await add_broadcast(data["text"], data["interval"], data["start_datetime"],
                        ed.isoformat(), photo_file_id=data.get("photo_file_id"))
    await state.clear()
    preview = data["text"][:80] + ("..." if len(data["text"]) > 80 else "")
    photo_note = "🖼 С фото" if data.get("photo_file_id") else "📝 Без фото"
    await message.answer(
        f"✅ Рассылка создана!\n\n{photo_note}\n📝 {preview}\n"
        f"🕐 Первая: <b>{data['start_datetime']}</b>\n"
        f"🔄 Каждые <b>{data['interval']}</b> дн.\n"
        f"📅 До <b>{ed.strftime('%d.%m.%Y')}</b>",
        parse_mode="HTML", reply_markup=admin_menu_kb()
    )


@router.message(F.text == "📋 Список рассылок")
async def admin_broadcasts_list(message: Message):
    if not is_admin(message.from_user.id):
        return
    broadcasts = await get_all_broadcasts()
    if not broadcasts:
        await message.answer("Рассылок нет.", reply_markup=admin_menu_kb())
        return
    lines = ["📋 <b>Все рассылки:</b>\n"]
    buttons = []
    for bc in broadcasts:
        status = "✅ Активна" if bc["active"] else "❌ Завершена"
        last = bc["last_sent"] or "не отправлялась"
        preview = bc["message_text"][:50] + ("..." if len(bc["message_text"]) > 50 else "")
        photo_note = " 🖼" if bc.get("photo_file_id") else ""
        lines.append(
            f"<b>#{bc['id']}</b> {status}{photo_note}\n"
            f"📝 {preview}\n"
            f"🕐 {bc.get('start_datetime', '—')} | 🔄 {bc['interval_days']} дн.\n"
            f"📅 До {bc['end_date']} | Последняя: {last}\n"
        )
        if bc["active"]:
            buttons.append([InlineKeyboardButton(
                text=f"⛔ Остановить #{bc['id']}", callback_data=f"stop_bc:{bc['id']}"
            )])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("stop_bc:"))
async def callback_stop_broadcast(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    bc_id = int(call.data.split(":")[1])
    await deactivate_broadcast(bc_id)
    await call.answer(f"✅ Рассылка #{bc_id} остановлена")
    await call.message.edit_reply_markup(reply_markup=None)


@router.message(F.text == "📡 Управление каналами")
async def admin_channels(message: Message):
    if not is_admin(message.from_user.id):
        return
    channels = await get_all_channels()
    text = f"📡 <b>Каналы ({len(channels)}):</b>" if channels else "📡 Каналов нет. Добавьте первый:"
    await message.answer(text, parse_mode="HTML", reply_markup=channel_management_kb(channels))


@router.callback_query(F.data == "add_channel")
async def callback_add_channel(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.answer(
        "📡 Перешлите сообщение из канала или введите @username / ID:",
        reply_markup=cancel_kb()
    )
    await state.set_state(AdminChannel.waiting_channel)


@router.message(AdminChannel.waiting_channel)
async def process_add_channel(message: Message, state: FSMContext, bot: Bot):
    if message.forward_from_chat:
        chat = message.forward_from_chat
        channel_id, title = str(chat.id), chat.title
    else:
        channel_id = message.text.strip()
        try:
            chat = await bot.get_chat(channel_id)
            title = chat.title or channel_id
        except Exception:
            await message.answer("❌ Не удалось найти канал.")
            return
    await add_channel(channel_id, title)
    await state.clear()
    await message.answer(f"✅ Канал <b>{title}</b> добавлен!", parse_mode="HTML", reply_markup=admin_menu_kb())


@router.callback_query(F.data.startswith("del_channel:"))
async def callback_del_channel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    channel_id = call.data.split(":", 1)[1]
    await remove_channel(channel_id)
    await call.answer("✅ Канал удалён")
    channels = await get_all_channels()
    await call.message.edit_reply_markup(reply_markup=channel_management_kb(channels))
