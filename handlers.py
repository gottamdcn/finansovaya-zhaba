from datetime import date, timedelta
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from database import (
    init_db, upsert_user, add_debt, get_debts,
    get_debt, delete_debt, get_total, get_monthly_total,
    add_credit_card, get_credit_cards, get_credit_card, delete_credit_card,
    update_card_balance, get_credit_cards_total_balance, get_credit_cards_min_payment_total,
    maybe_set_initial_total, update_debt
)
from milestones import check_milestones, _send_milestone  # noqa: F401
from phrases import (
    phrase, debt_phrase, format_amount, maybe_lore, card_danger_phrase,
    product_added_phrase, product_emoji, product_label,
    PHRASES_START, PHRASES_DEBT_ADDED, PHRASES_DEBT_DELETED,
    PHRASES_NO_DEBTS, PHRASES_HELP, PHRASES_HELP_MOTIVATION,
    PHRASES_CARD_ADDED, PHRASES_CARD_SPEND, PHRASES_CARD_SPEND_BIG,
    PHRASES_CARD_PAYMENT, PHRASES_CARD_PAID_FULL
)

router = Router()
init_db()


# ── FSM States ─────────────────────────────────────────────────────────────

class AddDebt(StatesGroup):
    product_type = State()            # consumer / mortgage / friend / card
    bank = State()
    initial_amount = State()
    amount = State()
    rate = State()
    payment_day = State()
    monthly_payment = State()
    loan_term = State()               # только для ипотеки
    mortgage_payment_choice = State() # выбор: платёж Жабы или свой


class EditDebt(StatesGroup):
    debt_id = State()
    field = State()
    value = State()


class PayDebt(StatesGroup):
    debt_id = State()
    amount = State()


class AddCard(StatesGroup):
    bank = State()
    credit_limit = State()
    balance = State()
    min_payment = State()
    payment_day = State()
    grace = State()          # "да" / "нет"
    grace_end_date = State()  # если да — дата конца грейса


class CardSpend(StatesGroup):
    card_id = State()
    amount = State()


class CardPay(StatesGroup):
    card_id = State()
    amount = State()


def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои долги"), KeyboardButton(text="➕ Добавить кредит")],
            [KeyboardButton(text="💰 Кредитки"), KeyboardButton(text="💳 Внести платёж")],
        ],
        resize_keyboard=True
    )


def debts_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Редактировать кредит"), KeyboardButton(text="🗑 Удалить кредит")],
            [KeyboardButton(text="↩ Назад")]
        ],
        resize_keyboard=True
    )


# ── /start ─────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    upsert_user(message.from_user.id, message.from_user.username)

    text = (
        "🐸 Привет. Жаба здесь.\n\n"
        "Жаба помогает держать все долги в одном месте - и не забывать о платежах.\n\n"
        "Что умеет Жаба:\n\n"
        "/add — добавить кредит\n"
        "/card — добавить кредитку\n"
        "/debts — все долги\n"
        "/pay — внести платёж\n"
        "/delete — закрыть кредит\n"
        "/help — все команды и подсказки\n\n"
        "Жаба не осуждает. Жаба не сравнивает. Жаба просто сидит рядом с чашкой чая.\n\n"
        "Начнём? Добавь первый кредит.\n\n"
        "─────────────────\n"
        "🐸 Есть идея или что-то не работает?\n"
        "Напиши /feedback - Жаба передаст."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())


# ── /help ──────────────────────────────────────────────────────────────────

@router.message(Command("help"))
async def cmd_help(message: Message):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    motivation = phrase(PHRASES_HELP_MOTIVATION)
    text = (
        PHRASES_HELP + "\n\n"
        "─────────────────\n"
        f"_{motivation}_\n\n"
        "🐸 Есть идея или что-то не работает?\n"
        "Напиши /feedback - Жаба передаст."
    )
    donate_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="☕ Поддержать разработчика",
            url="https://yoomoney.ru/to/4100118752541780"
        )]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=donate_kb)
    await message.answer("🐸", reply_markup=main_menu())


# ── /add ───────────────────────────────────────────────────────────────────

@router.message(Command("add"))
@router.message(F.text == "➕ Добавить кредит")
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddDebt.product_type)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Потребительский кредит"), KeyboardButton(text="🏠 Ипотека")],
            [KeyboardButton(text="🤝 Долг другу"),    KeyboardButton(text="💳 Кредитная карта")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "🐸 Жаба слушает.\n\nЧто добавляем?",
        reply_markup=kb
    )


@router.message(AddDebt.product_type)
async def add_product_type(message: Message, state: FSMContext):
    text = message.text.strip()
    mapping = {
        "💰 Потребительский кредит": "consumer",
        "🏠 Ипотека": "mortgage",
        "🤝 Долг другу": "friend",
        "💳 Кредитная карта": "card",
    }
    product_type = mapping.get(text)
    if not product_type:
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="💰 Потребительский кредит"), KeyboardButton(text="🏠 Ипотека")],
                [KeyboardButton(text="🤝 Долг другу"),    KeyboardButton(text="💳 Кредитная карта")],
            ],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer("🐸 Жаба не поняла. Выбери из кнопок.", reply_markup=kb)
        return

    if product_type == "card":
        await state.clear()
        await cmd_card(message, state)
        return

    await state.update_data(product_type=product_type)
    await state.set_state(AddDebt.bank)

    prompts = {
        "consumer": "Как называется банк?\n_(например: Сбер, Тинькофф, МФО Ромашка)_",
        "mortgage": "В каком банке ипотека?\n_(например: Сбер, ВТБ, Дом.РФ)_",
        "friend":   "Как зовут человека которому должен?\n_(имя или прозвище — только Жаба увидит)_",
    }
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="↩ Начать заново")]],
        resize_keyboard=True
    )
    await message.answer(
        f"🐸 {prompts[product_type]}",
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(F.text == "↩ Начать заново")
async def restart_add(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🐸 Жаба обнулила. Начнём заново.", reply_markup=main_menu())


@router.message(AddDebt.bank)
async def add_bank(message: Message, state: FSMContext):
    data = await state.get_data()
    product_type = data.get("product_type", "consumer")
    await state.update_data(bank=message.text.strip())
    await state.set_state(AddDebt.initial_amount)

    prompts = {
        "consumer": "Сколько брал изначально?\n_(например: 300000)_",
        "mortgage": "Сумма ипотеки изначально?\n_(например: 5000000)_",
        "friend":   "Сколько взял в долг?\n_(например: 50000)_",
    }
    await message.answer(prompts.get(product_type, prompts["consumer"]), parse_mode="Markdown")


@router.message(AddDebt.initial_amount)
async def add_initial_amount(message: Message, state: FSMContext):
    try:
        initial = float(message.text.replace(" ", "").replace(",", "."))
        if initial <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *300000*", parse_mode="Markdown")
        return

    await state.update_data(initial_amount=initial)
    await state.set_state(AddDebt.amount)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="↩ Начать заново")]],
        resize_keyboard=True
    )
    await message.answer(
        "Сколько осталось выплатить сейчас?\n_(например: 150000)_",
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(AddDebt.amount)
async def add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *150000*", parse_mode="Markdown")
        return

    data = await state.get_data()
    product_type = data.get("product_type", "consumer")
    await state.update_data(amount=amount)

    if product_type == "friend":
        await state.update_data(rate=0)
        await state.set_state(AddDebt.payment_day)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="↩ Начать заново")]], resize_keyboard=True)
        await message.answer(
            "Какого числа договорились отдавать?\n_(число от 1 до 31)\n\nЕсли нет чёткого числа — напиши *1*_",
            parse_mode="Markdown", reply_markup=kb
        )
    elif product_type == "mortgage":
        await state.set_state(AddDebt.rate)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="↩ Начать заново")]], resize_keyboard=True)
        await message.answer(
            "Процентная ставка по ипотеке?\n_(например: 8.5)_",
            parse_mode="Markdown", reply_markup=kb
        )
    else:
        await state.set_state(AddDebt.rate)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="↩ Начать заново")]], resize_keyboard=True)
        await message.answer(
            "Процентная ставка в год? Введи число.\n_(например: 19.9)_\n",
            parse_mode="Markdown", reply_markup=kb
        )


