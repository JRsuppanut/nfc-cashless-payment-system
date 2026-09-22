"""
PostgreSQL Database Manager for Food Court System
Replaces SQLite to support concurrency and distributed terminal connections.
"""

import datetime
import psycopg2
from psycopg2.extras import DictCursor
from typing import Any, Dict, List, Optional, Tuple

# ==========================================
# DATABASE CONFIGURATION
# ==========================================
DB_CONFIG = {
    "dbname": "foodcourt_db",
    "user": "postgres",
    "password": "////",  # IMPORTANT: Change this to your PostgreSQL password
    "host": "10.59.30.226",
    "port": "5432"
}

def get_connection():
    """Establish a connection to the PostgreSQL database."""
    conn = psycopg2.connect(**DB_CONFIG)
    return conn

def initialize_database() -> None:
    """Create all required tables using PostgreSQL syntax."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            # 1. Wallets
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    token_uuid TEXT PRIMARY KEY,
                    card_uid TEXT NOT NULL,
                    balance NUMERIC(10, 2) NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            
            # 2. Transaction Ledger
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transaction_ledger (
                    transaction_id SERIAL PRIMARY KEY,
                    token_uuid TEXT NOT NULL REFERENCES wallets (token_uuid),
                    card_uid TEXT NOT NULL,
                    terminal_type TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    amount NUMERIC(10, 2) NOT NULL,
                    balance_after NUMERIC(10, 2) NOT NULL,
                    timestamp TIMESTAMP NOT NULL
                )
            """)
            
            # 3. Stalls
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stalls (
                    stall_id TEXT PRIMARY KEY,
                    stall_name TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            
            # 4. Products
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    product_id SERIAL PRIMARY KEY,
                    stall_id TEXT NOT NULL REFERENCES stalls (stall_id),
                    product_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
                    is_available INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    UNIQUE (stall_id, product_name)
                )
            """)
            
            # 5. Orders
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id SERIAL PRIMARY KEY,
                    stall_id TEXT NOT NULL REFERENCES stalls (stall_id),
                    token_uuid TEXT NOT NULL REFERENCES wallets (token_uuid),
                    card_uid TEXT NOT NULL,
                    total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0),
                    balance_after NUMERIC(10, 2) NOT NULL,
                    payment_status TEXT NOT NULL DEFAULT 'PAID',
                    created_at TIMESTAMP NOT NULL
                )
            """)
            
            # 6. Order Items
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_items (
                    order_item_id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
                    product_id INTEGER REFERENCES products (product_id),
                    product_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
                    item_total NUMERIC(10, 2) NOT NULL CHECK (item_total >= 0),
                    item_note TEXT NOT NULL DEFAULT ''
                )
            """)
            
            # 7. Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_stall ON products (stall_id, is_available)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_stall_time ON orders (stall_id, created_at)")
            
            # 8. Demo Stall
            cursor.execute("""
                INSERT INTO stalls (stall_id, stall_name, is_active, created_at, updated_at)
                VALUES ('STALL-01', 'Demo Food Stall', 1, %s, %s)
                ON CONFLICT(stall_id) DO NOTHING
            """, (now, now))

            # 9. Starter Products
            cursor.execute("SELECT COUNT(*) FROM products WHERE stall_id = 'STALL-01'")
            if cursor.fetchone()[0] == 0:
                starter_products = [
                    ("Chicken Rice", "Rice", 50.0),
                    ("Pork Rice", "Rice", 55.0),
                    ("Noodle Soup", "Noodles", 45.0),
                    ("Iced Tea", "Drinks", 25.0),
                ]
                cursor.executemany("""
                    INSERT INTO products
                        (stall_id, product_name, category, price, is_available, created_at, updated_at)
                    VALUES ('STALL-01', %s, %s, %s, 1, %s, %s)
                """, [(name, category, price, now, now) for name, category, price in starter_products])
                
        conn.commit()


# ==========================================
# CARD AND WALLET OPERATIONS
# ==========================================

def get_wallet_by_token(token_uuid: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT * FROM wallets WHERE token_uuid = %s", (token_uuid,))
            row = cursor.fetchone()
            return dict(row) if row else None

def register_provisioned_card(token_uuid: str, card_uid: str) -> bool:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO wallets
                    (token_uuid, card_uid, balance, status, created_at, updated_at)
                VALUES (%s, %s, 0.0, 'ACTIVE', %s, %s)
                ON CONFLICT(token_uuid) DO NOTHING
            """, (token_uuid, card_uid, now, now))
        conn.commit()
    return True

