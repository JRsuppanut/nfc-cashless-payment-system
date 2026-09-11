import sqlite3
import datetime
from typing import Optional, Dict, Any, List, Tuple

DATABASE_FILE = "foodcourt_ledger.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                token_uuid TEXT PRIMARY KEY,
                card_uid TEXT NOT NULL,
                balance REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transaction_ledger (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_uuid TEXT NOT NULL,
                card_uid TEXT NOT NULL,
                terminal_type TEXT NOT NULL,
                action_type TEXT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                FOREIGN KEY (token_uuid) REFERENCES wallets (token_uuid)
            )
            """
        )
        conn.commit()


def get_wallet_by_token(token_uuid: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallets WHERE token_uuid = ?", (token_uuid,))
        row = cursor.fetchone()
        return dict(row) if row else None


def register_provisioned_card(token_uuid: str, card_uid: str) -> bool:
    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO wallets (token_uuid, card_uid, balance, status, created_at, updated_at)
            VALUES (?, ?, 0.0, 'ACTIVE', ?, ?)
            ON CONFLICT(token_uuid) DO NOTHING
            """,
            (token_uuid, card_uid, now, now),
        )
        conn.commit()
        return True


def process_top_up(token_uuid: str, card_uid: str, amount: float) -> Tuple[bool, str, float]:
    if amount <= 0:
        return False, "INVALID_AMOUNT", 0.0

    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT balance, status FROM wallets WHERE token_uuid = ?", (token_uuid,))
            wallet = cursor.fetchone()
            if wallet is None:
                return False, "WALLET_NOT_FOUND", 0.0

            if wallet["status"] != "ACTIVE":
                return False, "WALLET_SUSPENDED", wallet["balance"]

            new_balance = round(wallet["balance"] + amount, 2)
            cursor.execute(
                "UPDATE wallets SET balance = ?, updated_at = ? WHERE token_uuid = ?",
                (new_balance, now, token_uuid),
            )
            cursor.execute(
                """
                INSERT INTO transaction_ledger 
                (token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp)
                VALUES (?, ?, 'CASHIER', 'TOP_UP', ?, ?, ?)
                """,
                (token_uuid, card_uid, amount, new_balance, now),
            )
            conn.commit()
            return True, "SUCCESS", new_balance
        except Exception as exc:
            conn.rollback()
            return False, f"TX_ERROR: {exc}", 0.0


def process_deduction(token_uuid: str, card_uid: str, amount: float) -> Tuple[bool, str, float]:
    if amount <= 0:
        return False, "INVALID_AMOUNT", 0.0

    now = datetime.datetime.now().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT balance, status FROM wallets WHERE token_uuid = ?", (token_uuid,))
            wallet = cursor.fetchone()

            if wallet is None:
                return False, "UNREGISTERED_TOKEN", 0.0

            if wallet["status"] != "ACTIVE":
                return False, "CARD_SUSPENDED", wallet["balance"]

            if wallet["balance"] < amount:
                return False, "INSUFFICIENT_FUNDS", wallet["balance"]

            new_balance = round(wallet["balance"] - amount, 2)
            cursor.execute(
                "UPDATE wallets SET balance = ?, updated_at = ? WHERE token_uuid = ?",
                (new_balance, now, token_uuid),
            )
            cursor.execute(
                """
                INSERT INTO transaction_ledger 
                (token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp)
                VALUES (?, ?, 'STALL_POS', 'PAY', ?, ?, ?)
                """,
                (token_uuid, card_uid, amount, new_balance, now),
            )
            conn.commit()
            return True, "SUCCESS", new_balance
        except Exception as exc:
            conn.rollback()
            return False, f"TX_ERROR: {exc}", 0.0


def get_recent_transactions(limit: int = 15) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT transaction_id, token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp
            FROM transaction_ledger
            ORDER BY transaction_id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]