@router.message(AddDebt.rate)
async def add_rate(message: Message, state: FSMContext):
    try:
        rate = float(message.text.replace(",", "."))
        if rate < 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *19.9*", parse_mode="Markdown")
        return

    data = await state.get_data()
    product_type = data.get("product_type", "consumer")
    await state.update_data(rate=rate)

    if product_type == "mortgage":
        await state.set_state(AddDebt.loan_term)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="↩ Начать заново")]], resize_keyboard=True)
        await message.answer(
            "На сколько лет ипотека?\n_(например: 20)_",
            parse_mode="Markdown", reply_markup=kb
        )
    else:
        await state.set_state(AddDebt.loan_term)
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="12 мес."), KeyboardButton(text="24 мес."), KeyboardButton(text="36 мес.")],
                [KeyboardButton(text="48 мес."), KeyboardButton(text="60 мес.")],
                [KeyboardButton(text="↩ Начать заново")],
            ],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer(
            "На сколько месяцев взял кредит?\n_(например: 36)_",
            parse_mode="Markdown", reply_markup=kb
        )


@router.message(AddDebt.loan_term)
async def add_loan_term(message: Message, state: FSMContext):
    if message.text == "↩ Начать заново":
        await state.clear()
        await message.answer("🐸 Жаба обнулила. Начнём заново.", reply_markup=main_menu())
        return

    import math
    data = await state.get_data()
    product_type = data.get("product_type", "consumer")
    amount = data.get("amount", 0)
    rate = data.get("rate", 0)

    try:
        raw = message.text.strip().replace(" мес.", "").replace(",", ".")
        val = float(raw)
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *36*", parse_mode="Markdown")
        return

    # Ипотека — вводят годы, потреб — месяцы
    if product_type == "mortgage":
        months = int(val * 12)
        label = f"{int(val)} лет"
    else:
        months = int(val)
        label = f"{months} мес."

    # Считаем аннуитетный платёж
    if rate > 0:
        r = rate / 12 / 100
        try:
            monthly = amount * r * (1 + r) ** months / ((1 + r) ** months - 1)
        except Exception:
            monthly = amount / months if months > 0 else 0
    else:
        monthly = amount / months if months > 0 else 0

    # Переплата
    total_paid = monthly * months
    overpay = round(total_paid - amount, 2)
    overpay_str = f"\nПереплата банку: *{format_amount(overpay)} ₽*" if overpay > 0 else ""

    await state.update_data(loan_term_months=months, monthly_payment_calc=round(monthly, 2))
    await state.set_state(AddDebt.mortgage_payment_choice)

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"✅ {format_amount(monthly)} ₽ — как Жаба посчитала")],
            [KeyboardButton(text="✏️ Ввести свой платёж")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        f"Жаба посчитала — при ставке {rate}% на {label}:\n"
        f"Платёж: *{format_amount(monthly)} ₽/мес*{overpay_str}\n\n"
        f"Берём этот платёж или введёшь свой?",
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(AddDebt.mortgage_payment_choice)
async def mortgage_payment_choice(message: Message, state: FSMContext):
    data = await state.get_data()
    calc = data.get("monthly_payment_calc", 0)
    text = message.text.strip()

    if text.startswith("✅"):
        # Берём посчитанный Жабой
        await state.update_data(monthly_payment=calc)
        await state.set_state(AddDebt.payment_day)
        await message.answer(
            "Какого числа каждый месяц платёж?\n_(число от 1 до 31)_",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    elif text.startswith("✏️"):
        # Пользователь хочет ввести свой
        await state.set_state(AddDebt.monthly_payment)
        await message.answer(
            "Введи свой ежемесячный платёж:\n_(например: 45000)_",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        # Попробуем распарсить как число — вдруг сразу ввёл
        try:
            monthly = float(text.replace(" ", "").replace(",", "."))
            if monthly <= 0:
                raise ValueError
            await state.update_data(monthly_payment=monthly)
            await state.set_state(AddDebt.payment_day)
            await message.answer(
                "Какого числа каждый месяц платёж?\n_(число от 1 до 31)_",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )
        except ValueError:
            kb = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text=f"✅ {format_amount(calc)} ₽ — как Жаба посчитала")],
                    [KeyboardButton(text="✏️ Ввести свой платёж")],
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await message.answer("Жаба не поняла. Выбери из кнопок.", reply_markup=kb)


@router.message(AddDebt.payment_day)
async def add_payment_day(message: Message, state: FSMContext):
    try:
        day = int(message.text.strip())
        if not (1 <= day <= 31):
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число от *1* до *31*", parse_mode="Markdown")
        return

    data = await state.get_data()
    product_type = data.get("product_type", "consumer")
    await state.update_data(payment_day=day)
    await state.set_state(AddDebt.monthly_payment)

    prompts = {
        "friend":   "Договорились на какую сумму в месяц?\n_(например: 10000)\n\nЕсли нет чёткого графика — напиши *0*_",
        "mortgage": "Сколько платишь в месяц?\n_(Жаба уже рассчитала — можно подтвердить или ввести своё)_",
        "consumer": "Сколько платишь каждый месяц?\n_(например: 8500)_",
    }
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="↩ Начать заново")]], resize_keyboard=True)
    await message.answer(
        prompts.get(product_type, prompts["consumer"]),
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(AddDebt.monthly_payment)
async def add_monthly_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    # Если платёж уже выбран через кнопку (ипотека) — берём из state
    if data.get("monthly_payment") is not None and not message.text.strip():
        monthly = data["monthly_payment"]
    else:
        try:
            monthly = float(message.text.replace(" ", "").replace(",", "."))
            if monthly < 0:
                raise ValueError
        except ValueError:
            await message.answer("Жаба не поняла. Введи число - например: *8500*", parse_mode="Markdown")
            return

    await state.clear()

    product_type = data.get("product_type", "consumer")
    add_debt(
        user_id=message.from_user.id,
        bank=data["bank"],
        amount=data["amount"],
        initial_amount=data.get("initial_amount", data["amount"]),
        rate=data["rate"],
        payment_day=data.get("payment_day", 0),
        monthly_payment=monthly,
        product_type=product_type,
        loan_term_months=data.get("loan_term_months")
    )

    total = get_total(message.from_user.id)
    cards_total = get_credit_cards_total_balance(message.from_user.id)
    maybe_set_initial_total(message.from_user.id, total + cards_total)
    monthly_total = get_monthly_total(message.from_user.id)

    lore = maybe_lore()
    lore_text = f"\n\n_{lore}_" if lore else ""

    initial = data.get("initial_amount", data["amount"])
    progress = _progress_bar(data["amount"], initial)

    emoji = product_emoji(product_type)
    label = product_label(product_type)
    added_phrase = product_added_phrase(product_type)

    payment_day = data.get("payment_day", 0)
    rate = data.get("rate", 0)
    day_str = f"Каждое {payment_day}-е · " if payment_day else ""
    rate_str = f"Ставка: {rate}% · " if rate else ""
    term = data.get("loan_term_months")
    if term:
        if product_type == "mortgage":
            term_str = f" · {term // 12} лет"
        else:
            term_str = f" · {term} мес."
    else:
        term_str = ""

    # Переплата если есть срок
    overpay_str = ""
    if term and monthly > 0:
        overpay = round(monthly * term - data["amount"], 2)
        if overpay > 0:
            overpay_str = f"\nПереплата банку: *{format_amount(overpay)} ₽*"

    text = (
        f"🐸 {added_phrase}\n\n"
        f"{emoji} *{label}: {data['bank']}*\n"
        f"Взял: {format_amount(initial)} ₽\n"
        f"Осталось: {format_amount(data['amount'])} ₽{term_str}\n"
        f"{progress}\n"
        f"{rate_str}{day_str}Платёж: {format_amount(monthly)} ₽{overpay_str}\n\n"
        f"Общий долг: *{format_amount(total)} ₽*\n"
        f"В месяц отдаёшь: *{format_amount(monthly_total)} ₽*\n\n"
        f"─────────────────\n"
        f"_{debt_phrase(total)}_"
        f"{lore_text}"
    )

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить ещё"), KeyboardButton(text="✅ Готово")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


# ── После добавления кредита ───────────────────────────────────────────────

@router.message(F.text == "➕ Добавить ещё")
async def add_more(message: Message, state: FSMContext):
    await state.set_state(AddDebt.bank)
    await message.answer(
        "🐸 Жаба слушает. Как называется следующий банк?",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(F.text == "✅ Готово")
async def add_done(message: Message):
    debts = get_debts(message.from_user.id)
    total = get_total(message.from_user.id)
    monthly = get_monthly_total(message.from_user.id)

    text = (
        f"🐸 Жаба записала всё.\n\n"
        f"Кредитов: *{len(debts)}*\n"
        f"Общий долг: *{format_amount(total)} ₽*\n"
        f"В месяц: *{format_amount(monthly)} ₽*\n\n"
        f"Жаба будет напоминать о платежах. Жаба всегда напоминает."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())


# ── /pay ───────────────────────────────────────────────────────────────────

@router.message(Command("pay"))
@router.message(F.text == "💳 Внести платёж")
async def cmd_pay(message: Message, state: FSMContext):
    debts = get_debts(message.from_user.id)
    if not debts:
        await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
        return

    buttons = []
    for d in debts:
        buttons.append([KeyboardButton(text=f"{d['bank']} - {format_amount(d['amount'])} ₽ #{d['id']}")])

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

    await state.set_state(PayDebt.debt_id)
    await message.answer("🐸 По какому кредиту вносим платёж?", reply_markup=kb)


@router.message(PayDebt.debt_id)
async def pay_select_debt(message: Message, state: FSMContext):
    try:
        debt_id = int(message.text.split("#")[1])
    except ValueError:
        await message.answer("Жаба не поняла. Выбери кредит из списка.")
        return

    debt = get_debt(debt_id, message.from_user.id)
    if not debt:
        await message.answer("Жаба не нашла такой кредит. Проверь ID и попробуй ещё раз.")
        return

    await state.update_data(debt_id=debt_id, bank=debt["bank"], current_amount=debt["amount"])
    await state.set_state(PayDebt.amount)
    await message.answer(
        f"*{debt['bank']}* - остаток {format_amount(debt['amount'])} ₽\n\n"
        f"Сколько внёс? Введи сумму платежа:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(PayDebt.amount)
async def pay_confirm(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *5000*", parse_mode="Markdown")
        return

    data = await state.get_data()
    await state.clear()

    import database
    debt = get_debt(data["debt_id"], message.from_user.id)
    new_amount = max(0, debt["amount"] - amount)

    with database.get_conn() as conn:
        if new_amount == 0:
            conn.execute(
                "UPDATE debts SET amount = 0, closed_at = date('now') WHERE id = ? AND user_id = ?",
                (data["debt_id"], message.from_user.id)
            )
        else:
            conn.execute(
                "UPDATE debts SET amount = ? WHERE id = ? AND user_id = ?",
                (new_amount, data["debt_id"], message.from_user.id)
            )

    total = get_total(message.from_user.id)

    if new_amount == 0:
        text = (
            f"🐸 *{data['bank']}* закрыт!\n\n"
            f"Жаба молчит. Впервые за долгое время. Это хорошее молчание.\n\n"
            f"Осталось долгов: *{format_amount(total)} ₽*"
        )
        if total > 0:
            text += f"\n\n─────────────────\n_{debt_phrase(total)}_"
    else:
        text = (
            f"🐸 Это было больно. Жаба чувствует. Но это правильно.\n\n"
            f"*{data['bank']}*\n"
            f"Было: {format_amount(debt['amount'])} ₽\n"
            f"Внесено: -{format_amount(amount)} ₽\n"
            f"Осталось: *{format_amount(new_amount)} ₽*\n\n"
            f"Общий долг: *{format_amount(total)} ₽*\n\n"
            f"─────────────────\n"
            f"_{debt_phrase(total)}_"
        )

    sent = await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())

    try:
        from aiogram.types import ReactionTypeEmoji
        emoji = "🏆" if new_amount == 0 else "🎉"
        await sent.react([ReactionTypeEmoji(emoji=emoji)])
    except Exception:
        pass

    # Проверяем вехи после платежа
    await check_milestones(message.bot, message.from_user.id)


# ── /debts ─────────────────────────────────────────────────────────────────

@router.message(Command("debts"))
@router.message(F.text == "📋 Мои долги")
async def cmd_debts(message: Message):
    upsert_user(message.from_user.id, message.from_user.username)
    debts = get_debts(message.from_user.id)
    cards = get_credit_cards(message.from_user.id)

    if not debts and not cards:
        await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
        return

    lines = ["🐸 *Все долги*\n"]

    CATEGORIES = [
        ("mortgage", "🏠 *Ипотека*"),
        ("consumer", "💰 *Потребительские кредиты*"),
        ("friend",   "🤝 *Долги друзьям*"),
    ]

    total = 0
    monthly_total = 0

    if debts:
        total = get_total(message.from_user.id)
        monthly_total = get_monthly_total(message.from_user.id)

        # Группируем по типу
        from collections import defaultdict
        by_type = defaultdict(list)
        for d in debts:
            ptype = d["product_type"] if "product_type" in d.keys() else "consumer"
            by_type[ptype].append(d)

        for ptype, header in CATEGORIES:
            group = by_type.get(ptype, [])
            if not group:
                continue

            lines.append(header + "\n")
            for d in group:
                rate_str = f" · {d['rate']}%" if d['rate'] > 0 else ""
                initial = d["initial_amount"] if d["initial_amount"] else d["amount"]
                progress = _progress_bar(d["amount"], initial)
                months = _months_left(d["amount"], d["monthly_payment"], d["rate"])
                months_str = f" · {months}" if months else ""
                day_str = f"Платёж {d['payment_day']}-го: " if d['payment_day'] else "Платёж: "
                interest = _monthly_interest(d["amount"], d["rate"])
                interest_str = f"\nИз них банку: *{format_amount(interest)} ₽* процентов" if interest > 0 else ""

                _, close_str, overpay = _closing_date(d["amount"], d["monthly_payment"], d["rate"])
                if close_str:
                    close_str_line = f"\nЗакроется в {close_str} · переплата *{format_amount(overpay)} ₽*"
                elif interest > 0 and d["monthly_payment"] <= interest:
                    close_str_line = f"\n⚠️ Платёж не покрывает проценты"
                else:
                    close_str_line = ""

                lines.append(
                    f"*{d['bank']}*{rate_str}\n"
                    f"{progress}{months_str}\n"
                    f"Остаток: {format_amount(d['amount'])} ₽\n"
                    f"{day_str}{format_amount(d['monthly_payment'])} ₽{interest_str}{close_str_line}\n"
                )

        lines.append("─────────────────")
        lines.append(f"Итого: *{format_amount(total)} ₽* · в мес: *{format_amount(monthly_total)} ₽*\n")

    if cards:
        lines.append("💳 *Кредитки*\n")
        for c in cards:
            used_pct = (c["balance"] / c["credit_limit"] * 100) if c["credit_limit"] > 0 else 0
            free = c["credit_limit"] - c["balance"]
            days_left = _grace_days_left(c["grace_end_date"])
            danger = card_danger_phrase(used_pct, days_left)

            lines.append(
                f"*{c['bank']}* (лимит {format_amount(c['credit_limit'])} ₽)\n"
                f"Долг: {format_amount(c['balance'])} ₽ · Свободно: {format_amount(free)} ₽\n"
                f"Мин. платёж: {format_amount(c['min_payment'])} ₽ · {c['payment_day']}-го\n"
                f"{danger}\n"
            )

        cards_total = get_credit_cards_total_balance(message.from_user.id)
        cards_min = get_credit_cards_min_payment_total(message.from_user.id)
        lines.append("─────────────────")
        lines.append(f"По кредиткам: *{format_amount(cards_total)} ₽* · мин. в мес: *{format_amount(cards_min)} ₽*\n")

    # Общий итог
    grand_total = get_total(message.from_user.id) + get_credit_cards_total_balance(message.from_user.id)
    lines.append(f"Всего долгов: *{format_amount(grand_total)} ₽*")
    lines.append(f"\n{debt_phrase(grand_total)}")

    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=debts_menu())


# ── /total ─────────────────────────────────────────────────────────────────

@router.message(Command("total"))
@router.message(F.text == "💰 Общий долг")
async def cmd_total(message: Message):
    total = get_total(message.from_user.id)
    cards_total = get_credit_cards_total_balance(message.from_user.id)
    grand = total + cards_total
    monthly_total = get_monthly_total(message.from_user.id)

    if grand == 0:
        await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
        return

    text = (
        f"🐸 Общий долг: *{format_amount(grand)} ₽*\n"
        f"В месяц: *{format_amount(monthly_total)} ₽*\n\n"
        f"{debt_phrase(grand)}"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())


# ── /delete ────────────────────────────────────────────────────────────────

@router.message(Command("delete"))
async def cmd_delete(message: Message):
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        debts = get_debts(message.from_user.id)
        if not debts:
            await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
            return

        lines = ["🐸 Какой кредит удалить?\nНапиши: /delete <ID>\n"]
        for d in debts:
            lines.append(f"`{d['id']}` - *{d['bank']}*, {format_amount(d['amount'])} ₽")

        await message.answer("\n".join(lines), parse_mode="Markdown")
        return

    try:
        debt_id = int(args[1].strip())
    except ValueError:
        await message.answer("Жаба не поняла. Пример: `/delete 3`", parse_mode="Markdown")
        return

    debt = get_debt(debt_id, message.from_user.id)
    if not debt:
        await message.answer("Жаба не нашла такой кредит. Проверь ID в /debts")
        return

    delete_debt(debt_id, message.from_user.id)
    total = get_total(message.from_user.id)

    text = (
        f"🐸 {phrase(PHRASES_DEBT_DELETED)}\n\n"
        f"*{debt['bank']}* удалён.\n"
    )
    if total > 0:
        text += f"Осталось: *{format_amount(total)} ₽*"
    else:
        text += "Долгов больше нет. Жаба молчит. Это хорошее молчание."

    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())

    # Веха — первый закрытый кредит
    await _send_milestone(message.bot, message.from_user.id, "first_debt_closed")
    await check_milestones(message.bot, message.from_user.id)


# ── /edit — редактировать кредит ──────────────────────────────────────────

EDIT_FIELDS = {
    "💰 Остаток":          ("amount",          "Введи новый остаток по кредиту:\n_(например: 280000)_"),
    "📅 Ежемесячный платёж": ("monthly_payment", "Введи новый ежемесячный платёж:\n_(например: 12000)_"),
    "📊 Процентная ставка": ("rate",             "Введи новую ставку в год:\n_(например: 19.9)_"),
    "🗓 День платежа":      ("payment_day",      "Введи новый день платежа:\n_(число от 1 до 31)_"),
}


@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext):
    debts = get_debts(message.from_user.id)
    if not debts:
        await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
        return

    buttons = []
    for d in debts:
        buttons.append([KeyboardButton(
            text=f"✏️ {d['bank']} - {format_amount(d['amount'])} ₽ (ID {d['id']})"
        )])
    buttons.append([KeyboardButton(text="↩ Отмена")])

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)
    await state.set_state(EditDebt.debt_id)
    await message.answer("🐸 Жаба слушает. Какой кредит правим?", reply_markup=kb)