def process_top_up(token_uuid: str, card_uid: str, amount: float) -> Tuple[bool, str, float]:
    if amount <= 0:
        return False, "INVALID_AMOUNT", 0.0

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                # Row-Level Locking
                cursor.execute(
                    "SELECT balance, status FROM wallets WHERE token_uuid = %s FOR UPDATE",
                    (token_uuid,)
                )
                wallet = cursor.fetchone()
                
                if wallet is None:
                    conn.rollback()
                    return False, "WALLET_NOT_FOUND", 0.0
                if wallet["status"] != "ACTIVE":
                    conn.rollback()
                    return False, "WALLET_SUSPENDED", float(wallet["balance"])

                new_balance = round(float(wallet["balance"]) + float(amount), 2)
                
                cursor.execute(
                    "UPDATE wallets SET balance = %s, updated_at = %s WHERE token_uuid = %s",
                    (new_balance, now, token_uuid)
                )
                
                cursor.execute("""
                    INSERT INTO transaction_ledger
                        (token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp)
                    VALUES (%s, %s, 'CASHIER', 'TOP_UP', %s, %s, %s)
                """, (token_uuid, card_uid, round(float(amount), 2), new_balance, now))
                
                conn.commit()
                return True, "SUCCESS", new_balance
            except Exception as exc:
                conn.rollback()
                return False, f"TX_ERROR: {exc}", 0.0

def process_card_return(token_uuid: str, card_uid: str) -> Tuple[bool, str, float]:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute(
                    "SELECT balance, status FROM wallets WHERE token_uuid = %s FOR UPDATE",
                    (token_uuid,)
                )
                wallet = cursor.fetchone()
                
                if wallet is None:
                    conn.rollback()
                    return False, "WALLET_NOT_FOUND", 0.0
                if wallet["status"] != "ACTIVE":
                    conn.rollback()
                    return False, "CARD_NOT_ACTIVE", float(wallet["balance"])

                refund_amount = round(float(wallet["balance"]), 2)
                
                cursor.execute("""
                    UPDATE wallets
                    SET balance = 0.0, status = 'AVAILABLE', updated_at = %s
                    WHERE token_uuid = %s
                """, (now, token_uuid))
                
                cursor.execute("""
                    INSERT INTO transaction_ledger
                        (token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp)
                    VALUES (%s, %s, 'CASHIER', 'REFUND_RETURN', %s, 0.0, %s)
                """, (token_uuid, card_uid, refund_amount, now))
                
                conn.commit()
                return True, "SUCCESS", refund_amount
            except Exception as exc:
                conn.rollback()
                return False, f"TX_ERROR: {exc}", 0.0

def process_deduction(token_uuid: str, card_uid: str, amount: float) -> Tuple[bool, str, float]:
    """Original simple deduction function, retained for compatibility."""
    if amount <= 0:
        return False, "INVALID_AMOUNT", 0.0

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                cursor.execute(
                    "SELECT balance, status FROM wallets WHERE token_uuid = %s FOR UPDATE",
                    (token_uuid,)
                )
                wallet = cursor.fetchone()
                
                if wallet is None:
                    conn.rollback()
                    return False, "UNREGISTERED_TOKEN", 0.0
                if wallet["status"] != "ACTIVE":
                    conn.rollback()
                    return False, "CARD_SUSPENDED", float(wallet["balance"])
                if float(wallet["balance"]) < float(amount):
                    conn.rollback()
                    return False, "INSUFFICIENT_FUNDS", float(wallet["balance"])

                new_balance = round(float(wallet["balance"]) - float(amount), 2)
                
                cursor.execute(
                    "UPDATE wallets SET balance = %s, updated_at = %s WHERE token_uuid = %s",
                    (new_balance, now, token_uuid)
                )
                
                cursor.execute("""
                    INSERT INTO transaction_ledger
                        (token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp)
                    VALUES (%s, %s, 'STALL_POS', 'PAY', %s, %s, %s)
                """, (token_uuid, card_uid, round(float(amount), 2), new_balance, now))
                
                conn.commit()
                return True, "SUCCESS", new_balance
            except Exception as exc:
                conn.rollback()
                return False, f"TX_ERROR: {exc}", 0.0

