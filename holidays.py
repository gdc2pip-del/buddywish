"""
holidays.py — Каталог популярных праздников.

Формат каждой записи:
    key        — уникальный строковый ключ (хранится в БД)
    emoji      — один или несколько эмодзи
    name       — отображаемое название
    month      — месяц (1–12)
    day        — день месяца (1–31)
    advance_days — за сколько дней предупреждать (по умолчанию 3)
"""

HOLIDAYS: list[dict] = [
    # ── Зима ─────────────────────────────────────────────────────────────────
    {
        "key": "new_year",
        "emoji": "🎆",
        "name": "Новый год",
        "month": 1, "day": 1,
        "advance_days": 7,
    },
    {
        "key": "old_new_year",
        "emoji": "🥂",
        "name": "Старый Новый год",
        "month": 1, "day": 14,
        "advance_days": 3,
    },
    {
        "key": "christmas_orthodox",
        "emoji": "⛪",
        "name": "Рождество Христово (православное)",
        "month": 1, "day": 7,
        "advance_days": 3,
    },
    {
        "key": "christmas_catholic",
        "emoji": "🎄",
        "name": "Рождество Христово (католическое)",
        "month": 12, "day": 25,
        "advance_days": 7,
    },
    {
        "key": "valentine",
        "emoji": "💝",
        "name": "День святого Валентина",
        "month": 2, "day": 14,
        "advance_days": 3,
    },
    {
        "key": "defender_day",
        "emoji": "🪖",
        "name": "День защитника Отечества",
        "month": 2, "day": 23,
        "advance_days": 3,
    },
    # ── Весна ─────────────────────────────────────────────────────────────────
    {
        "key": "womens_day",
        "emoji": "🌷",
        "name": "Международный женский день (8 Марта)",
        "month": 3, "day": 8,
        "advance_days": 3,
    },
    {
        "key": "spring_first",
        "emoji": "🌸",
        "name": "Первый день весны",
        "month": 3, "day": 1,
        "advance_days": 1,
    },
    {
        "key": "april_fools",
        "emoji": "🤡",
        "name": "День дурака (1 апреля)",
        "month": 4, "day": 1,
        "advance_days": 1,
    },
    {
        "key": "cosmonautics",
        "emoji": "🚀",
        "name": "День космонавтики",
        "month": 4, "day": 12,
        "advance_days": 2,
    },
    {
        "key": "labor_day",
        "emoji": "✊",
        "name": "День труда (1 Мая)",
        "month": 5, "day": 1,
        "advance_days": 3,
    },
    {
        "key": "victory_day",
        "emoji": "🎖️",
        "name": "День Победы (9 Мая)",
        "month": 5, "day": 9,
        "advance_days": 3,
    },
    # ── Лето ──────────────────────────────────────────────────────────────────
    {
        "key": "summer_first",
        "emoji": "☀️",
        "name": "Первый день лета",
        "month": 6, "day": 1,
        "advance_days": 1,
    },
    {
        "key": "children_day",
        "emoji": "🧒",
        "name": "День защиты детей",
        "month": 6, "day": 1,
        "advance_days": 2,
    },
    {
        "key": "russia_day",
        "emoji": "🇷🇺",
        "name": "День России",
        "month": 6, "day": 12,
        "advance_days": 2,
    },
    {
        "key": "ivan_kupala",
        "emoji": "🔥",
        "name": "Иван Купала",
        "month": 7, "day": 7,
        "advance_days": 2,
    },
    {
        "key": "family_day",
        "emoji": "👨‍👩‍👧",
        "name": "День семьи, любви и верности",
        "month": 7, "day": 8,
        "advance_days": 2,
    },
    # ── Осень ─────────────────────────────────────────────────────────────────
    {
        "key": "autumn_first",
        "emoji": "🍂",
        "name": "Первый день осени",
        "month": 9, "day": 1,
        "advance_days": 1,
    },
    {
        "key": "knowledge_day",
        "emoji": "📚",
        "name": "День знаний (1 Сентября)",
        "month": 9, "day": 1,
        "advance_days": 2,
    },
    {
        "key": "teacher_day",
        "emoji": "👩‍🏫",
        "name": "День учителя",
        "month": 10, "day": 5,
        "advance_days": 2,
    },
    {
        "key": "halloween",
        "emoji": "🎃",
        "name": "Хэллоуин",
        "month": 10, "day": 31,
        "advance_days": 3,
    },
    {
        "key": "unity_day",
        "emoji": "🤝",
        "name": "День народного единства",
        "month": 11, "day": 4,
        "advance_days": 2,
    },
    {
        "key": "mother_day",
        "emoji": "💐",
        "name": "День матери (последнее воскресенье ноября)",
        "month": 11, "day": 28,
        "advance_days": 3,
    },
    # ── Конец года ────────────────────────────────────────────────────────────
    {
        "key": "new_year_eve",
        "emoji": "🎇",
        "name": "Канун Нового года (31 декабря)",
        "month": 12, "day": 31,
        "advance_days": 3,
    },
    {
        "key": "winter_first",
        "emoji": "❄️",
        "name": "Первый день зимы",
        "month": 12, "day": 1,
        "advance_days": 1,
    },
]

# Быстрый доступ по ключу
HOLIDAYS_BY_KEY: dict[str, dict] = {h["key"]: h for h in HOLIDAYS}


def days_until_holiday(month: int, day: int) -> int:
    """Сколько дней до ближайшего наступления этого праздника."""
    from datetime import date
    today = date.today()
    try:
        next_hd = date(today.year, month, day)
    except ValueError:
        return 999
    if next_hd < today:
        try:
            next_hd = date(today.year + 1, month, day)
        except ValueError:
            return 999
    return (next_hd - today).days
