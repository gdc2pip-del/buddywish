from datetime import date, datetime


def parse_birthdate(text: str) -> date | None:
    """Parse dd.mm.yyyy → date. Returns None on failure."""
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def calculate_age(birthdate: date) -> int:
    today = date.today()
    age = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        age -= 1
    return age


def days_until_birthday(birthdate: date) -> int:
    today = date.today()
    next_bd = birthdate.replace(year=today.year)
    if next_bd < today:
        next_bd = next_bd.replace(year=today.year + 1)
    return (next_bd - today).days


def format_birthdate(birthdate_str: str) -> str:
    """Format stored dd.mm.yyyy string for display."""
    return birthdate_str