@router.message(EditDebt.debt_id)
async def edit_select_debt(message: Message, state: FSMContext):
    if message.text == "↩ Отмена":
        await state.clear()
        await message.answer("🐸 Жаба отменила.", reply_markup=main_menu())
        return

    try:
        debt_id = int(message.text.split("(ID ")[1].rstrip(")"))
    except (IndexError, ValueError):
        await message.answer("Жаба не поняла. Выбери кредит из списка.")
        return

    debt = get_debt(debt_id, message.from_user.id)
    if not debt:
        await message.answer("Жаба не нашла такой кредит.", reply_markup=main_menu())
        return

    await state.update_data(debt_id=debt_id, bank=debt["bank"])
    await state.set_state(EditDebt.field)

    buttons = [[KeyboardButton(text=label)] for label in EDIT_FIELDS]
    buttons.append([KeyboardButton(text="↩ Отмена")])
    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

    await message.answer(
        f"🐸 *{debt['bank']}* — что правим?\n\n"
        f"Сейчас:\n"
        f"Остаток: {format_amount(debt['amount'])} ₽\n"
        f"Платёж: {format_amount(debt['monthly_payment'])} ₽\n"
        f"Ставка: {debt['rate']}%\n"
        f"День платежа: {debt['payment_day']}-е",
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(EditDebt.field)
async def edit_select_field(message: Message, state: FSMContext):
    if message.text == "↩ Отмена":
        await state.clear()
        await message.answer("🐸 Жаба отменила.", reply_markup=main_menu())
        return

    field_info = EDIT_FIELDS.get(message.text)
    if not field_info:
        await message.answer("Жаба не поняла. Выбери поле из списка.")
        return

    field_key, prompt = field_info
    await state.update_data(field=field_key)
    await state.set_state(EditDebt.value)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="↩ Отмена")]],
        resize_keyboard=True
    )
    await message.answer(prompt, parse_mode="Markdown", reply_markup=kb)


