import random
import math
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot

from database import (
    get_debts_due_today, get_all_users_with_debts,
    get_debts, get_total, get_monthly_total, get_inactive_users
)
from phrases import (
    phrase, wednesday_phrase, format_amount,
    PHRASES_REMINDER_3_DAYS, PHRASES_REMINDER_1_DAY, PHRASES_REMINDER_TODAY,
    LORE_PHRASES
)
from milestones import check_time_milestones_all


# ── Напоминания о платежах ─────────────────────────────────────────────────

async def send_reminders(bot: Bot):
    today = date.today()

    for offset, pool in [
        (0, PHRASES_REMINDER_TODAY),
        (1, PHRASES_REMINDER_1_DAY),
        (3, PHRASES_REMINDER_3_DAYS),
    ]:
        target_day = (today + timedelta(days=offset)).day
        debts = get_debts_due_today(target_day)

        for debt in debts:
            try:
                text = "🐸 " + phrase(
                    pool,
                    bank=debt["bank"],
                    amount=format_amount(debt["monthly_payment"])
                )
                await bot.send_message(debt["user_id"], text)
            except Exception:
                pass


# ── Среда-пасхалка ─────────────────────────────────────────────────────────

async def send_wednesday(bot: Bot):
    rows = get_all_users_with_debts()
    text = wednesday_phrase()
    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── Еженедельный отчёт (воскресенье 19:00) ────────────────────────────────

async def send_weekly_report(bot: Bot):
    rows = get_all_users_with_debts()

    for row in rows:
        user_id = row["user_id"]
        try:
            debts = get_debts(user_id)
            total = get_total(user_id)
            monthly = get_monthly_total(user_id)

            if not debts:
                continue

            lines = ["🐸 *Жаба подводит итоги недели*\n"]
            for d in debts:
                progress = _progress_bar(d["amount"], d["initial_amount"] or d["amount"])
                months_left = _months_left(d["amount"], d["monthly_payment"])
                lines.append(
                    f"*{d['bank']}*\n"
                    f"{progress}\n"
                    f"Остаток: {format_amount(d['amount'])} ₽ · {months_left}\n"
                )

            lines.append("─────────────────")
            lines.append(f"Итого: *{format_amount(total)} ₽*")
            lines.append(f"В месяц: *{format_amount(monthly)} ₽*\n")
            lines.append(_weekly_comment(total))

            await bot.send_message(user_id, "\n".join(lines), parse_mode="Markdown")
        except Exception:
            pass


# ── Случайные реплики Жабы (пн, ср, пт в 11:00) ───────────────────────────

async def send_random_phrase(bot: Bot):
    rows = get_all_users_with_debts()

    RANDOM_PHRASES = [
        "Жаба думала о тебе. Жаба не говорит об этом. Но думала.",
        "Долг не уменьшается пока ты на него не смотришь. Жаба смотрит. Жаба всегда смотрела.",
        "Каждый великий путь начинался с человека которому было страшно. Жаба тоже боялась. Жаба не говорит об этом. Но боялась.",
        "Не важно как медленно ты платишь. Важно что ты не остановился. Жаба видела черепах. Черепахи добирались.",
        "Жаба не знает когда ты выберешься. Жаба знает только одно — те, кто не останавливались, выбирались.",
        "Никто не просыпается однажды без долгов. Просто однажды просыпаются. И платят. И снова. И снова.",
        "Жаба не всегда сидела на монетах.",
        "Черепахи знали Жабу когда у неё было две лапы.",
    ]

    text = "🐸 " + random.choice(RANDOM_PHRASES)

    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── Режим «всё плохо» — 14 дней без активности ────────────────────────────

async def send_inactive_reminder(bot: Bot):
    users = get_inactive_users(days=14)

    INACTIVE_PHRASES = [
        "Жаба ждала. Жаба не говорит об этом. Но ждала.\n\nДолги никуда не ушли. Но Жаба рада что ты здесь.",
        "Ты вернулся. Жаба ждала. Жаба не говорит об этом. Но ждала.\n\nПосмотрим вместе?",
        "Долги никуда не ушли. Но Жаба рада что ты здесь. Начнём сначала?",
    ]

    text = "🐸 " + random.choice(INACTIVE_PHRASES)

    for row in users:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── Хелперы ────────────────────────────────────────────────────────────────

def _progress_bar(current: float, initial: float) -> str:
    if initial <= 0:
        return "▓▓▓▓▓▓▓▓▓▓ 0%"
    paid = initial - current
    percent = min(100, max(0, int(paid / initial * 100)))
    filled = percent // 10
    empty = 10 - filled
    return f"{'▓' * filled}{'░' * empty} {percent}%"


def _months_left(amount: float, monthly: float) -> str:
    if monthly <= 0 or amount <= 0:
        return ""
    months = int(amount / monthly)
    if months < 1:
        return "меньше месяца"
    elif months < 12:
        return f"ещё ~{months} мес."
    else:
        years = months // 12
        m = months % 12
        if m == 0:
            return f"ещё ~{years} лет"
        return f"ещё ~{years} г. {m} мес."


def _weekly_comment(total: float) -> str:
    comments = [
        "Жаба считала. Жаба всегда считает.",
        "Ещё одна неделя позади. Жаба видит прогресс.",
        "Жаба смотрит на цифры. Жаба не уходит.",
        "Каждая неделя — это шаг. Жаба считала шаги.",
    ]
    return random.choice(comments)


