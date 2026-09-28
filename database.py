import sqlite3
from datetime import date, datetime
from typing import Optional, List
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                created_at  TEXT DEFAULT (date('now')),
                last_seen   TEXT DEFAULT (date('now')),
                initial_total REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS debts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                bank            TEXT NOT NULL,
                product_type    TEXT NOT NULL DEFAULT 'consumer',
                amount          REAL NOT NULL,
                initial_amount  REAL NOT NULL,
                rate            REAL NOT NULL,
                payment_day     INTEGER NOT NULL DEFAULT 0,
                monthly_payment REAL NOT NULL,
                loan_term_months INTEGER,
                created_at      TEXT DEFAULT (date('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS credit_cards (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                bank            TEXT NOT NULL,
                credit_limit    REAL NOT NULL,
                balance         REAL NOT NULL DEFAULT 0,
                min_payment     REAL NOT NULL DEFAULT 0,
                payment_day     INTEGER NOT NULL,
                grace_days      INTEGER,
                grace_end_date  TEXT,
                created_at      TEXT DEFAULT (date('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS milestones (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                milestone   TEXT NOT NULL,
                reached_at  TEXT DEFAULT (date('now')),
                UNIQUE(user_id, milestone),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)

        # Migrate: add initial_amount if missing
        try:
            conn.execute("ALTER TABLE debts ADD COLUMN initial_amount REAL NOT NULL DEFAULT 0")
            conn.execute("UPDATE debts SET initial_amount = amount WHERE initial_amount = 0")
        except Exception:
            pass

        # Migrate: add product_type if missing
        try:
            conn.execute("ALTER TABLE debts ADD COLUMN product_type TEXT NOT NULL DEFAULT 'consumer'")
        except Exception:
            pass

        # Migrate: add loan_term_months if missing
        try:
            conn.execute("ALTER TABLE debts ADD COLUMN loan_term_months INTEGER")
        except Exception:
            pass

        # Migrate: add last_seen if missing
        try:
            conn.execute("ALTER TABLE users ADD COLUMN last_seen TEXT DEFAULT (date('now'))")
        except Exception:
            pass

        # Migrate: add initial_total if missing
        try:
            conn.execute("ALTER TABLE users ADD COLUMN initial_total REAL DEFAULT 0")
        except Exception:
            pass

        # Migrate: add closed_at if missing
        try:
            conn.execute("ALTER TABLE debts ADD COLUMN closed_at TEXT DEFAULT NULL")
        except Exception:
            pass


# ── Users ──────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: Optional[str]):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        conn.execute(
            "UPDATE users SET last_seen = date('now') WHERE user_id = ?",
            (user_id,)
        )


def get_user_last_seen(user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_seen FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["last_seen"] if row else None


def get_user_created_at(user_id: int) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT created_at FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["created_at"] if row else None


def get_inactive_users(days: int) -> List[sqlite3.Row]:
    """Users who haven't been seen for N+ days and have debts or credit cards."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT DISTINCT u.user_id FROM users u
               WHERE (
                   EXISTS (SELECT 1 FROM debts d WHERE d.user_id = u.user_id)
                   OR EXISTS (SELECT 1 FROM credit_cards c WHERE c.user_id = u.user_id)
               )
               AND u.last_seen <= date('now', ?)""",
            (f"-{days} days",)
        ).fetchall()


def get_all_users() -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT user_id FROM users").fetchall()


# ── initial_total — точка отсчёта для вех прогресса ───────────────────────

def get_initial_total(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT initial_total FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["initial_total"] if row else 0.0


def maybe_set_initial_total(user_id: int, total: float):
    """Фиксирует initial_total только если он ещё не установлен (равен 0)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET initial_total = ? WHERE user_id = ? AND (initial_total IS NULL OR initial_total = 0)",
            (total, user_id)
        )


# ── Debts ──────────────────────────────────────────────────────────────────

def add_debt(user_id: int, bank: str, amount: float,
             initial_amount: float, rate: float, payment_day: int, monthly_payment: float,
             product_type: str = 'consumer', loan_term_months: int = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO debts (user_id, bank, product_type, amount, initial_amount, rate,
                                  payment_day, monthly_payment, loan_term_months)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, bank, product_type, amount, initial_amount, rate,
             payment_day, monthly_payment, loan_term_months)
        )
        return cur.lastrowid


def get_debts(user_id: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM debts WHERE user_id = ? AND closed_at IS NULL ORDER BY amount DESC",
            (user_id,)
        ).fetchall()


def get_closed_debts(user_id: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM debts WHERE user_id = ? AND closed_at IS NOT NULL ORDER BY closed_at DESC",
            (user_id,)
        ).fetchall()


def get_debt(debt_id: int, user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM debts WHERE id = ? AND user_id = ?",
            (debt_id, user_id)
        ).fetchone()


def delete_debt(debt_id: int, user_id: int) -> bool:
    """Мягкое удаление — помечаем как закрытый, не удаляем из базы."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE debts SET closed_at = date('now') WHERE id = ? AND user_id = ? AND closed_at IS NULL",
            (debt_id, user_id)
        )
        return cur.rowcount > 0


def get_total(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM debts WHERE user_id = ? AND closed_at IS NULL",
            (user_id,)
        ).fetchone()
        return row["total"]


def get_monthly_total(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(monthly_payment), 0) as total FROM debts WHERE user_id = ? AND closed_at IS NULL",
            (user_id,)
        ).fetchone()
        return row["total"]


def get_all_users_with_debts() -> List[sqlite3.Row]:
    """Все пользователи у которых есть активные долги или кредитки."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT DISTINCT user_id FROM (
                SELECT user_id FROM debts WHERE closed_at IS NULL
                UNION
                SELECT user_id FROM credit_cards
            )"""
        ).fetchall()


