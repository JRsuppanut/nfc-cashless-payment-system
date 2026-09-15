import datetime
import sqlite3
from typing import Any, Dict, List, Optional, Tuple


DATABASE_FILE = "foodcourt_ledger.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database() -> None:
    """Create the original wallet tables plus stall, menu, and order tables."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stalls (
                stall_id TEXT PRIMARY KEY,
                stall_name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                stall_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL CHECK (price >= 0),
                is_available INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                FOREIGN KEY (stall_id) REFERENCES stalls (stall_id),
                UNIQUE (stall_id, product_name)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                stall_id TEXT NOT NULL,
                token_uuid TEXT NOT NULL,
                card_uid TEXT NOT NULL,
                total_amount REAL NOT NULL CHECK (total_amount >= 0),
                balance_after REAL NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'PAID',
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (stall_id) REFERENCES stalls (stall_id),
                FOREIGN KEY (token_uuid) REFERENCES wallets (token_uuid)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS order_items (
                order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price REAL NOT NULL CHECK (unit_price >= 0),
                item_total REAL NOT NULL CHECK (item_total >= 0),
                item_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (order_id) REFERENCES orders (order_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products (product_id)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_products_stall ON products (stall_id, is_available)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_stall_time ON orders (stall_id, created_at)"
        )
        cursor.execute(
            """
            INSERT INTO stalls (stall_id, stall_name, is_active, created_at, updated_at)
            VALUES ('STALL-01', 'Demo Food Stall', 1, ?, ?)
            ON CONFLICT(stall_id) DO NOTHING
            """,
            (now, now),
        )

        cursor.execute("SELECT COUNT(*) AS total FROM products WHERE stall_id = 'STALL-01'")
        if int(cursor.fetchone()["total"]) == 0:
            starter_products = [
                ("Chicken Rice", "Rice", 50.0),
                ("Pork Rice", "Rice", 55.0),
                ("Noodle Soup", "Noodles", 45.0),
                ("Iced Tea", "Drinks", 25.0),
            ]
            cursor.executemany(
                """
                INSERT INTO products
                    (stall_id, product_name, category, price, is_available, created_at, updated_at)
                VALUES ('STALL-01', ?, ?, ?, 1, ?, ?)
                """,
                [(name, category, price, now, now) for name, category, price in starter_products],
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Existing card and wallet functions (kept compatible with Cashier App)
# ---------------------------------------------------------------------------


def get_wallet_by_token(token_uuid: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wallets WHERE token_uuid = ?", (token_uuid,)
        ).fetchone()
        return dict(row) if row else None


def register_provisioned_card(token_uuid: str, card_uid: str) -> bool:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO wallets
                (token_uuid, card_uid, balance, status, created_at, updated_at)
            VALUES (?, ?, 0.0, 'ACTIVE', ?, ?)
            ON CONFLICT(token_uuid) DO NOTHING
            """,
            (token_uuid, card_uid, now, now),
        )
        conn.commit()
    return True


def process_top_up(
    token_uuid: str, card_uid: str, amount: float
) -> Tuple[bool, str, float]:
    if amount <= 0:
        return False, "INVALID_AMOUNT", 0.0

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            wallet = cursor.execute(
                "SELECT balance, status FROM wallets WHERE token_uuid = ?",
                (token_uuid,),
            ).fetchone()
            if wallet is None:
                conn.rollback()
                return False, "WALLET_NOT_FOUND", 0.0
            if wallet["status"] != "ACTIVE":
                conn.rollback()
                return False, "WALLET_SUSPENDED", float(wallet["balance"])

            new_balance = round(float(wallet["balance"]) + float(amount), 2)
            cursor.execute(
                "UPDATE wallets SET balance = ?, updated_at = ? WHERE token_uuid = ?",
                (new_balance, now, token_uuid),
            )
            cursor.execute(
                """
                INSERT INTO transaction_ledger
                    (token_uuid, card_uid, terminal_type, action_type,
                     amount, balance_after, timestamp)
                VALUES (?, ?, 'CASHIER', 'TOP_UP', ?, ?, ?)
                """,
                (token_uuid, card_uid, round(float(amount), 2), new_balance, now),
            )
            conn.commit()
            return True, "SUCCESS", new_balance
        except Exception as exc:
            conn.rollback()
            return False, f"TX_ERROR: {exc}", 0.0