@router.message(EditDebt.value)
async def edit_apply_value(message: Message, state: FSMContext):
    if message.text == "↩ Отмена":
        await state.clear()
        await message.answer("🐸 Жаба отменила.", reply_markup=main_menu())
        return

    data = await state.get_data()
    field = data["field"]

    try:
        value = float(message.text.replace(" ", "").replace(",", "."))
        if field == "payment_day" and not (1 <= int(value) <= 31):
            raise ValueError
        if field != "payment_day" and value < 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи корректное число.")
        return

    await state.clear()

    success = update_debt(data["debt_id"], message.from_user.id, field, value)
    if not success:
        await message.answer("🐸 Жаба не смогла обновить. Попробуй ещё раз.", reply_markup=main_menu())
        return

    FIELD_LABELS = {
        "amount":          "Остаток",
        "monthly_payment": "Платёж",
        "rate":            "Ставка",
        "payment_day":     "День платежа",
    }
    label = FIELD_LABELS.get(field, field)
    unit = "-е" if field == "payment_day" else (" %" if field == "rate" else " ₽")

    await message.answer(
        f"🐸 Жаба обновила.\n\n"
        f"*{data['bank']}* — {label}: *{format_amount(value)}{unit}*\n\n"
        f"Жаба записала. Жаба не переспрашивает.",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ── /cancel ────────────────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        await state.clear()
        await message.answer(
            "🐸 Жаба остановила. Начни заново когда будешь готов.",
            reply_markup=main_menu()
        )
    else:
        await message.answer("🐸 Жаба ничего не делает. Нечего отменять.", reply_markup=main_menu())


# ── Удалить кредит через меню ──────────────────────────────────────────────

@router.message(F.text == "✏️ Редактировать кредит")
async def menu_edit(message: Message, state: FSMContext):
    await cmd_edit(message, state)


@router.message(F.text == "🗑 Удалить кредит")
async def menu_delete(message: Message):
    debts = get_debts(message.from_user.id)
    if not debts:
        await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
        return

    buttons = []
    for d in debts:
        buttons.append([KeyboardButton(text=f"❌ {d['bank']} - {format_amount(d['amount'])} ₽ (ID {d['id']})")])
    buttons.append([KeyboardButton(text="↩ Отмена")])

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🐸 Какой кредит удалить?", reply_markup=kb)


@router.message(F.text.startswith("❌"))
async def delete_by_button(message: Message):
    # Кредитка — кнопка содержит "долг" и "#"
    if "долг" in message.text and "#" in message.text:
        try:
            card_id = int(message.text.split("#")[1])
        except (IndexError, ValueError):
            await message.answer("Жаба не поняла. Попробуй ещё раз.")
            return

        card = get_credit_card(card_id, message.from_user.id)
        if not card:
            await message.answer("Жаба не нашла такую кредитку.", reply_markup=main_menu())
            return

        delete_credit_card(card_id, message.from_user.id)
        await message.answer(
            "🐸 Кредитка " + card["bank"] + " удалена.\n\nЖаба выдыхает. Одной кредиткой меньше.",
            reply_markup=main_menu()
        )
        return

    # Обычный кредит
    try:
        debt_id = int(message.text.split("(ID ")[1].rstrip(")"))
    except (IndexError, ValueError):
        await message.answer("Жаба не поняла. Попробуй ещё раз.")
        return

    debt = get_debt(debt_id, message.from_user.id)
    if not debt:
        await message.answer("Жаба не нашла такой кредит.", reply_markup=main_menu())
        return

    delete_debt(debt_id, message.from_user.id)
    total = get_total(message.from_user.id)

    text = (
        f"🐸 {phrase(PHRASES_DEBT_DELETED)}\n\n"
        f"*{debt['bank']}* удалён.\n"
    )
    if total > 0:
        text += f"Осталось: *{format_amount(total)} ₽*"
    else:
        text += "Долгов больше нет. Жаба молчит. Это хорошее молчание."

    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())

    # Веха — первый закрытый кредит
    await _send_milestone(message.bot, message.from_user.id, "first_debt_closed")
    await check_milestones(message.bot, message.from_user.id)


