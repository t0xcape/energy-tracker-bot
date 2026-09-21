import os
import sqlite3
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN в файле .env")


# Тульское / московское время
TIMEZONE = ZoneInfo("Europe/Moscow")

DATABASE = "energy.db"

# Напоминания:
# 09:00, 10:00, ..., 23:00 и 00:00
REMINDER_HOURS = list(range(9, 24)) + [0]


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

def get_connection():
    return sqlite3.connect(DATABASE)


def init_database():
    with get_connection() as conn:
        cursor = conn.cursor()

        # Пользователи бота
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                registered_at TEXT NOT NULL
            )
        """)

        # Оценки энергии
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS energy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                tracking_date TEXT NOT NULL,
                hour INTEGER NOT NULL,

                energy INTEGER NOT NULL,

                created_at TEXT NOT NULL,

                UNIQUE(user_id, tracking_date, hour)
            )
        """)

        conn.commit()


def add_user(user_id, username, first_name):
    now = datetime.now(TIMEZONE).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO users (
                user_id,
                username,
                first_name,
                registered_at
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(user_id)
            DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (
            user_id,
            username,
            first_name,
            now
        ))

        conn.commit()


def get_all_users():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id
            FROM users
        """)

        return [row[0] for row in cursor.fetchall()]


def save_energy(
    user_id,
    tracking_date,
    hour,
    energy
):
    now = datetime.now(TIMEZONE).isoformat()

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO energy (
                user_id,
                tracking_date,
                hour,
                energy,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(user_id, tracking_date, hour)
            DO UPDATE SET
                energy = excluded.energy,
                created_at = excluded.created_at
        """, (
            user_id,
            tracking_date,
            hour,
            energy,
            now
        ))

        conn.commit()


# ============================================================
# ДАТЫ
# ============================================================

def get_tracking_date(dt: datetime):
    """
    Наш день идёт с 09:00 до 00:00.

    Поэтому оценка ровно в 00:00 относится
    к предыдущему дню.

    Например:
    22 сентября 00:00
    считается последним замером за 21 сентября.
    """

    if dt.hour == 0:
        return (dt.date() - timedelta(days=1)).isoformat()

    return dt.date().isoformat()


# ============================================================
# ВНЕШНИЙ ВИД
# ============================================================

def get_energy_emoji(value):
    if value <= 2:
        return "🪫"

    if value <= 4:
        return "😴"

    if value <= 6:
        return "🙂"

    if value <= 8:
        return "⚡"

    return "🔥"


def create_energy_keyboard(
    tracking_date,
    hour
):
    row1 = []
    row2 = []

    for value in range(1, 6):
        row1.append(
            InlineKeyboardButton(
                str(value),
                callback_data=(
                    f"energy:"
                    f"{tracking_date}:"
                    f"{hour}:"
                    f"{value}"
                )
            )
        )

    for value in range(6, 11):
        row2.append(
            InlineKeyboardButton(
                str(value),
                callback_data=(
                    f"energy:"
                    f"{tracking_date}:"
                    f"{hour}:"
                    f"{value}"
                )
            )
        )

    return InlineKeyboardMarkup(
        [
            row1,
            row2
        ]
    )


# ============================================================
# /start
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    add_user(
        user.id,
        user.username,
        user.first_name
    )

    await update.message.reply_text(
        "⚡ Energy Tracker запущен!\n\n"
        "Я буду помогать тебе отслеживать "
        "уровень энергии в течение дня.\n\n"
        "Каждый час с 09:00 до 00:00 "
        "я пришлю кнопки от 1 до 10.\n\n"
        "1 — энергии почти нет\n"
        "10 — максимум энергии\n\n"
        "Команды:\n"
        "/check — оценить энергию сейчас\n"
        "/today — оценки за сегодня\n"
        "/week — статистика за 7 дней\n"
        "/stats — средняя энергия по часам\n"
        "/test — тест уведомления"
    )


# ============================================================
# СОЗДАНИЕ ЗАПРОСА ЭНЕРГИИ
# ============================================================

