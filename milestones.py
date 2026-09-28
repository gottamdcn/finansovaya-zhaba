import asyncio
from datetime import date
from aiogram import Bot

from database import (
    get_total, get_credit_cards_total_balance,
    get_debts, get_initial_total, get_user_created_at,
    save_milestone
)


# ── Фразы для вех (хайку) ─────────────────────────────────────────────────

MILESTONE_PHRASES = {

    # Прогресс
    "first_payment": (
        "Жаба видела первый шаг.\n"
        "Жаба не говорит об этом.\n"
        "Но видела."
    ),
    "progress_10": (
        "Десятая часть позади.\n"
        "Жаба считала. Жаба не ошибается.\n"
        "Продолжай."
    ),
    "progress_25": (
        "Жаба считала.\n"
        "Четверть пути позади.\n"
        "Черепахи добирались."
    ),
    "progress_50": (
        "Половина.\n"
        "Жаба молчит секунду.\n"
        "Это уважение."
    ),
    "progress_75": (
        "Жаба почти не говорит.\n"
        "Потому что почти нечего говорить.\n"
        "Почти."
    ),
    "first_debt_closed": (
        "Один закрыт.\n"
        "Где-то вдали — золотая тень.\n"
        "Жаба видит. Молчит."
    ),
    "all_debts_closed": (
        "Жаба молчит впервые.\n"
        "Это хорошее молчание.\n"
        "Это тишина."
    ),

    # Время с Жабой
    "month_1": (
        "Месяц.\n"
        "Жаба помнит первый день.\n"
        "Жаба всегда помнит."
    ),
    "month_6": (
        "Полгода.\n"
        "Жаба не ожидала.\n"
        "Жаба не говорит об этом. Но не ожидала."
    ),
    "year_1": (
        "Год.\n"
        "Жаба видела как ты менялся.\n"
        "Черепахи бы одобрили."
    ),
}

# Вехи прогресса в порядке важности — только одна новая за раз
PROGRESS_MILESTONES = [
    (75, "progress_75"),
    (50, "progress_50"),
    (25, "progress_25"),
    (10, "progress_10"),
]


# ── Проверка вех ───────────────────────────────────────────────────────────

async def check_milestones(bot: Bot, user_id: int):
    await _check_progress_milestones(bot, user_id)
    await _check_time_milestones(bot, user_id)


async def _check_progress_milestones(bot: Bot, user_id: int):
    initial = get_initial_total(user_id)
    current_debts = get_total(user_id)
    current_cards = get_credit_cards_total_balance(user_id)
    current = current_debts + current_cards

    # Если initial_total не установлен или долг не уменьшился — ещё рано
    if initial <= 0 or current >= initial:
        return

    # Все долги закрыты — только эта веха, больше ничего
    if current == 0:
        await _send_milestone(bot, user_id, "all_debts_closed")
        return

    # Первый платёж
    sent = await _send_milestone(bot, user_id, "first_payment")
    if sent:
        await asyncio.sleep(3)

    # Из прогресс-вех — только самая высокая достигнутая и ещё не отправленная
    progress_pct = (initial - current) / initial * 100
    for pct, key in PROGRESS_MILESTONES:
        if progress_pct >= pct:
            sent = await _send_milestone(bot, user_id, key)
            if sent:
                # Одна веха за раз — остальные придут со следующими платежами
                break


async def _check_time_milestones(bot: Bot, user_id: int):
    created_at_str = get_user_created_at(user_id)
    if not created_at_str:
        return

    try:
        created_at = date.fromisoformat(created_at_str)
    except Exception:
        return

    today = date.today()
    days_with_zhaba = (today - created_at).days

    for days, key in [
        (365, "year_1"),
        (180, "month_6"),
        (30,  "month_1"),
    ]:
        if days_with_zhaba >= days:
            await _send_milestone(bot, user_id, key)


async def _send_milestone(bot: Bot, user_id: int, key: str) -> bool:
    """Отправляет веху если она ещё не была отправлена.
    Возвращает True если веха была новой и отправлена."""
    is_new = save_milestone(user_id, key)
    if not is_new:
        return False

    text = MILESTONE_PHRASES.get(key)
    if not text:
        return False

    try:
        await bot.send_message(user_id, f"🐸\n\n{text}")
        return True
    except Exception:
        return False


# ── Проверка вех времени в шедулере (ежедневно) ───────────────────────────

async def check_time_milestones_all(bot: Bot):
    """Вызывается из scheduler раз в день — проверяет вехи времени для всех."""
    from database import get_all_users_with_debts
    rows = get_all_users_with_debts()
    for row in rows:
        try:
            await _check_time_milestones(bot, row["user_id"])
        except Exception:
            pass