@router.message(F.text == "↩ Отмена")
async def delete_cancel(message: Message):
    await message.answer("🐸 Жаба отменила.", reply_markup=main_menu())


# ── /card — добавить кредитку ──────────────────────────────────────────────

@router.message(Command("card"))
async def cmd_card(message: Message, state: FSMContext):
    await state.set_state(AddCard.bank)
    await message.answer(
        "🐸 Жаба смотрит с подозрением. Кредитка?\n\n"
        "Жаба не осуждает. Жаба записывает.\n\n"
        "Как называется банк кредитки?\n_(например: Тинькофф, Альфа, Сбер)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(AddCard.bank)
async def card_add_bank(message: Message, state: FSMContext):
    await state.update_data(bank=message.text.strip())
    await state.set_state(AddCard.credit_limit)
    await message.answer(
        "Какой кредитный лимит?\n_(например: 100000)_",
        parse_mode="Markdown"
    )


@router.message(AddCard.credit_limit)
async def card_add_limit(message: Message, state: FSMContext):
    try:
        limit = float(message.text.replace(" ", "").replace(",", "."))
        if limit <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *100000*", parse_mode="Markdown")
        return

    await state.update_data(credit_limit=limit)
    await state.set_state(AddCard.balance)
    await message.answer(
        "Сколько сейчас потрачено по кредитке?\n_(текущий долг, например: 25000)\n\nЕсли карта не использовалась — напиши *0*_",
        parse_mode="Markdown"
    )


@router.message(AddCard.balance)
async def card_add_balance(message: Message, state: FSMContext):
    try:
        balance = float(message.text.replace(" ", "").replace(",", "."))
        if balance < 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *25000*", parse_mode="Markdown")
        return

    await state.update_data(balance=balance)
    await state.set_state(AddCard.min_payment)
    await message.answer(
        "Какой минимальный обязательный платёж в месяц?\n_(например: 1500)\n\nЕсли не знаешь точно — напиши примерно_",
        parse_mode="Markdown"
    )


@router.message(AddCard.min_payment)
async def card_add_min_payment(message: Message, state: FSMContext):
    try:
        min_pay = float(message.text.replace(" ", "").replace(",", "."))
        if min_pay < 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *1500*", parse_mode="Markdown")
        return

    await state.update_data(min_payment=min_pay)
    await state.set_state(AddCard.payment_day)
    await message.answer(
        "Какого числа платёж?\n_(число от 1 до 31)_",
        parse_mode="Markdown"
    )


@router.message(AddCard.payment_day)
async def card_add_payment_day(message: Message, state: FSMContext):
    try:
        day = int(message.text.strip())
        if not (1 <= day <= 31):
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число от *1* до *31*", parse_mode="Markdown")
        return

    await state.update_data(payment_day=day)
    await state.set_state(AddCard.grace)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer(
        "Есть грейс-период (беспроцентный период)?\n\n"
        "_Грейс — когда банк не начисляет проценты если погасить долг до определённой даты._",
        parse_mode="Markdown",
        reply_markup=kb
    )


@router.message(AddCard.grace)
async def card_add_grace(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text in ("да", "yes", "y"):
        await state.update_data(has_grace=True)
        await state.set_state(AddCard.grace_end_date)
        await message.answer(
            "До какого числа этого месяца действует грейс?\n_(например: 25)\n\n"
            "Жаба посчитает сколько дней осталось._",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    elif text in ("нет", "no", "n"):
        await state.update_data(has_grace=False, grace_end_date=None)
        await _finish_add_card(message, state)
    else:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await message.answer("Жаба не поняла. Да или Нет?", reply_markup=kb)


@router.message(AddCard.grace_end_date)
async def card_add_grace_date(message: Message, state: FSMContext):
    try:
        day = int(message.text.strip())
        if not (1 <= day <= 31):
            raise ValueError
        today = date.today()
        grace_date = date(today.year, today.month, day)
        # если дата уже прошла — переносим на следующий месяц
        if grace_date < today:
            if today.month == 12:
                grace_date = date(today.year + 1, 1, day)
            else:
                grace_date = date(today.year, today.month + 1, day)
        await state.update_data(grace_end_date=grace_date.isoformat())
    except ValueError:
        await message.answer("Жаба не поняла. Введи число от *1* до *31*", parse_mode="Markdown")
        return

    await _finish_add_card(message, state)


async def _finish_add_card(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    card_id = add_credit_card(
        user_id=message.from_user.id,
        bank=data["bank"],
        credit_limit=data["credit_limit"],
        balance=data["balance"],
        min_payment=data["min_payment"],
        payment_day=data["payment_day"],
        grace_end_date=data.get("grace_end_date")
    )

    used_pct = (data["balance"] / data["credit_limit"] * 100) if data["credit_limit"] > 0 else 0
    free = data["credit_limit"] - data["balance"]
    days_left = _grace_days_left(data.get("grace_end_date"))
    danger = card_danger_phrase(used_pct, days_left)

    grace_str = ""
    if data.get("grace_end_date"):
        grace_str = f"Грейс до: {data['grace_end_date']}\n"

    text = (
        f"🐸 {phrase(PHRASES_CARD_ADDED)}\n\n"
        f"*{data['bank']}*\n"
        f"Лимит: {format_amount(data['credit_limit'])} ₽\n"
        f"Долг: {format_amount(data['balance'])} ₽ · Свободно: {format_amount(free)} ₽\n"
        f"Мин. платёж: {format_amount(data['min_payment'])} ₽ · {data['payment_day']}-го\n"
        f"{grace_str}"
        f"\n{danger}"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())


# ── /spend — добавить трату по кредитке ───────────────────────────────────

@router.message(Command("spend"))
async def cmd_spend(message: Message, state: FSMContext):
    cards = get_credit_cards(message.from_user.id)
    if not cards:
        await message.answer(
            "🐸 Кредиток нет. Добавь кредитку через /card",
            reply_markup=main_menu()
        )
        return

    buttons = [[KeyboardButton(
        text=f"{c['bank']} - долг {format_amount(c['balance'])} ₽ #{c['id']}"
    )] for c in cards]

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)
    await state.set_state(CardSpend.card_id)
    await message.answer("🐸 По какой кредитке трата?", reply_markup=kb)


@router.message(CardSpend.card_id)
async def spend_select_card(message: Message, state: FSMContext):
    try:
        card_id = int(message.text.split("#")[1])
    except ValueError:
        await message.answer("Жаба не поняла. Выбери кредитку из списка.")
        return

    card = get_credit_card(card_id, message.from_user.id)
    if not card:
        await message.answer("Жаба не нашла такую кредитку.")
        return

    free = card["credit_limit"] - card["balance"]
    await state.update_data(card_id=card_id, bank=card["bank"],
                             limit=card["credit_limit"], balance=card["balance"])
    await state.set_state(CardSpend.amount)
    await message.answer(
        f"*{card['bank']}*\n"
        f"Сейчас долг: {format_amount(card['balance'])} ₽ · Свободно: {format_amount(free)} ₽\n\n"
        f"Сколько потратил?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(CardSpend.amount)
async def spend_confirm(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *3000*", parse_mode="Markdown")
        return

    data = await state.get_data()
    await state.clear()

    new_balance = update_card_balance(data["card_id"], message.from_user.id, +amount)
    if new_balance is None:
        await message.answer("Жаба не нашла кредитку. Попробуй снова.", reply_markup=main_menu())
        return

    card = get_credit_card(data["card_id"], message.from_user.id)
    free = card["credit_limit"] - new_balance
    used_pct = (new_balance / card["credit_limit"] * 100) if card["credit_limit"] > 0 else 0

    # Большая трата — другой пул фраз
    pool = PHRASES_CARD_SPEND_BIG if amount >= 10_000 else PHRASES_CARD_SPEND
    spend_text = phrase(pool)

    text = (
        f"🐸 {spend_text}\n\n"
        f"*{data['bank']}*\n"
        f"Потрачено: +{format_amount(amount)} ₽\n"
        f"Долг: *{format_amount(new_balance)} ₽*\n"
        f"Свободно: {format_amount(free)} ₽ ({100 - int(used_pct)}% лимита)\n\n"
        f"{card_danger_phrase(used_pct, _grace_days_left(card['grace_end_date']))}"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())


# ── /cardpay — платёж по кредитке ─────────────────────────────────────────

@router.message(Command("cardpay"))
async def cmd_cardpay(message: Message, state: FSMContext):
    cards = get_credit_cards(message.from_user.id)
    if not cards:
        await message.answer(
            "🐸 Кредиток нет. Добавь кредитку через /card",
            reply_markup=main_menu()
        )
        return

    buttons = [[KeyboardButton(
        text=f"{c['bank']} - долг {format_amount(c['balance'])} ₽ #{c['id']}"
    )] for c in cards]

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)
    await state.set_state(CardPay.card_id)
    await message.answer("🐸 По какой кредитке вносим платёж?", reply_markup=kb)


@router.message(CardPay.card_id)
async def cardpay_select(message: Message, state: FSMContext):
    try:
        card_id = int(message.text.split("#")[1])
    except ValueError:
        await message.answer("Жаба не поняла. Выбери кредитку из списка.")
        return

    card = get_credit_card(card_id, message.from_user.id)
    if not card:
        await message.answer("Жаба не нашла такую кредитку.")
        return

    await state.update_data(card_id=card_id, bank=card["bank"], balance=card["balance"])
    await state.set_state(CardPay.amount)
    await message.answer(
        f"*{card['bank']}* — долг {format_amount(card['balance'])} ₽\n\n"
        f"Сколько вносишь?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(CardPay.amount)
async def cardpay_confirm(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Жаба не поняла. Введи число - например: *5000*", parse_mode="Markdown")
        return

    data = await state.get_data()
    await state.clear()

    new_balance = update_card_balance(data["card_id"], message.from_user.id, -amount)
    if new_balance is None:
        await message.answer("Жаба не нашла кредитку. Попробуй снова.", reply_markup=main_menu())
        return

    card = get_credit_card(data["card_id"], message.from_user.id)
    free = card["credit_limit"] - new_balance
    used_pct = (new_balance / card["credit_limit"] * 100) if card["credit_limit"] > 0 else 0

    if new_balance == 0:
        pay_text = phrase(PHRASES_CARD_PAID_FULL)
    else:
        pay_text = phrase(PHRASES_CARD_PAYMENT)

    text = (
        f"🐸 {pay_text}\n\n"
        f"*{data['bank']}*\n"
        f"Внесено: -{format_amount(amount)} ₽\n"
        f"Долг: *{format_amount(new_balance)} ₽*\n"
        f"Свободно: {format_amount(free)} ₽\n\n"
        f"{card_danger_phrase(used_pct, _grace_days_left(card['grace_end_date']))}"
    )

    sent = await message.answer(text, parse_mode="Markdown", reply_markup=main_menu())

    try:
        from aiogram.types import ReactionTypeEmoji
        emoji = "🏆" if new_balance == 0 else "🎉"
        await sent.react([ReactionTypeEmoji(emoji=emoji)])
    except Exception:
        pass


# ── 💰 Кредитки — кнопка меню ─────────────────────────────────────────────

@router.message(F.text == "💰 Кредитки")
async def menu_cards(message: Message):
    cards = get_credit_cards(message.from_user.id)
    if not cards:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="➕ Добавить кредитку"), KeyboardButton(text="↩ Назад")]],
            resize_keyboard=True
        )
        await message.answer(
            "🐸 Кредиток пока нет.\n\nКредитка — инструмент. Жаба не осуждает. Но смотрит.",
            reply_markup=kb
        )
        return

    lines = ["🐸 *Кредитки*\n"]
    for c in cards:
        used_pct = (c["balance"] / c["credit_limit"] * 100) if c["credit_limit"] > 0 else 0
        free = c["credit_limit"] - c["balance"]
        days_left = _grace_days_left(c["grace_end_date"])
        danger = card_danger_phrase(used_pct, days_left)

        lines.append(
            f"*{c['bank']}*\n"
            f"Лимит: {format_amount(c['credit_limit'])} ₽\n"
            f"Долг: {format_amount(c['balance'])} ₽ · Свободно: {format_amount(free)} ₽\n"
            f"Мин. платёж: {format_amount(c['min_payment'])} ₽ · {c['payment_day']}-го\n"
            f"{danger}\n"
        )

    total = get_credit_cards_total_balance(message.from_user.id)
    lines.append("─────────────────")
    lines.append(f"Итого долг по кредиткам: *{format_amount(total)} ₽*")

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить кредитку")],
            [KeyboardButton(text="💸 Записать трату"), KeyboardButton(text="💳 Погасить кредитку")],
            [KeyboardButton(text="🗑 Удалить кредитку"), KeyboardButton(text="↩ Назад")]
        ],
        resize_keyboard=True
    )
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=kb)


