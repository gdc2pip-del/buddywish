import aiosqlite
from config import DATABASE_PATH


async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                birthdate     TEXT,
                invited_by    INTEGER,
                stats_public  INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracking (
                watcher_id   INTEGER,
                target_id    INTEGER,
                PRIMARY KEY (watcher_id, target_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id   TEXT PRIMARY KEY,
                title        TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                message_text   TEXT NOT NULL,
                photo_file_id  TEXT,
                interval_days  INTEGER NOT NULL,
                start_datetime TEXT NOT NULL,
                end_date       TEXT NOT NULL,
                last_sent      TEXT,
                active         INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wishlist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                item        TEXT NOT NULL,
                added_at    TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS holiday_tracking (
                user_id      INTEGER,
                holiday_key  TEXT,
                PRIMARY KEY (user_id, holiday_key)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                title       TEXT NOT NULL,
                date_str    TEXT NOT NULL,
                repeat      INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS congrats_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id     INTEGER NOT NULL,
                target_id     INTEGER NOT NULL,
                congrats_year INTEGER NOT NULL,
                sent_at       TEXT NOT NULL,
                UNIQUE(sender_id, target_id, congrats_year)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS congrats_stats (
                user_id         INTEGER PRIMARY KEY,
                total_sent      INTEGER DEFAULT 0,
                current_streak  INTEGER DEFAULT 0,
                best_streak     INTEGER DEFAULT 0,
                last_congrats_at TEXT DEFAULT ''
            )
        """)

        # Migrations for older DBs
        for col_def in [
            "ALTER TABLE broadcasts ADD COLUMN start_datetime TEXT NOT NULL DEFAULT '1970-01-01 00:00'",
            "ALTER TABLE broadcasts ADD COLUMN photo_file_id TEXT",
            "ALTER TABLE users ADD COLUMN invited_by INTEGER",
            "ALTER TABLE users ADD COLUMN stats_public INTEGER DEFAULT 0",
        ]:
            try:
                await db.execute(col_def)
            except Exception:
                pass

        await db.commit()


# ─── Users ────────────────────────────────────────────────────────────────────

async def upsert_user(telegram_id: int, username: str | None, first_name: str,
                      birthdate: str, invited_by: int | None = None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, first_name, birthdate, invited_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                birthdate  = excluded.birthdate
        """, (telegram_id, username, first_name, birthdate, invited_by))
        await db.commit()


async def get_user_by_id(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@").lower()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE LOWER(username) = ?", (username,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_invited_count(user_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE invited_by = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def toggle_stats_public(user_id: int) -> bool:
    """Flip stats_public flag. Returns the new value."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT stats_public FROM users WHERE telegram_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            current = row[0] if row else 0
        new_val = 0 if current else 1
        await db.execute(
            "UPDATE users SET stats_public = ? WHERE telegram_id = ?", (new_val, user_id)
        )
        await db.commit()
    return bool(new_val)


# ─── Tracking ─────────────────────────────────────────────────────────────────

async def add_tracking(watcher_id: int, target_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO tracking (watcher_id, target_id) VALUES (?, ?)",
            (watcher_id, target_id))
        await db.commit()


async def remove_tracking(watcher_id: int, target_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM tracking WHERE watcher_id = ? AND target_id = ?",
            (watcher_id, target_id))
        await db.commit()


async def is_tracking(watcher_id: int, target_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM tracking WHERE watcher_id = ? AND target_id = ?",
            (watcher_id, target_id)
        ) as cur:
            return await cur.fetchone() is not None


async def get_watchers_of(target_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT watcher_id FROM tracking WHERE target_id = ?", (target_id,)
        ) as cur:
            return [r[0] for r in await cur.fetchall()]


async def get_tracking_count(watcher_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM tracking WHERE watcher_id = ?", (watcher_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_watchers_count(target_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM tracking WHERE target_id = ?", (target_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


# ─── Channels ─────────────────────────────────────────────────────────────────

async def add_channel(channel_id: str, title: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO channels (channel_id, title) VALUES (?, ?)",
            (channel_id, title))
        await db.commit()


async def remove_channel(channel_id: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        await db.commit()


async def get_all_channels() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM channels") as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─── Broadcasts ───────────────────────────────────────────────────────────────

async def add_broadcast(message_text: str, interval_days: int, start_datetime: str,
                        end_date: str, photo_file_id: str | None = None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO broadcasts (message_text, interval_days, start_datetime, end_date, photo_file_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (message_text, interval_days, start_datetime, end_date, photo_file_id))
        await db.commit()


async def get_active_broadcasts() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM broadcasts WHERE active = 1") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def update_broadcast_last_sent(broadcast_id: int, last_sent: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE broadcasts SET last_sent = ? WHERE id = ?", (last_sent, broadcast_id))
        await db.commit()


async def deactivate_broadcast(broadcast_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("UPDATE broadcasts SET active = 0 WHERE id = ?", (broadcast_id,))
        await db.commit()


async def get_all_broadcasts() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM broadcasts ORDER BY id DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─── Wishlist ─────────────────────────────────────────────────────────────────

async def wishlist_add(user_id: int, item: str):
    from datetime import datetime
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO wishlist (user_id, item, added_at) VALUES (?, ?, ?)",
            (user_id, item, datetime.now().strftime("%d.%m.%Y %H:%M")))
        await db.commit()


async def wishlist_get(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM wishlist WHERE user_id = ? ORDER BY id", (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def wishlist_delete(item_id: int, user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM wishlist WHERE id = ? AND user_id = ?", (item_id, user_id))
        await db.commit()


async def wishlist_clear(user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM wishlist WHERE user_id = ?", (user_id,))
        await db.commit()


# ─── Holiday tracking ─────────────────────────────────────────────────────────

async def holiday_subscribe(user_id: int, holiday_key: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO holiday_tracking (user_id, holiday_key) VALUES (?, ?)",
            (user_id, holiday_key))
        await db.commit()


async def holiday_unsubscribe(user_id: int, holiday_key: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM holiday_tracking WHERE user_id = ? AND holiday_key = ?",
            (user_id, holiday_key))
        await db.commit()


async def holiday_is_subscribed(user_id: int, holiday_key: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM holiday_tracking WHERE user_id = ? AND holiday_key = ?",
            (user_id, holiday_key)
        ) as cur:
            return await cur.fetchone() is not None


async def get_user_holiday_subscriptions(user_id: int) -> list[str]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT holiday_key FROM holiday_tracking WHERE user_id = ?", (user_id,)
        ) as cur:
            return [r[0] for r in await cur.fetchall()]


async def get_all_holiday_subscriptions() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM holiday_tracking") as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─── Custom events ────────────────────────────────────────────────────────────

async def custom_event_add(user_id: int, title: str, date_str: str, repeat: bool):
    from datetime import datetime
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO custom_events (user_id, title, date_str, repeat, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, title, date_str, 1 if repeat else 0, datetime.now().strftime("%d.%m.%Y %H:%M")))
        await db.commit()


async def custom_event_get_all(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM custom_events WHERE user_id = ? ORDER BY id", (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def custom_event_delete(event_id: int, user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM custom_events WHERE id = ? AND user_id = ?", (event_id, user_id))
        await db.commit()


async def get_all_custom_events() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM custom_events") as cur:
            return [dict(r) for r in await cur.fetchall()]


# ─── Congrats ─────────────────────────────────────────────────────────────────

async def has_congratulated_this_year(sender_id: int, target_id: int, year: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM congrats_log WHERE sender_id=? AND target_id=? AND congrats_year=?",
            (sender_id, target_id, year)
        ) as cur:
            return await cur.fetchone() is not None


async def record_congrats(sender_id: int, target_id: int, year: int) -> dict:
    from datetime import datetime
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row

        await db.execute(
            "INSERT OR IGNORE INTO congrats_log (sender_id, target_id, congrats_year, sent_at)"
            " VALUES (?, ?, ?, ?)",
            (sender_id, target_id, year, now_str))

        async with db.execute("SELECT changes()") as cur:
            row = await cur.fetchone()
            inserted = row[0] if row else 0

        async with db.execute(
            "SELECT * FROM congrats_stats WHERE user_id = ?", (sender_id,)
        ) as cur:
            row = await cur.fetchone()

        if row:
            stats = dict(row)
            total = stats["total_sent"]
            streak = stats["current_streak"]
            best = stats["best_streak"]
        else:
            total, streak, best = 0, 0, 0

        if inserted:
            total += 1
            streak += 1
            if streak > best:
                best = streak

            if row:
                await db.execute(
                    "UPDATE congrats_stats SET total_sent=?, current_streak=?, best_streak=?,"
                    " last_congrats_at=? WHERE user_id=?",
                    (total, streak, best, now_str, sender_id))
            else:
                await db.execute(
                    "INSERT INTO congrats_stats (user_id, total_sent, current_streak, best_streak, last_congrats_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (sender_id, total, streak, best, now_str))

        await db.commit()

    return {"total_sent": total, "current_streak": streak, "best_streak": best, "is_new": bool(inserted)}


async def reset_streak(user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE congrats_stats SET current_streak = 0 WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_congrats_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM congrats_stats WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {
                "total_sent": 0, "current_streak": 0,
                "best_streak": 0, "last_congrats_at": ""
            }


# ─── Admin stats ──────────────────────────────────────────────────────────────

async def get_users_count() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0