def get_debts_due_today(payment_day: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM debts WHERE payment_day = ? AND closed_at IS NULL",
            (payment_day,)
        ).fetchall()


# ── Credit Cards ───────────────────────────────────────────────────────────

def add_credit_card(user_id: int, bank: str, credit_limit: float,
                    balance: float, min_payment: float, payment_day: int,
                    grace_days: Optional[int] = None,
                    grace_end_date: Optional[str] = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO credit_cards
               (user_id, bank, credit_limit, balance, min_payment, payment_day, grace_days, grace_end_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, bank, credit_limit, balance, min_payment, payment_day, grace_days, grace_end_date)
        )
        return cur.lastrowid


def get_credit_cards(user_id: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM credit_cards WHERE user_id = ? ORDER BY balance DESC",
            (user_id,)
        ).fetchall()


def get_credit_card(card_id: int, user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM credit_cards WHERE id = ? AND user_id = ?",
            (card_id, user_id)
        ).fetchone()


def delete_credit_card(card_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM credit_cards WHERE id = ? AND user_id = ?",
            (card_id, user_id)
        )
        return cur.rowcount > 0


def update_card_balance(card_id: int, user_id: int, delta: float) -> Optional[float]:
    """Изменить баланс на delta (+ трата, - платёж). Возвращает новый баланс."""
    with get_conn() as conn:
        card = conn.execute(
            "SELECT * FROM credit_cards WHERE id = ? AND user_id = ?",
            (card_id, user_id)
        ).fetchone()
        if not card:
            return None
        new_balance = max(0.0, card["balance"] + delta)
        conn.execute(
            "UPDATE credit_cards SET balance = ? WHERE id = ?",
            (new_balance, card_id)
        )
        return new_balance


def get_cards_due_today(payment_day: int) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM credit_cards WHERE payment_day = ?",
            (payment_day,)
        ).fetchall()


def get_cards_grace_ending(days_ahead: int) -> List[sqlite3.Row]:
    """Кредитки у которых грейс заканчивается через days_ahead дней."""
    with get_conn() as conn:
        target = f"date('now', '+{days_ahead} days')"
        return conn.execute(
            f"SELECT * FROM credit_cards WHERE grace_end_date = {target}"
        ).fetchall()


def get_credit_cards_total_balance(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) as total FROM credit_cards WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["total"]


def get_credit_cards_min_payment_total(user_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(min_payment), 0) as total FROM credit_cards WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return row["total"]


# ── Milestones ─────────────────────────────────────────────────────────────

def save_milestone(user_id: int, milestone: str) -> bool:
    """Сохраняет веху. Возвращает True если веха новая, False если уже была."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO milestones (user_id, milestone) VALUES (?, ?)",
                (user_id, milestone)
            )
        return True
    except sqlite3.IntegrityError:
        # UNIQUE constraint — веха уже была
        return False


def update_debt(debt_id: int, user_id: int, field: str, value: float) -> bool:
    allowed = {"amount", "monthly_payment", "rate", "payment_day"}
    if field not in allowed:
        return False
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE debts SET {field} = ? WHERE id = ? AND user_id = ?",
            (value, debt_id, user_id)
        )
        return cur.rowcount > 0


def get_user_milestones(user_id: int) -> List[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT milestone FROM milestones WHERE user_id = ?",
            (user_id,)
        ).fetchall()
        return [r["milestone"] for r in rows]