@router.message(F.text == "➕ Добавить кредитку")
async def menu_add_card(message: Message, state: FSMContext):
    await cmd_card(message, state)


@router.message(F.text == "💸 Записать трату")
async def menu_spend(message: Message, state: FSMContext):
    await cmd_spend(message, state)


@router.message(F.text == "💳 Погасить кредитку")
async def menu_cardpay(message: Message, state: FSMContext):
    await cmd_cardpay(message, state)


@router.message(F.text == "🗑 Удалить кредитку")
async def menu_delete_card(message: Message):
    cards = get_credit_cards(message.from_user.id)
    if not cards:
        await message.answer("🐸 Кредиток нет.", reply_markup=main_menu())
        return

    buttons = []
    for c in cards:
        buttons.append([KeyboardButton(
            text=f"❌ {c['bank']} - долг {format_amount(c['balance'])} ₽ #{c['id']}"
        )])
    buttons.append([KeyboardButton(text="↩ Отмена")])

    kb = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)
    await message.answer("🐸 Какую кредитку удалить?", reply_markup=kb)





@router.message(F.text == "↩ Назад")
async def menu_back(message: Message):
    await message.answer("🐸", reply_markup=main_menu())


# ── /when - калькулятор «когда выплачу» ────────────────────────────────────

@router.message(Command("when"))
@router.message(F.text == "📅 Когда выплачу")
async def cmd_when(message: Message):
    debts = get_debts(message.from_user.id)
    if not debts:
        await message.answer(f"🐸 {phrase(PHRASES_NO_DEBTS)}", reply_markup=main_menu())
        return

    lines = ["🐸 *Когда выплачу - при текущем платеже*\n"]
    for d in debts:
        initial = d["initial_amount"] if d["initial_amount"] else d["amount"]
        progress = _progress_bar(d["amount"], initial)
        rate_str = f" · {d['rate']}%" if d['rate'] > 0 else " · без процентов"
        _, close_str, overpay = _closing_date(d["amount"], d["monthly_payment"], d["rate"])
        if close_str:
            close_line = f"Закроется в {close_str}"
            overpay_line = f"Переплата: *{format_amount(overpay)} ₽*" if overpay and overpay > 0 else ""
        else:
            interest = _monthly_interest(d["amount"], d["rate"])
            if interest > 0 and d["monthly_payment"] <= interest:
                close_line = f"⚠️ Платёж не покрывает проценты — долг растёт"
                overpay_line = f"Только процентов в месяц: *{format_amount(interest)} ₽*"
            else:
                close_line = ""
                overpay_line = ""
        lines.append(
            f"*{d['bank']}*{rate_str}\n"
            f"{progress}\n"
            f"Осталось: {format_amount(d['amount'])} ₽\n"
            f"Платёж {format_amount(d['monthly_payment'])} ₽/мес\n"
            + (f"{close_line}\n" if close_line else "")
            + (f"{overpay_line}\n" if overpay_line else "")
        )

    lines.append("─────────────────")
    lines.append("_Жаба считала с учётом процентов. Реальный срок может отличаться._")

    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu())