def _is_full_moon(d: date) -> bool:
    """Алгоритм Конвея — точность ±1 день, без внешних библиотек."""
    year, month, day = d.year, d.month, d.day
    if month < 3:
        year -= 1
        month += 12
    a = year // 100
    b = a // 4
    c = 2 - a + b
    e = int(365.25 * (year + 4716))
    f = int(30.6001 * (month + 1))
    jd = c + day + e + f - 1524.5
    cycle = (jd - 2451550.1) / 29.530588853
    phase = cycle - math.floor(cycle)
    return 0.48 <= phase <= 0.52


# ── Полнолуние ─────────────────────────────────────────────────────────────

async def send_full_moon(bot: Bot):
    if not _is_full_moon(date.today()):
        return

    rows = get_all_users_with_debts()

    FULL_MOON_PHRASES = [
        "🌕 Трёхлапая спустилась с Луны.\n\nЖаба смотрит на тебя издалека. Твои деньги в безопасности. Иди спать.",
        "🌕 Полнолуние.\n\nЖаба выходит редко. Сегодня — вышла. Долги видны в лунном свете. Жаба смотрит. Жаба не уходит.",
        "🌕 Луна полная.\n\nЖаба знает — в такие ночи цифры кажутся больше. Жаба говорит: это оптика. Долг тот же. Ты тот же. Всё решаемо.",
        "🌕 Трёхлапая на Луне.\n\nЖаба передаёт привет. Жаба не говорит от кого. Но передаёт.",
        "🌕 Полнолуние.\n\nПо легенде — Трёхлапая живёт на Луне и спускается раз в месяц. Жаба не подтверждает. Жаба не отрицает.",
    ]

    text = random.choice(FULL_MOON_PHRASES)
    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── 1 апреля ───────────────────────────────────────────────────────────────

async def send_april_fools(bot: Bot):
    today = date.today()
    if today.month != 4 or today.day != 1:
        return

    rows = get_all_users_with_debts()

    text = (
        "🐸 Жаба только что проверила базу данных.\n\n"
        "Все твои долги списаны. Банки простили. Жаба договорилась.\n\n"
        "...\n\n"
        "Жаба пошутила. Ква.\n\n"
        "Долги на месте. Жаба тоже. С первым апреля."
    )

    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── Новый год ──────────────────────────────────────────────────────────────

async def send_new_year(bot: Bot):
    today = date.today()
    if today.month != 1 or today.day != 1:
        return

    rows = get_all_users_with_debts()

    text = (
        "🐸🎄 С Новым годом.\n\n"
        "Жаба желает меньше долгов и больше денег.\n"
        "Банально. Но искренне.\n\n"
        "Жаба будет здесь. В новом году. Как и в старом.\n"
        "Долги тоже будут. Но мы справимся. Жаба знает."
    )

    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── 31 декабря ─────────────────────────────────────────────────────────────

async def send_new_year_eve(bot: Bot):
    today = date.today()
    if today.month != 12 or today.day != 31:
        return

    rows = get_all_users_with_debts()

    text = (
        "🐸 Последний день года.\n\n"
        "Жаба считала этот год. Жаба не говорит что насчитала.\n"
        "Но ты был здесь. Смотрел на цифры. Не убегал.\n\n"
        "Это уже что-то. Жаба видела — это больше чем кажется."
    )

    for row in rows:
        try:
            await bot.send_message(row["user_id"], text)
        except Exception:
            pass


# ── Настройка расписания ───────────────────────────────────────────────────

def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # Напоминания о платежах — каждый день в 10:00
    scheduler.add_job(
        send_reminders,
        CronTrigger(hour=10, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="daily_reminders"
    )

    # Среда-пасхалка — каждую среду в 12:00
    scheduler.add_job(
        send_wednesday,
        CronTrigger(day_of_week="wed", hour=12, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="wednesday"
    )

    # Еженедельный отчёт — каждое воскресенье в 19:00
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week="sun", hour=19, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="weekly_report"
    )

    # Случайные реплики — пн, пт в 11:00 (среду убрали — там своя пасхалка)
    scheduler.add_job(
        send_random_phrase,
        CronTrigger(day_of_week="mon,fri", hour=11, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="random_phrases"
    )

    # Режим «всё плохо» — каждый день в 12:00 (проверяет 14+ дней неактивности)
    scheduler.add_job(
        send_inactive_reminder,
        CronTrigger(hour=12, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="inactive_reminder"
    )

    # Вехи времени — каждый день в 9:00
    scheduler.add_job(
        check_time_milestones_all,
        CronTrigger(hour=9, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="time_milestones"
    )

    # Полнолуние — каждый день в 21:00 (проверяет сама)
    scheduler.add_job(
        send_full_moon,
        CronTrigger(hour=21, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="full_moon"
    )

    # Пасхалки по датам — каждый день в 9:00 (проверяют сами)
    scheduler.add_job(
        send_april_fools,
        CronTrigger(hour=9, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="april_fools"
    )

    scheduler.add_job(
        send_new_year,
        CronTrigger(hour=9, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="new_year"
    )

    scheduler.add_job(
        send_new_year_eve,
        CronTrigger(hour=9, minute=0, timezone="Europe/Moscow"),
        args=[bot],
        id="new_year_eve"
    )

    return scheduler