def process_card_return(
    token_uuid: str, card_uid: str
) -> Tuple[bool, str, float]:
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            wallet = cursor.execute(
                "SELECT balance, status FROM wallets WHERE token_uuid = ?",
                (token_uuid,),
            ).fetchone()
            if wallet is None:
                conn.rollback()
                return False, "WALLET_NOT_FOUND", 0.0
            if wallet["status"] != "ACTIVE":
                conn.rollback()
                return False, "CARD_NOT_ACTIVE", float(wallet["balance"])

            refund_amount = round(float(wallet["balance"]), 2)
            cursor.execute(
                """
                UPDATE wallets
                SET balance = 0.0, status = 'AVAILABLE', updated_at = ?
                WHERE token_uuid = ?
                """,
                (now, token_uuid),
            )
            cursor.execute(
                """
                INSERT INTO transaction_ledger
                    (token_uuid, card_uid, terminal_type, action_type,
                     amount, balance_after, timestamp)
                VALUES (?, ?, 'CASHIER', 'REFUND_RETURN', ?, 0.0, ?)
                """,
                (token_uuid, card_uid, refund_amount, now),
            )
            conn.commit()
            return True, "SUCCESS", refund_amount
        except Exception as exc:
            conn.rollback()
            return False, f"TX_ERROR: {exc}", 0.0


def process_deduction(
    token_uuid: str, card_uid: str, amount: float
) -> Tuple[bool, str, float]:
    """Original simple deduction function, retained for compatibility."""
    if amount <= 0:
        return False, "INVALID_AMOUNT", 0.0

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            wallet = cursor.execute(
                "SELECT balance, status FROM wallets WHERE token_uuid = ?",
                (token_uuid,),
            ).fetchone()
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
                "UPDATE wallets SET balance = ?, updated_at = ? WHERE token_uuid = ?",
                (new_balance, now, token_uuid),
            )
            cursor.execute(
                """
                INSERT INTO transaction_ledger
                    (token_uuid, card_uid, terminal_type, action_type,
                     amount, balance_after, timestamp)
                VALUES (?, ?, 'STALL_POS', 'PAY', ?, ?, ?)
                """,
                (token_uuid, card_uid, round(float(amount), 2), new_balance, now),
            )
            conn.commit()
            return True, "SUCCESS", new_balance
        except Exception as exc:
            conn.rollback()
            return False, f"TX_ERROR: {exc}", 0.0


def get_recent_transactions(limit: int = 15) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT transaction_id, token_uuid, card_uid, terminal_type,
                   action_type, amount, balance_after, timestamp
            FROM transaction_ledger
            ORDER BY transaction_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Stall and menu management
# ---------------------------------------------------------------------------


def get_stall(stall_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM stalls WHERE stall_id = ?", (stall_id,)
        ).fetchone()
        return dict(row) if row else None


def update_stall_name(stall_id: str, stall_name: str) -> Tuple[bool, str]:
    stall_name = stall_name.strip()
    if not stall_name:
        return False, "STALL_NAME_REQUIRED"
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE stalls SET stall_name = ?, updated_at = ? WHERE stall_id = ?
                """,
                (stall_name, now, stall_id),
            )
            if cursor.rowcount == 0:
                return False, "STALL_NOT_FOUND"
            conn.commit()
        return True, "SUCCESS"
    except Exception as exc:
        return False, f"DB_ERROR: {exc}"


def get_products(
    stall_id: str, include_unavailable: bool = False
) -> List[Dict[str, Any]]:
    sql = """
        SELECT product_id, stall_id, product_name, category, price, is_available
        FROM products
        WHERE stall_id = ?
    """
    params: List[Any] = [stall_id]
    if not include_unavailable:
        sql += " AND is_available = 1"
    sql += " ORDER BY category COLLATE NOCASE, product_name COLLATE NOCASE"
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


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
            cursor = conn.execute(
                """
                INSERT INTO products
                    (stall_id, product_name, category, price, is_available,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stall_id,
                    product_name,
                    category,
                    round(float(price), 2),
                    1 if is_available else 0,
                    now,
                    now,
                ),
            )
            product_id = int(cursor.lastrowid)
            conn.commit()
        return True, "SUCCESS", product_id
    except sqlite3.IntegrityError:
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
            cursor = conn.execute(
                """
                UPDATE products
                SET product_name = ?, category = ?, price = ?,
                    is_available = ?, updated_at = ?
                WHERE product_id = ? AND stall_id = ?
                """,
                (
                    product_name,
                    category,
                    round(float(price), 2),
                    1 if is_available else 0,
                    now,
                    product_id,
                    stall_id,
                ),
            )
            if cursor.rowcount == 0:
                return False, "PRODUCT_NOT_FOUND"
            conn.commit()
        return True, "SUCCESS"
    except sqlite3.IntegrityError:
        return False, "DUPLICATE_PRODUCT_NAME"
    except Exception as exc:
        return False, f"DB_ERROR: {exc}"