# ── /feedback ──────────────────────────────────────────────────────────────

MY_ID = 683788387

class Feedback(StatesGroup):
    text = State()


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext):
    await state.set_state(Feedback.text)
    await message.answer(
        "🐸 Жаба слушает.\n\nНапиши что думаешь - что нравится, что мешает, чего не хватает.\n\nЖаба передаст.",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(Feedback.text)
async def feedback_receive(message: Message, state: FSMContext):
    await state.clear()

    user = message.from_user
    username = f"@{user.username}" if user.username else f"id{user.id}"
    forward_text = (
        f"🐸 Новый отзыв\n\n"
        f"От: {user.first_name} {username}\n\n"
        f"{message.text}"
    )
    try:
        await message.bot.send_message(MY_ID, forward_text)
    except Exception:
        pass

    await message.answer(
        "🐸 Жаба передала. Спасибо что написал.\n\nЖаба читает каждый отзыв. Жаба не говорит об этом. Но читает.",
        reply_markup=main_menu()
    )


# ── /stats — только для админа ─────────────────────────────────────────────

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != MY_ID:
        return

    import database
    with database.get_conn() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        users_with_debts = conn.execute("SELECT COUNT(DISTINCT user_id) FROM debts").fetchone()[0]
        users_with_cards = conn.execute("SELECT COUNT(DISTINCT user_id) FROM credit_cards").fetchone()[0]
        users_with_anything = conn.execute(
            """SELECT COUNT(DISTINCT user_id) FROM (
                SELECT user_id FROM debts
                UNION
                SELECT user_id FROM credit_cards
            )"""
        ).fetchone()[0]
        total_debts = conn.execute("SELECT COUNT(*) FROM debts").fetchone()[0]
        total_cards = conn.execute("SELECT COUNT(*) FROM credit_cards").fetchone()[0]
        total_amount = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM debts").fetchone()[0]
        total_cards_balance = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM credit_cards").fetchone()[0]
        active_7d = conn.execute(
            "SELECT COUNT(*) FROM users WHERE last_seen >= date('now', '-7 days')"
        ).fetchone()[0]
        active_30d = conn.execute(
            "SELECT COUNT(*) FROM users WHERE last_seen >= date('now', '-30 days')"
        ).fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE created_at >= date('now')"
        ).fetchone()[0]
        count_consumer = conn.execute("SELECT COUNT(*) FROM debts WHERE product_type = 'consumer'").fetchone()[0]
        count_consumer_active = conn.execute("SELECT COUNT(*) FROM debts WHERE product_type = 'consumer' AND closed_at IS NULL").fetchone()[0]
        count_mortgage = conn.execute("SELECT COUNT(*) FROM debts WHERE product_type = 'mortgage'").fetchone()[0]
        count_mortgage_active = conn.execute("SELECT COUNT(*) FROM debts WHERE product_type = 'mortgage' AND closed_at IS NULL").fetchone()[0]
        count_friend = conn.execute("SELECT COUNT(*) FROM debts WHERE product_type = 'friend'").fetchone()[0]
        count_friend_active = conn.execute("SELECT COUNT(*) FROM debts WHERE product_type = 'friend' AND closed_at IS NULL").fetchone()[0]
        sum_consumer = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM debts WHERE product_type = 'consumer' AND closed_at IS NULL").fetchone()[0]
        sum_mortgage = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM debts WHERE product_type = 'mortgage' AND closed_at IS NULL").fetchone()[0]
        sum_friend = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM debts WHERE product_type = 'friend' AND closed_at IS NULL").fetchone()[0]
        count_closed = conn.execute("SELECT COUNT(*) FROM debts WHERE closed_at IS NOT NULL").fetchone()[0]

    conversion = round(users_with_anything / total_users * 100) if total_users else 0

    text = (
        f"🐸 *Статистика Жабы*\n\n"
        f"👤 Пользователей всего: *{total_users}*\n"
        f"➕ Новых сегодня: *{new_today}*\n"
        f"📅 Активных за 7 дней: *{active_7d}*\n"
        f"📅 Активных за 30 дней: *{active_30d}*\n\n"
        f"✅ Добавили что-то: *{users_with_anything}* ({conversion}%)\n"
        f"💰 Потреб. кредитов: *{count_consumer}* всего · *{count_consumer_active}* активных · {format_amount(sum_consumer)} ₽\n"
        f"🏠 Ипотек: *{count_mortgage}* всего · *{count_mortgage_active}* активных · {format_amount(sum_mortgage)} ₽\n"
        f"🤝 Долгов друзьям: *{count_friend}* всего · *{count_friend_active}* активных · {format_amount(sum_friend)} ₽\n"
        f"💳 Кредиток: *{total_cards}* · {format_amount(total_cards_balance)} ₽\n"
        f"🏆 Закрыто кредитов: *{count_closed}*\n"
    )
    await message.answer(text, parse_mode="Markdown")


