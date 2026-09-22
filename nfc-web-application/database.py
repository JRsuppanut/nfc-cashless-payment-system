"""
Database connection module for the Web Application.
Focuses on read-only operations for the Customer Portal.
"""

import psycopg2
from psycopg2.extras import DictCursor
from typing import Any, Dict, List, Optional

# Database Configuration 
DB_CONFIG = {
    "dbname": "foodcourt_db",
    "user": "postgres",
    "password": "////",
    "host": "10.59.30.226",
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

def get_recent_transactions(limit: int = 10, token_uuid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve recent transactions and include order details for PAY actions."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            if token_uuid:
                cursor.execute("""
                    SELECT 
                        t.transaction_id, 
                        t.terminal_type, 
                        t.action_type, 
                        t.amount, 
                        t.balance_after, 
                        t.timestamp,
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'product_name', oi.product_name,
                                    'quantity', oi.quantity,
                                    'item_total', oi.item_total
                                )
                            )
                            FROM orders o
                            JOIN order_items oi ON o.order_id = oi.order_id
                            WHERE o.token_uuid = t.token_uuid
                              AND o.created_at >= t.timestamp - interval '5 seconds'
                              AND o.created_at <= t.timestamp + interval '5 seconds'
                        ) AS order_list
                    FROM transaction_ledger t
                    WHERE t.token_uuid = %s
                    ORDER BY t.transaction_id DESC
                    LIMIT %s
                """, (token_uuid, limit))
                return [dict(row) for row in cursor.fetchall()]
            return []