def delete_product(product_id: int, stall_id: str) -> Tuple[bool, str]:
    """Delete only when unused; otherwise mark unavailable to preserve receipts."""
    try:
        with get_connection() as conn:
            used = conn.execute(
                "SELECT 1 FROM order_items WHERE product_id = ? LIMIT 1",
                (product_id,),
            ).fetchone()
            if used:
                conn.execute(
                    """
                    UPDATE products SET is_available = 0, updated_at = ?
                    WHERE product_id = ? AND stall_id = ?
                    """,
                    (
                        datetime.datetime.now().isoformat(timespec="seconds"),
                        product_id,
                        stall_id,
                    ),
                )
                conn.commit()
                return True, "MARKED_UNAVAILABLE"

            cursor = conn.execute(
                "DELETE FROM products WHERE product_id = ? AND stall_id = ?",
                (product_id, stall_id),
            )
            if cursor.rowcount == 0:
                return False, "PRODUCT_NOT_FOUND"
            conn.commit()
        return True, "DELETED"
    except Exception as exc:
        return False, f"DB_ERROR: {exc}"


# ---------------------------------------------------------------------------
# Atomic order payment and receipts
# ---------------------------------------------------------------------------


def process_order_payment(
    token_uuid: str,
    card_uid: str,
    stall_id: str,
    cart_items: List[Dict[str, Any]],
) -> Tuple[bool, str, float, Optional[int], float]:
    """
    Validate current product prices, deduct the wallet, create the ledger entry,
    and save the order in one database transaction.
    """
    if not cart_items:
        return False, "EMPTY_ORDER", 0.0, None, 0.0

    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            wallet = cursor.execute(
                "SELECT balance, status FROM wallets WHERE token_uuid = ?",
                (token_uuid,),
            ).fetchone()
            if wallet is None:
                conn.rollback()
                return False, "UNREGISTERED_TOKEN", 0.0, None, 0.0
            if wallet["status"] != "ACTIVE":
                conn.rollback()
                return (
                    False,
                    "CARD_SUSPENDED",
                    float(wallet["balance"]),
                    None,
                    0.0,
                )

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

                product = cursor.execute(
                    """
                    SELECT product_id, product_name, price, is_available
                    FROM products
                    WHERE product_id = ? AND stall_id = ?
                    """,
                    (product_id, stall_id),
                ).fetchone()
                if product is None:
                    conn.rollback()
                    return False, "PRODUCT_NOT_FOUND", float(wallet["balance"]), None, 0.0
                if int(product["is_available"]) != 1:
                    conn.rollback()
                    return False, "PRODUCT_UNAVAILABLE", float(wallet["balance"]), None, 0.0

                unit_price = round(float(product["price"]), 2)
                item_total = round(unit_price * quantity, 2)
                note = str(item.get("note", "")).strip()[:250]
                normalized_items.append(
                    {
                        "product_id": product_id,
                        "product_name": str(product["product_name"]),
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "item_total": item_total,
                        "note": note,
                    }
                )
                total_amount = round(total_amount + item_total, 2)

            current_balance = round(float(wallet["balance"]), 2)
            if current_balance < total_amount:
                conn.rollback()
                return False, "INSUFFICIENT_FUNDS", current_balance, None, total_amount

            new_balance = round(current_balance - total_amount, 2)
            cursor.execute(
                "UPDATE wallets SET balance = ?, updated_at = ? WHERE token_uuid = ?",
                (new_balance, now, token_uuid),
            )
            cursor.execute(
                """
                INSERT INTO transaction_ledger
                    (token_uuid, card_uid, terminal_type, action_type,
                     amount, balance_after, timestamp)
                VALUES (?, ?, ?, 'PAY', ?, ?, ?)
                """,
                (token_uuid, card_uid, stall_id, total_amount, new_balance, now),
            )
            cursor.execute(
                """
                INSERT INTO orders
                    (stall_id, token_uuid, card_uid, total_amount,
                     balance_after, payment_status, created_at)
                VALUES (?, ?, ?, ?, ?, 'PAID', ?)
                """,
                (stall_id, token_uuid, card_uid, total_amount, new_balance, now),
            )
            order_id = int(cursor.lastrowid)

            cursor.executemany(
                """
                INSERT INTO order_items
                    (order_id, product_id, product_name, quantity,
                     unit_price, item_total, item_note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
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
                ],
            )
            conn.commit()
            return True, "SUCCESS", new_balance, order_id, total_amount
        except Exception as exc:
            conn.rollback()
            return False, f"TX_ERROR: {exc}", 0.0, None, 0.0


def get_order_receipt(order_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        order = conn.execute(
            """
            SELECT o.*, s.stall_name
            FROM orders AS o
            JOIN stalls AS s ON s.stall_id = o.stall_id
            WHERE o.order_id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            return None
        items = conn.execute(
            """
            SELECT product_name, quantity, unit_price, item_total, item_note
            FROM order_items
            WHERE order_id = ?
            ORDER BY order_item_id
            """,
            (order_id,),
        ).fetchall()
        result = dict(order)
        result["items"] = [dict(item) for item in items]
        return result


def get_recent_stall_orders(stall_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT order_id, total_amount, balance_after, payment_status, created_at
            FROM orders
            WHERE stall_id = ?
            ORDER BY order_id DESC
            LIMIT ?
            """,
            (stall_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