# ── Хелперы ────────────────────────────────────────────────────────────────

def _monthly_interest(amount: float, rate: float) -> float:
    """Сколько из платежа уходит на проценты в этом месяце."""
    if rate <= 0 or amount <= 0:
        return 0.0
    return round(amount * rate / 12 / 100, 2)


def _closing_date(amount: float, monthly: float, rate: float):
    """Возвращает (месяцев, строка_даты, итоговая_переплата)."""
    import math
    if monthly <= 0 or amount <= 0:
        return None, None, None
    if rate > 0:
        r = rate / 12 / 100
        if monthly <= amount * r:
            return None, None, None
        try:
            months = math.ceil(-math.log(1 - r * amount / monthly) / math.log(1 + r))
        except Exception:
            months = int(amount / monthly)
    else:
        months = int(amount / monthly)
        if amount % monthly > 0:
            months += 1

    today = date.today()
    close_month = today.month + months
    close_year = today.year + (close_month - 1) // 12
    close_month = ((close_month - 1) % 12) + 1

    total_paid = monthly * months
    overpay = round(total_paid - amount, 2)

    MONTHS_RU = [
        "", "январе", "феврале", "марте", "апреле", "мае", "июне",
        "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"
    ]
    close_str = f"{MONTHS_RU[close_month]} {close_year}"
    return months, close_str, overpay


def _progress_bar(current: float, initial: float) -> str:
    if initial <= 0:
        return "▓▓▓▓▓▓▓▓▓▓ 0%"
    paid = initial - current
    percent = min(100, max(0, int(paid / initial * 100)))
    filled = percent // 10
    empty = 10 - filled
    return f"{'▓' * filled}{'░' * empty} {percent}%"


def _months_left(amount: float, monthly: float, rate: float = 0) -> str:
    if monthly <= 0 or amount <= 0:
        return ""

    if rate > 0:
        r = rate / 12 / 100
        monthly_interest = amount * r
        if monthly <= monthly_interest:
            return "❗платёж не покрывает проценты"
        import math
        try:
            months = math.ceil(-math.log(1 - r * amount / monthly) / math.log(1 + r))
        except Exception:
            months = int(amount / monthly)
    else:
        months = int(amount / monthly)

    if months < 1:
        return "меньше месяца"
    elif months < 12:
        return f"~{months} {_plural(months, 'месяц', 'месяца', 'месяцев')}"
    else:
        years = months // 12
        m = months % 12
        y_str = f"~{years} {_plural(years, 'год', 'года', 'лет')}"
        if m == 0:
            return y_str
        return f"{y_str} {m} {_plural(m, 'месяц', 'месяца', 'месяцев')}"


def _plural(n: int, form1: str, form2: str, form5: str) -> str:
    """Склонение по числу: 1 год, 2 года, 5 лет."""
    n = abs(n) % 100
    if 11 <= n <= 19:
        return form5
    n = n % 10
    if n == 1:
        return form1
    if 2 <= n <= 4:
        return form2
    return form5


def _grace_days_left(grace_end_date) -> int:
    """Сколько дней осталось до конца грейса. None если грейса нет."""
    if not grace_end_date:
        return None
    try:
        end = date.fromisoformat(grace_end_date)
        return (end - date.today()).days
    except Exception:
        return None
