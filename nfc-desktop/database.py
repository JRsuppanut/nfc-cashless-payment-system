import sqlite3
from typing import Optional, Tuple, List, Dict, Any

DATABASE_FILE = "foodcourt.db"

def get_connection() -> sqlite3.Connection:
    """Establish and return a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database() -> None:
    """Create necessary database tables if they do not exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Wallets table: Stores balance referenced by Tag UID
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                card_uid TEXT PRIMARY KEY,
                balance REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Transactions ledger: Audit log for financial movements
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_uid TEXT NOT NULL,
                action_type TEXT NOT NULL,
                amount REAL NOT NULL,
                balance_after REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (card_uid) REFERENCES wallets(card_uid)
            );
        """)
        conn.commit()

def get_wallet(card_uid: str) -> Optional[sqlite3.Row]:
    """Retrieve wallet information by card UID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallets WHERE card_uid = ?", (card_uid,))
        return cursor.fetchone()

def register_card_if_absent(card_uid: str) -> None:
    """Register a new card with zero initial balance if not existing."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO wallets (card_uid, balance)
            VALUES (?, 0.0)
        """, (card_uid,))
        conn.commit()

def process_top_up(card_uid: str, amount: float) -> Tuple[bool, str, float]:
    """
    Deposit funds into a card wallet within an atomic transaction.
    Returns: (Success status, Message, Updated balance)
    """
    if amount <= 0:
        return False, "Top-up amount must be greater than zero.", 0.0

    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            # Ensure card exists in the registry
            cursor.execute("""
                INSERT OR IGNORE INTO wallets (card_uid, balance)
                VALUES (?, 0.0)
            """, (card_uid,))
            
            # Fetch current balance
            cursor.execute("SELECT balance FROM wallets WHERE card_uid = ?", (card_uid,))
            current_balance = cursor.fetchone()["balance"]
            
            new_balance = current_balance + amount
            
            # Update balance
            cursor.execute("""
                UPDATE wallets
                SET balance = ?, updated_at = CURRENT_TIMESTAMP
                WHERE card_uid = ?
            """, (new_balance, card_uid))
            
            # Insert audit ledger record
            cursor.execute("""
                INSERT INTO transactions (card_uid, action_type, amount, balance_after)
                VALUES (?, 'TOP_UP', ?, ?)
            """, (card_uid, amount, new_balance))
            
            conn.commit()
            return True, "Top-up successful.", new_balance
        except Exception as err:
            conn.rollback()
            return False, f"Transaction error: {err}", 0.0

def process_deduction(card_uid: str, amount: float) -> Tuple[bool, str, float]:
    """
    Deduct funds from a card wallet within an atomic transaction.
    Returns: (Success status, Message, Updated balance)
    """
    if amount <= 0:
        return False, "Deduction amount must be greater than zero.", 0.0

    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT balance FROM wallets WHERE card_uid = ?", (card_uid,))
            row = cursor.fetchone()
            
            if row is None:
                return False, "Card not registered in the system.", 0.0
            
            current_balance = row["balance"]
            if current_balance < amount:
                return False, f"Insufficient funds. Balance: {current_balance:.2f} THB", current_balance
            
            new_balance = current_balance - amount
            
            # Update balance
            cursor.execute("""
                UPDATE wallets
                SET balance = ?, updated_at = CURRENT_TIMESTAMP
                WHERE card_uid = ?
            """, (new_balance, card_uid))
            
            # Insert audit ledger record
            cursor.execute("""
                INSERT INTO transactions (card_uid, action_type, amount, balance_after)
                VALUES (?, 'PAYMENT', ?, ?)
            """, (card_uid, amount, new_balance))
            
            conn.commit()
            return True, "Payment accepted.", new_balance
        except Exception as err:
            conn.rollback()
            return False, f"Transaction error: {err}", 0.0

def get_recent_transactions(limit: int = 10) -> List[sqlite3.Row]:
    """Fetch recent transaction records for audit monitoring."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT transaction_id, card_uid, action_type, amount, balance_after, timestamp
            FROM transactions
            ORDER BY transaction_id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()