async def send_prompt_to_chat(
    context,
    chat_id,
    dt=None
):
    if dt is None:
        dt = datetime.now(TIMEZONE)

    tracking_date = get_tracking_date(dt)

    hour = dt.hour

    keyboard = create_energy_keyboard(
        tracking_date,
        hour
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "⚡ Как твоя энергия сейчас?\n\n"
            f"🕐 {hour:02d}:00\n\n"
            "Выбери оценку от 1 до 10:"
        ),
        reply_markup=keyboard
    )


# ============================================================
# /check
# ============================================================

async def check(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    now = datetime.now(TIMEZONE)

    user = update.effective_user

    # На всякий случай регистрируем пользователя
    add_user(
        user.id,
        user.username,
        user.first_name
    )

    await send_prompt_to_chat(
        context,
        update.effective_chat.id,
        now
    )


# ============================================================
# /test
# ============================================================

async def test_reminder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await send_prompt_to_chat(
        context,
        update.effective_chat.id
    )


# ============================================================
# НАЖАТИЕ КНОПКИ 1–10
# ============================================================

async def energy_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    # Telegram ждёт подтверждения обработки кнопки
    await query.answer()

    try:
        parts = query.data.split(":")

        # Формат:
        # energy:2026-09-21:15:8

        tracking_date = parts[1]
        hour = int(parts[2])
        energy = int(parts[3])

    except (IndexError, ValueError):
        await query.edit_message_text(
            "Ошибка обработки оценки."
        )
        return

    if energy < 1 or energy > 10:
        await query.edit_message_text(
            "Некорректная оценка."
        )
        return

    user_id = query.from_user.id

    save_energy(
        user_id,
        tracking_date,
        hour,
        energy
    )

    emoji = get_energy_emoji(energy)

    await query.edit_message_text(
        f"{emoji} Оценка записана!\n\n"
        f"🕐 {hour:02d}:00\n"
        f"⚡ Энергия: {energy}/10"
    )


# ============================================================
# АВТОМАТИЧЕСКИЕ НАПОМИНАНИЯ
# ============================================================

async def scheduled_reminder(
    context: ContextTypes.DEFAULT_TYPE
):
    now = datetime.now(TIMEZONE)

    users = get_all_users()

    for user_id in users:

        try:
            await send_prompt_to_chat(
                context,
                user_id,
                now
            )

        except Exception as error:
            print(
                f"Ошибка отправки пользователю "
                f"{user_id}: {error}"
            )


# ============================================================
# /today
# ============================================================

async def today(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    now = datetime.now(TIMEZONE)

    tracking_date = get_tracking_date(now)

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                hour,
                energy
            FROM energy
            WHERE
                user_id = ?
                AND tracking_date = ?
            ORDER BY
                CASE
                    WHEN hour = 0 THEN 24
                    ELSE hour
                END
        """, (
            user_id,
            tracking_date
        ))

        rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text(
            "📭 За сегодня пока нет оценок.\n\n"
            "Используй /check, чтобы поставить первую."
        )
        return

    total = sum(
        energy
        for _, energy in rows
    )

    average = total / len(rows)

    best = max(rows, key=lambda x: x[1])
    worst = min(rows, key=lambda x: x[1])

    text = (
        "📅 Энергия за сегодня\n\n"
    )

    for hour, energy in rows:
        emoji = get_energy_emoji(energy)

        text += (
            f"{emoji} "
            f"{hour:02d}:00 — "
            f"{energy}/10\n"
        )

    text += (
        "\n"
        f"📊 Средняя: {average:.1f}/10\n"
        f"🔥 Максимум: "
        f"{best[1]}/10 в {best[0]:02d}:00\n"
        f"🪫 Минимум: "
        f"{worst[1]}/10 в {worst[0]:02d}:00\n"
        f"📝 Замеров: {len(rows)}"
    )

    await update.message.reply_text(text)


# ============================================================
# /week
# ============================================================

async def week(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    now = datetime.now(TIMEZONE)

    end_date = datetime.fromisoformat(
        get_tracking_date(now)
    ).date()

    start_date = end_date - timedelta(days=6)

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                tracking_date,
                AVG(energy),
                MIN(energy),
                MAX(energy),
                COUNT(*)
            FROM energy

            WHERE
                user_id = ?
                AND tracking_date >= ?
                AND tracking_date <= ?

            GROUP BY tracking_date

            ORDER BY tracking_date
        """, (
            user_id,
            start_date.isoformat(),
            end_date.isoformat()
        ))

        days = cursor.fetchall()

    if not days:
        await update.message.reply_text(
            "📭 За последние 7 дней данных пока нет."
        )
        return

    all_values = []

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT energy
            FROM energy

            WHERE
                user_id = ?
                AND tracking_date >= ?
                AND tracking_date <= ?
        """, (
            user_id,
            start_date.isoformat(),
            end_date.isoformat()
        ))

        all_values = [
            row[0]
            for row in cursor.fetchall()
        ]

    average_week = (
        sum(all_values) /
        len(all_values)
    )

    text = (
        "📊 Последние 7 дней\n\n"
    )

    for (
        date_string,
        average,
        minimum,
        maximum,
        count
    ) in days:

        date_object = datetime.fromisoformat(
            date_string
        )

        text += (
            f"📅 {date_object.strftime('%d.%m')}\n"
            f"Средняя: {average:.1f}/10\n"
            f"Диапазон: {minimum}–{maximum}\n"
            f"Замеров: {count}\n\n"
        )

    text += (
        f"⚡ Общая средняя: "
        f"{average_week:.2f}/10\n"
        f"📝 Всего замеров: "
        f"{len(all_values)}"
    )

    await update.message.reply_text(text)


# ============================================================
# /stats
# ============================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    now = datetime.now(TIMEZONE)

    end_date = datetime.fromisoformat(
        get_tracking_date(now)
    ).date()

    start_date = end_date - timedelta(days=6)

    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                hour,
                AVG(energy) AS average_energy,
                COUNT(*) AS count_measurements

            FROM energy

            WHERE
                user_id = ?
                AND tracking_date >= ?
                AND tracking_date <= ?

            GROUP BY hour

            ORDER BY
                CASE
                    WHEN hour = 0 THEN 24
                    ELSE hour
                END
        """, (
            user_id,
            start_date.isoformat(),
            end_date.isoformat()
        ))

        rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text(
            "📭 Пока недостаточно данных.\n\n"
            "Начни отмечать энергию через /check."
        )
        return

    best = max(
        rows,
        key=lambda x: x[1]
    )

    worst = min(
        rows,
        key=lambda x: x[1]
    )

    text = (
        "🧠 Средняя энергия по часам\n"
        "за последние 7 дней\n\n"
    )

    for hour, average, count in rows:
        text += (
            f"🕐 {hour:02d}:00 — "
            f"{average:.2f}/10 "
            f"({count} зам.)\n"
        )

    text += (
        "\n🔥 Больше всего энергии:\n"
        f"{best[0]:02d}:00 — "
        f"{best[1]:.2f}/10\n\n"

        "🪫 Меньше всего энергии:\n"
        f"{worst[0]:02d}:00 — "
        f"{worst[1]:.2f}/10"
    )

    await update.message.reply_text(text)


# ============================================================
# ПЛАНИРОВЩИК
# ============================================================

def setup_jobs(application):
    job_queue = application.job_queue

    for hour in REMINDER_HOURS:

        reminder_time = time(
            hour=hour,
            minute=0,
            second=0,
            tzinfo=TIMEZONE
        )

        job_queue.run_daily(
            scheduled_reminder,
            time=reminder_time,
            name=f"energy_reminder_{hour}"
        )

        print(
            f"Добавлено напоминание: "
            f"{hour:02d}:00"
        )


# ============================================================
# ЗАПУСК
# ============================================================

def main():
    print("Инициализация базы данных...")

    init_database()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "check",
            check
        )
    )

    application.add_handler(
        CommandHandler(
            "today",
            today
        )
    )

    application.add_handler(
        CommandHandler(
            "week",
            week
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CommandHandler(
            "test",
            test_reminder
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            energy_button,
            pattern=r"^energy:"
        )
    )

    setup_jobs(application)

    print()
    print("===================================")
    print("⚡ Energy Tracker запущен")
    print("===================================")
    print()

    application.run_polling()


if __name__ == "__main__":
    main()