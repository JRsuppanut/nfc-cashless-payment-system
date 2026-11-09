"""Read PostgreSQL data for the Customer Wallet and balance kiosk."""

import os
from contextlib import closing
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import DictCursor


# Point the web app to the same PostgreSQL database as Cashier and Stall.
# Keep the password in the local environment so it stays out of source control.
DB_CONFIG = {
    "dbname": os.getenv("FOODCOURT_DB_NAME", "foodcourt_db"),
    "user": os.getenv("FOODCOURT_DB_USER", "postgres"),
    "password": os.getenv("FOODCOURT_DB_PASSWORD", ""),
    "host": os.getenv("FOODCOURT_DB_HOST", "192.168.1.59"),
    "port": os.getenv("FOODCOURT_DB_PORT", "5432"),
}


def get_connection():
    """Establish a connection to the PostgreSQL database."""
    return psycopg2.connect(**DB_CONFIG)


def get_wallet_by_token(token_uuid: str) -> Optional[Dict[str, Any]]:
    """Retrieve wallet details using the token UUID."""
    with closing(get_connection()) as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT * FROM wallets WHERE token_uuid = %s", (token_uuid,))
            row = cursor.fetchone()
            return dict(row) if row else None


def get_recent_transactions(limit: int = 10, token_uuid: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read recent ledger rows and attach the food items for each purchase."""
    if not token_uuid:
        return []

    with closing(get_connection()) as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            # Older ledgers may not have the new columns until Stall starts.
            cursor.execute("""
                SELECT t.transaction_id, t.terminal_type, t.action_type,
                    t.amount, t.balance_after, t.timestamp,
                    to_jsonb(t)->>'terminal_id' AS terminal_id,
                    to_jsonb(t)->>'stall_order_id' AS stall_order_id
                FROM transaction_ledger t
                WHERE t.token_uuid=%s
                ORDER BY t.transaction_id DESC LIMIT %s
            """, (token_uuid, limit))
            transactions = [dict(row) for row in cursor.fetchall()]
            attach_order_items(cursor, token_uuid, transactions)
            return transactions


def attach_order_items(cursor, token, transactions):
    purchases = [tx for tx in transactions if tx["action_type"] == "PAY"]
    linked_ids = {tx["stall_order_id"] for tx in purchases if tx["stall_order_id"]}

    if linked_ids:
        # Use the exact order ID recorded by Stall at the time of payment.
        cursor.execute("""
            SELECT o.id, o.items, s.stall_name
            FROM stall_ui_orders o LEFT JOIN stalls s USING (stall_id)
            WHERE o.id=ANY(%s)
        """, (list(linked_ids),))
        orders = {row["id"]: row for row in cursor.fetchall()}

        for tx in purchases:
            order = orders.get(tx["stall_order_id"])
            if order is None:
                continue
            tx["stall_name"] = order["stall_name"]
            tx["order_list"] = [
                {
                    "product_name": item["name"],
                    "quantity": item["qty"],
                    "item_total": Decimal(str(item["price"])) * item["qty"],
                }
                for item in order["items"]
            ]

    old_purchases = [tx for tx in purchases if not tx["stall_order_id"]]
    if not old_purchases:
        return

    cursor.execute("""
        SELECT to_regclass('orders') IS NOT NULL
            AND to_regclass('order_items') IS NOT NULL AS available
    """)
    if not cursor.fetchone()["available"]:
        return

    # Match legacy orders only when the timestamp, amount and store agree.
    cursor.execute("""
        SELECT o.created_at, o.total_amount, o.stall_id, s.stall_name,
            json_agg(json_build_object(
                'product_name', i.product_name, 'quantity', i.quantity,
                'item_total', i.item_total
            ) ORDER BY i.order_item_id) AS items
        FROM orders o JOIN order_items i USING (order_id)
        LEFT JOIN stalls s ON s.stall_id=o.stall_id
        WHERE o.token_uuid=%s AND o.created_at=ANY(%s)
        GROUP BY o.order_id, s.stall_name
    """, (token, [tx["timestamp"] for tx in old_purchases]))
    orders = cursor.fetchall()

    for tx in old_purchases:
        matches = [
            order for order in orders
            if order["created_at"] == tx["timestamp"]
            and order["total_amount"] == tx["amount"]
            and order["stall_id"] == tx["terminal_type"]
        ]
        if len(matches) == 1:
            tx["stall_name"] = matches[0]["stall_name"]
            tx["order_list"] = matches[0]["items"]


def get_kiosk_balance(uid: str) -> Optional[Decimal]:
    """Find the current balance of an active card by its compact UID."""
    # Existing records may store the UID with or without colon separators.
    canonical = ":".join(uid[i:i + 2] for i in range(0, len(uid), 2))
    with closing(get_connection()) as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT balance FROM wallets
                WHERE card_uid IN (%s, %s) AND status='ACTIVE'
                ORDER BY created_at DESC LIMIT 1
            """, (canonical, uid))
            row = cursor.fetchone()
    return row[0] if row else None