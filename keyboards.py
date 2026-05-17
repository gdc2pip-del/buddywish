from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Найти пользователя")],
            [KeyboardButton(text="📋 Мой профиль"), KeyboardButton(text="⭐ Мои отслеживания")],
            [KeyboardButton(text="🗓 Праздники"), KeyboardButton(text="📊 Моя статистика")],
        ],
        resize_keyboard=True
    )


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📢 Создать рассылку")],
            [KeyboardButton(text="📋 Список рассылок")],
            [KeyboardButton(text="📡 Управление каналами")],
            [KeyboardButton(text="👥 Статистика пользователей")],
            [KeyboardButton(text="🔙 Главное меню")],
        ],
        resize_keyboard=True
    )


def profile_kb(
    target_id: int,
    is_tracking: bool,
    is_self: bool,
    stats_public: bool = False,
) -> InlineKeyboardMarkup:
    buttons = []

    # Row 1: track + wishlist (or just wishlist for own profile)
    row1 = []
    if not is_self:
        track_text = "❌ Не отслеживать" if is_tracking else "🔔 Отслеживать"
        row1.append(InlineKeyboardButton(text=track_text, callback_data=f"track:{target_id}"))
        row1.append(InlineKeyboardButton(text="🎁 Вишлист", callback_data=f"wishlist_view:{target_id}"))
        buttons.append(row1)
        # Stats button for other people's profiles (shows only if they made it public)
        buttons.append([InlineKeyboardButton(
            text="📊 Статистика",
            callback_data=f"view_stats:{target_id}"
        )])
    else:
        row1.append(InlineKeyboardButton(text="🎁 Вишлист", callback_data=f"wishlist_view:{target_id}"))
        buttons.append(row1)

    # Share / referral link
    buttons.append([InlineKeyboardButton(
        text="🔗 Поделиться профилем",
        callback_data=f"share:{target_id}"
    )])

    # Self-only controls
    if is_self:
        buttons.append([InlineKeyboardButton(
            text="✏️ Изменить дату рождения",
            callback_data="edit_birthdate"
        )])
        stats_icon = "🔓" if stats_public else "🔒"
        stats_label = "открыта для всех" if stats_public else "скрыта"
        buttons.append([InlineKeyboardButton(
            text=f"{stats_icon} Статистика: {stats_label}",
            callback_data="toggle_stats_public"
        )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def wishlist_view_kb(items: list[dict], owner_id: int, viewer_id: int) -> InlineKeyboardMarkup:
    buttons = []
    is_owner = owner_id == viewer_id

    if is_owner:
        for item in items:
            buttons.append([InlineKeyboardButton(
                text=f"🗑 {item['item'][:40]}",
                callback_data=f"wish_del:{item['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="➕ Добавить пожелание", callback_data="wish_add")])
        if items:
            buttons.append([InlineKeyboardButton(text="🗑 Очистить всё", callback_data="wish_clear")])

    buttons.append([InlineKeyboardButton(text="◀️ Назад к профилю", callback_data=f"back_profile:{owner_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def channel_management_kb(channels: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(
            text=f"❌ Удалить: {ch['title']}",
            callback_data=f"del_channel:{ch['channel_id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


def users_list_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"users_page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"users_page:{page + 1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Congrats keyboard ────────────────────────────────────────────────────────

CONGRATS_TEMPLATES = [
    ("🎉 С днём рождения!", "🎉 С днём рождения! Желаю счастья, здоровья и всего самого лучшего! 🎂"),
    ("🥳 Ура, именинник!", "🥳 Ура, именинник! Пусть этот день будет самым ярким! Отмечай на полную! 🎊"),
    ("🎂 Сто лет жизни!", "🎂 С днём рождения! Желаю долгих лет жизни, крепкого здоровья и радости каждый день! 🌟"),
    ("💐 Тепла и любви!", "💐 С днём рождения! Пусть в твоей жизни будет много тепла, любви и добрых людей рядом! ❤️"),
    ("🚀 Новых высот!", "🚀 С днём рождения! Пусть этот год принесёт тебе новые вершины, открытия и победы! ⭐"),
    ("✨ Сбычи мечт!", "✨ С днём рождения! Пусть все задуманное сбудется, а мечты воплотятся в жизнь! 🌈"),
]


def congrats_kb(target_id: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, (label, _) in enumerate(CONGRATS_TEMPLATES):
        row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"congrats_tmpl:{target_id}:{i}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="✍️ Написать своё поздравление",
        callback_data=f"congrats_custom:{target_id}"
    )])
    buttons.append([InlineKeyboardButton(
        text="🎈 Поздравить без текста (эмодзи)",
        callback_data=f"congrats_emoji:{target_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Holidays ─────────────────────────────────────────────────────────────────

def holidays_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Популярные праздники", callback_data="holidays_catalog")],
        [InlineKeyboardButton(text="✨ Мои подписки на праздники", callback_data="holidays_my")],
        [InlineKeyboardButton(text="📅 Мои события", callback_data="events_my")],
        [InlineKeyboardButton(text="➕ Создать своё событие", callback_data="event_create")],
    ])


def holidays_catalog_kb(holidays: list[dict], subscribed_keys: set[str],
                         page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    total = len(holidays)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    chunk = holidays[page * page_size:(page + 1) * page_size]

    buttons = []
    for h in chunk:
        is_sub = h["key"] in subscribed_keys
        icon = "✅" if is_sub else "➕"
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {h['emoji']} {h['name']}",
            callback_data=f"htoggle:{h['key']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"hcat_page:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"hcat_page:{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="holidays_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def my_holidays_kb(subscribed: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for h in subscribed:
        buttons.append([InlineKeyboardButton(
            text=f"❌ {h['emoji']} {h['name']}",
            callback_data=f"htoggle:{h['key']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="holidays_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def my_events_kb(events: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for ev in events:
        repeat_icon = "🔁" if ev["repeat"] else "1️⃣"
        buttons.append([InlineKeyboardButton(
            text=f"🗑 {repeat_icon} {ev['title'][:35]} ({ev['date_str']})",
            callback_data=f"event_del:{ev['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Создать событие", callback_data="event_create")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="holidays_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def event_repeat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔁 Каждый год", callback_data="event_repeat:1"),
            InlineKeyboardButton(text="1️⃣ Один раз", callback_data="event_repeat:0"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="event_create_cancel")],
    ])