def get_recent_transactions(limit: int = 15, card_uid: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            if card_uid:
                # Filter specific card transactions
                cursor.execute("""
                    SELECT transaction_id, token_uuid, card_uid, terminal_type,
                           action_type, amount, balance_after, timestamp
                    FROM transaction_ledger
                    WHERE card_uid = %s
                    ORDER BY transaction_id DESC
                    LIMIT %s
                """, (card_uid, limit))
            else:
                # Get general recent transactions
                cursor.execute("""
                    SELECT transaction_id, token_uuid, card_uid, terminal_type,
                           action_type, amount, balance_after, timestamp
                    FROM transaction_ledger
                    ORDER BY transaction_id DESC
                    LIMIT %s
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

# ==========================================
# STALL AND MENU MANAGEMENT
# ==========================================

def get_stall(stall_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT * FROM stalls WHERE stall_id = %s", (stall_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

def update_stall_name(stall_id: str, stall_name: str) -> Tuple[bool, str]:
    stall_name = stall_name.strip()
    if not stall_name:
        return False, "STALL_NAME_REQUIRED"
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE stalls SET stall_name = %s, updated_at = %s WHERE stall_id = %s
                """, (stall_name, now, stall_id))
                if cursor.rowcount == 0:
                    return False, "STALL_NOT_FOUND"
            conn.commit()
        return True, "SUCCESS"
    except Exception as exc:
        return False, f"DB_ERROR: {exc}"

def get_products(stall_id: str, include_unavailable: bool = False) -> List[Dict[str, Any]]:
    sql = """
        SELECT product_id, stall_id, product_name, category, price, is_available
        FROM products
        WHERE stall_id = %s
    """
    params: List[Any] = [stall_id]
    if not include_unavailable:
        sql += " AND is_available = 1"
    
    # PostgreSQL requires specific collation or simple ordering
    sql += " ORDER BY category, product_name"
    
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

def add_product(
    stall_id: str,
    product_name: str,
    category: str,
    price: float,
    is_available: bool = True,
) -> Tuple[bool, str, Optional[int]]:
    product_name = product_name.strip()
    category = category.strip() or "Other"
    if not product_name:
        return False, "PRODUCT_NAME_REQUIRED", None
    if price < 0:
        return False, "INVALID_PRICE", None

    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO products
                        (stall_id, product_name, category, price, is_available, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING product_id
                """, (
                    stall_id, product_name, category, round(float(price), 2),
                    1 if is_available else 0, now, now
                ))
                product_id = int(cursor.fetchone()[0])
            conn.commit()
        return True, "SUCCESS", product_id
    except psycopg2.IntegrityError:
        return False, "DUPLICATE_PRODUCT_NAME", None
    except Exception as exc:
        return False, f"DB_ERROR: {exc}", None

def update_product(
    product_id: int,
    stall_id: str,
    product_name: str,
    category: str,
    price: float,
    is_available: bool,
) -> Tuple[bool, str]:
    product_name = product_name.strip()
    category = category.strip() or "Other"
    if not product_name:
        return False, "PRODUCT_NAME_REQUIRED"
    if price < 0:
        return False, "INVALID_PRICE"

    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE products
                    SET product_name = %s, category = %s, price = %s,
                        is_available = %s, updated_at = %s
                    WHERE product_id = %s AND stall_id = %s
                """, (
                    product_name, category, round(float(price), 2),
                    1 if is_available else 0, now, product_id, stall_id
                ))
                if cursor.rowcount == 0:
                    return False, "PRODUCT_NOT_FOUND"
            conn.commit()
        return True, "SUCCESS"
    except psycopg2.IntegrityError:
        return False, "DUPLICATE_PRODUCT_NAME"
    except Exception as exc:
        return False, f"DB_ERROR: {exc}"

def delete_product(product_id: int, stall_id: str) -> Tuple[bool, str]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM order_items WHERE product_id = %s LIMIT 1", (product_id,))
                used = cursor.fetchone()
                
                if used:
                    now = datetime.datetime.now().isoformat(timespec="seconds")
                    cursor.execute("""
                        UPDATE products SET is_available = 0, updated_at = %s
                        WHERE product_id = %s AND stall_id = %s
                    """, (now, product_id, stall_id))
                    conn.commit()
                    return True, "MARKED_UNAVAILABLE"

                cursor.execute("DELETE FROM products WHERE product_id = %s AND stall_id = %s", (product_id, stall_id))
                if cursor.rowcount == 0:
                    return False, "PRODUCT_NOT_FOUND"
            conn.commit()
        return True, "DELETED"
    except Exception as exc:
        return False, f"DB_ERROR: {exc}"

# ==========================================
# ATOMIC ORDER PAYMENT
# ==========================================

def process_order_payment(
    token_uuid: str,
    card_uid: str,
    stall_id: str,
    cart_items: List[Dict[str, Any]],
) -> Tuple[bool, str, float, Optional[int], float]:
    if not cart_items:
        return False, "EMPTY_ORDER", 0.0, None, 0.0

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            try:
                # Row-Level Locking
                cursor.execute(
                    "SELECT balance, status FROM wallets WHERE token_uuid = %s FOR UPDATE",
                    (token_uuid,)
                )
                wallet = cursor.fetchone()
                
                if wallet is None:
                    conn.rollback()
                    return False, "UNREGISTERED_TOKEN", 0.0, None, 0.0
                if wallet["status"] != "ACTIVE":
                    conn.rollback()
                    return False, "CARD_SUSPENDED", float(wallet["balance"]), None, 0.0

                normalized_items: List[Dict[str, Any]] = []
                total_amount = 0.0
                
                for item in cart_items:
                    try:
                        product_id = int(item["product_id"])
                        quantity = int(item["quantity"])
                    except (KeyError, TypeError, ValueError):
                        conn.rollback()
                        return False, "INVALID_ORDER_ITEM", float(wallet["balance"]), None, 0.0
                    
                    if quantity <= 0:
                        conn.rollback()
                        return False, "INVALID_QUANTITY", float(wallet["balance"]), None, 0.0

                    cursor.execute("""
                        SELECT product_id, product_name, price, is_available
                        FROM products
                        WHERE product_id = %s AND stall_id = %s
                    """, (product_id, stall_id))
                    product = cursor.fetchone()
                    
                    if product is None:
                        conn.rollback()
                        return False, "PRODUCT_NOT_FOUND", float(wallet["balance"]), None, 0.0
                    if int(product["is_available"]) != 1:
                        conn.rollback()
                        return False, "PRODUCT_UNAVAILABLE", float(wallet["balance"]), None, 0.0

                    unit_price = round(float(product["price"]), 2)
                    item_total = round(unit_price * quantity, 2)
                    note = str(item.get("note", "")).strip()[:250]
                    
                    normalized_items.append({
                        "product_id": product_id,
                        "product_name": str(product["product_name"]),
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "item_total": item_total,
                        "note": note,
                    })
                    total_amount = round(total_amount + item_total, 2)

                current_balance = round(float(wallet["balance"]), 2)
                if current_balance < total_amount:
                    conn.rollback()
                    return False, "INSUFFICIENT_FUNDS", current_balance, None, total_amount

                new_balance = round(current_balance - total_amount, 2)
                
                cursor.execute(
                    "UPDATE wallets SET balance = %s, updated_at = %s WHERE token_uuid = %s",
                    (new_balance, now, token_uuid)
                )
                
                cursor.execute("""
                    INSERT INTO transaction_ledger
                        (token_uuid, card_uid, terminal_type, action_type, amount, balance_after, timestamp)
                    VALUES (%s, %s, %s, 'PAY', %s, %s, %s)
                """, (token_uuid, card_uid, stall_id, total_amount, new_balance, now))
                
                # Insert order and return the auto-generated order_id
                cursor.execute("""
                    INSERT INTO orders
                        (stall_id, token_uuid, card_uid, total_amount, balance_after, payment_status, created_at)
                    VALUES (%s, %s, %s, %s, %s, 'PAID', %s)
                    RETURNING order_id
                """, (stall_id, token_uuid, card_uid, total_amount, new_balance, now))
                order_id = int(cursor.fetchone()[0])

                cursor.executemany("""
                    INSERT INTO order_items
                        (order_id, product_id, product_name, quantity, unit_price, item_total, item_note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [
                    (
                        order_id,
                        item["product_id"],
                        item["product_name"],
                        item["quantity"],
                        item["unit_price"],
                        item["item_total"],
                        item["note"],
                    )
                    for item in normalized_items
                ])
                
                conn.commit()
                return True, "SUCCESS", new_balance, order_id, total_amount
            except Exception as exc:
                conn.rollback()
                return False, f"TX_ERROR: {exc}", 0.0, None, 0.0

def get_order_receipt(order_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT o.*, s.stall_name
                FROM orders AS o
                JOIN stalls AS s ON s.stall_id = o.stall_id
                WHERE o.order_id = %s
            """, (order_id,))
            order = cursor.fetchone()
            
            if order is None:
                return None
                
            cursor.execute("""
                SELECT product_name, quantity, unit_price, item_total, item_note
                FROM order_items
                WHERE order_id = %s
                ORDER BY order_item_id
            """, (order_id,))
            items = cursor.fetchall()
            
            result = dict(order)
            result["items"] = [dict(item) for item in items]
            return result

def get_recent_stall_orders(stall_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT order_id, total_amount, balance_after, payment_status, created_at
                FROM orders
                WHERE stall_id = %s
                ORDER BY order_id DESC
                LIMIT %s
            """, (stall_id, limit))
            return [dict(row) for row in cursor.fetchall()]