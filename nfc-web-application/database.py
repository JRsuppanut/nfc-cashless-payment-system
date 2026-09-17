"""
Database connection module for the Web Application.
Focuses on read-only operations for the Customer Portal.
"""

import psycopg2
from psycopg2.extras import DictCursor
from typing import Any, Dict, List, Optional

# Database Configuration (Must match the desktop application)
DB_CONFIG = {
    "dbname": "foodcourt_db",
    "user": "postgres",
    "password": "////",  # Replace with actual password
    "host": "127.0.0.1",
    "port": "5432"
}

def get_connection():
    """Establish a connection to the PostgreSQL database."""
    return psycopg2.connect(**DB_CONFIG)

def get_wallet_by_token(token_uuid: str) -> Optional[Dict[str, Any]]:
    """Retrieve wallet details using the token UUID."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM wallets WHERE token_uuid = %s",
                (token_uuid,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

def get_recent_transactions(limit: int = 10, card_uid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve recent transactions for a specific card UID."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            if card_uid:
                cursor.execute("""
                    SELECT transaction_id, terminal_type, action_type, amount, balance_after, timestamp
                    FROM transaction_ledger
                    WHERE card_uid = %s
                    ORDER BY transaction_id DESC
                    LIMIT %s
                """, (card_uid, limit))
                return [dict(row) for row in cursor.fetchall()]
            return []