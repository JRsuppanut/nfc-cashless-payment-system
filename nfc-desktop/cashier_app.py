"""Cashier UI with durable requests and verified NFC writing.

Requires the matching nfc_worker.py (API_VERSION 2), token_security.py, and
the existing database.py. Financial results are recovered with the original
operation ID; they are never inferred solely from card presence.
"""

# APPLICATION AND STANDARD LIBRARY IMPORTS
import sys
from contextlib import contextmanager
import psycopg2
import uuid
from datetime import datetime
# Use Decimal for currency arithmetic instead of binary floating-point.
from decimal import Decimal, InvalidOperation

# Qt signals and worker threads separate slow I/O from the GUI event loop.
from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QDialog, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QHeaderView,
)
from psycopg2.extras import DictCursor, Json

# Read database connection settings from the existing project module.
import database
import terminal_registry
from nfc_worker import NFCWorker, DEFAULT_PORT


# UI THEME: object names and tone properties select the existing Qt style rules.
# These rules preserve the latest layout, font sizes, and status colors.
STYLE = """
QWidget {
font-family: 'Tahoma';
font-size: 16px;
color: #192c4c;
}
QMainWindow, QWidget#root {
background: #eff6f4;
}
QFrame#panel, QFrame#header, QFrame#footer {
background: white;
border: 1px solid #dbe5e6;
border-radius: 12px;
}
QLabel#title {
font-size: 23px;
font-weight: bold;
}
QLabel#section {
font-size: 21px;
font-weight: bold;
}
QLabel#muted {
color: #526577;
font-size: 16px;
}
QLabel#money {
font-size: 48px;
font-weight: bold;
color: #007e64;
}
QFrame#hero[tone="blue"] QLabel#money {
color: #245fa8;
}
QFrame#hero[tone="amber"] QLabel#money {
color: #b76b0a;
}
QLabel#notice {
background: #fff2d5;
color: #955900;
border: 1px solid #f0d39a;
border-radius: 9px;
padding: 10px 14px;
font-size: 16px;
}
QFrame#hero {
background: #e4f6ee;
border: none;
border-radius: 12px;
}
QFrame#hero[tone="blue"] {
background: #e9f1ff;
}
QFrame#hero[tone="amber"] {
background: #fff1dc;
}
QPushButton {
background: white;
border: 1px solid #cad8d9;
border-radius: 9px;
padding: 9px 16px;
font-weight: bold;
}
QPushButton:hover {
background: #ecf6f1;
border-color: #009477;
}
QPushButton:checked {
background: #e0f5eb;
border: 2px solid #00856b;
color: #007e64;
}
QPushButton#mode:checked, QPushButton#primary {
background: qlineargradient(
x1:0, y1:0, x2:1, y2:1,
stop:0 #009477, stop:1 #00715b
);
color: white;
border: 1px solid #00856b;
}
QPushButton#primary:hover {
background: #006e57;
}
QPushButton:disabled, QPushButton#primary:disabled {
background: #e5ece9;
color: #93a29d;
border: 1px solid #dde5e0;
}
QPushButton#nav {
border: none;
border-radius: 0;
padding: 8px 20px;
background: transparent;
}
QPushButton#nav:checked {
color: #007e64;
border-bottom: 3px solid #00856b;
}
QPushButton#technicalButton {
background: white;
color: #192c4c;
border: 1px solid #b8ccca;
border-radius: 9px;
padding: 9px 15px;
font-size: 16px;
font-weight: bold;
}
QPushButton#technicalButton:hover {
background: #e8f5f0;
border: 2px solid #00856b;
color: #007e64;
}
QPushButton#preset {
font-size: 21px;
padding: 12px;
}
QLineEdit {
background: white;
border: 2px solid #00856b;
border-radius: 9px;
padding: 8px 14px;
font-size: 38px;
font-weight: bold;
}
QLineEdit:disabled {
background: #f1f5f3;
color: #93a29d;
}
QTextEdit {
background: #f5f8f6;
border: 1px solid #dce7df;
border-radius: 8px;
padding: 8px;
}
QTableWidget {
background: white;
border: 1px solid #dbe5e6;
gridline-color: #edf2ee;
selection-background-color: #e0f2e7;
selection-color: #192c4c;
alternate-background-color: #f8fbfa;
}
QHeaderView::section {
background: #e5f3ed;
padding: 11px;
border: none;
font-weight: bold;
}
QLabel#notice {
min-height: 48px;
padding: 12px 18px;
border-radius: 10px;
font-size: 19px;
font-weight: bold;
}
QLabel#notice[tone="info"] {
background: #e8f2ff; color: #1856a8;
border: 1px solid #9fc5ff; border-left: 7px solid #2d6cdf;
}
QLabel#notice[tone="warning"] {
background: #fff3d8; color: #9a5800;
border: 1px solid #efc66f; border-left: 7px solid #f0a500;
}
QLabel#notice[tone="success"] {
background: #e4f8ec; color: #087845;
border: 1px solid #9eddb8; border-left: 7px solid #16a05d;
}
QLabel#notice[tone="error"] {
background: #fff0ef; color: #bd2922;
border: 1px solid #f2aaa5; border-left: 7px solid #dc3730;
}
QLabel#filterInfo {
min-height: 0;
background: #eef8f4;
color: #176b58;
border: 1px solid #b8dfd2;
border-left: 5px solid #159276;
border-radius: 7px;
padding: 7px 11px;
font-size: 16px;
font-weight: bold;
}
QLabel#statusReady {
background:#e4f8ec; color:#087845; border:1px solid #9eddb8;
border-radius:13px; padding:7px 12px; font-weight:bold;
}
QLabel#statusWarning {
background:#fff3d8; color:#9a5800; border:1px solid #efc66f;
border-radius:13px; padding:7px 12px; font-weight:bold;
}
QLabel#statusError {
background:#fff0ef; color:#bd2922; border:1px solid #f2aaa5;
border-radius:13px; padding:7px 12px; font-weight:bold;
}
QLabel#cardHeading {
color:#087845; font-size:25px; font-weight:bold;
}
QLabel#largeValue {
color:#087845; font-size:34px; font-weight:bold;
}
QPushButton#danger {
color:#bd2922; border-color:#ef9b95; background:#fff7f6;
}
QPushButton#link {
color:#087845; border:2px solid #00856b; background:white;
}
"""


# Format a database/Decimal amount for display. This function does not change a balance.
def money(value):
    return f"฿{Decimal(str(value)):,.2f}"


# Create a wrapping label and optionally assign a CSS object name.
def label(text="", name=None):
    item = QLabel(text)
    item.setWordWrap(True)
    if name:
        item.setObjectName(name)
    return item


# Create a reusable white panel with the existing margins and spacing.
def panel():
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


# Update the status message and refresh its color from the tone property.
def set_banner(widget, tone, text):
    widget.setProperty("tone", tone)
    widget.setText(("● " if not str(text).lstrip().startswith("●") else "") + str(text))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# Update the small reader/database status indicator.
def set_pill(widget, tone, text):
    names = {
        "ready": "statusReady",
        "warning": "statusWarning",
        "error": "statusError",
    }
    widget.setObjectName(names[tone])
    widget.setText(text)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


# Draw scalable icons in code; no external image files are required.
def icon(kind, color, size=36):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 36, size / 36)
    painter.setPen(QPen(QColor(color), 2.5))
    if kind == 0:
        # Card only: no plus sign.
        painter.drawRoundedRect(3, 8, 30, 21, 3, 3)
        painter.drawLine(4, 14, 32, 14)
    elif kind == 1:
        # One coin stack. The plus stays outside its right edge.
        painter.drawEllipse(3, 7, 20, 8)
        painter.drawLine(3, 11, 3, 23)
        painter.drawLine(23, 11, 23, 23)
        painter.drawArc(3, 12, 20, 8, 180 * 16, 180 * 16)
        painter.drawArc(3, 19, 20, 8, 180 * 16, 180 * 16)
        painter.drawLine(27, 17, 35, 17)
        painter.drawLine(31, 13, 31, 21)
    elif kind == 2:
        painter.drawEllipse(4, 3, 22, 22)
        painter.drawLine(23, 23, 33, 33)
    else:
        painter.drawLine(5, 12, 27, 12)
        painter.drawLine(5, 12, 13, 4)
        painter.drawLine(5, 12, 13, 20)
        painter.drawArc(19, 12, 13, 17, -90 * 16, 180 * 16)
        painter.drawLine(17, 29, 26, 29)
    painter.end()
    return pixmap


# Known application error codes used by the transaction workflow.
class CashierError(Exception):
    pass


# DATABASE LAYER: durable requests, wallet changes, ledger entries, and recovery.
class CashierStore:
    """Durable requests; each retry keeps the original operation ID."""

    # Keep the terminal identifier used to own and recover requests.
    def __init__(self, terminal_id="CASHIER-01"):
        self.terminal_id = terminal_id

    # Commit on success, roll back on exceptions, and always close the connection.
    @contextmanager
    def connection(self):
        settings = dict(database.DB_CONFIG)
        # Limit connection waiting so an unavailable server does not leave a job waiting indefinitely.
        settings.setdefault("connect_timeout", 5)
        # Bound SQL execution and lock waiting; failures remain recoverable through operation IDs.
        settings.setdefault("options", "-c statement_timeout=8000 -c lock_timeout=5000")
        conn = psycopg2.connect(**settings)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # Create missing tables/columns without deleting existing wallet or ledger records.
    def initialize(self):
        with self.connection() as conn:
            with conn.cursor() as c:
                terminal_registry.require_cashier(c, self.terminal_id)
                c.execute("""
                    CREATE TABLE IF NOT EXISTS wallets (
                        token_uuid TEXT PRIMARY KEY, card_uid TEXT NOT NULL,
                        balance NUMERIC(10,2) NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'ACTIVE',
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS transaction_ledger (
                        transaction_id SERIAL PRIMARY KEY,
                        token_uuid TEXT NOT NULL REFERENCES wallets(token_uuid),
                        card_uid TEXT NOT NULL, terminal_type TEXT NOT NULL,
                        action_type TEXT NOT NULL, amount NUMERIC(10,2) NOT NULL,
                        balance_after NUMERIC(10,2) NOT NULL, timestamp TIMESTAMP NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS cashier_ui_operations (
                        operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                        token_uuid TEXT, card_uid TEXT NOT NULL,
                        amount NUMERIC(10,2), state TEXT NOT NULL DEFAULT 'PENDING',
                        result JSONB, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    ALTER TABLE cashier_ui_operations ADD COLUMN IF NOT EXISTS
                        terminal_id TEXT NOT NULL DEFAULT 'CASHIER-01';
                    ALTER TABLE cashier_ui_operations ADD COLUMN IF NOT EXISTS previous_token TEXT;
                    ALTER TABLE cashier_ui_operations ADD COLUMN IF NOT EXISTS
                        stage TEXT NOT NULL DEFAULT 'PREPARED';
                    CREATE INDEX IF NOT EXISTS cashier_ui_operations_terminal_pending
                        ON cashier_ui_operations(terminal_id,state,created_at);
                    ALTER TABLE transaction_ledger ADD COLUMN IF NOT EXISTS terminal_id TEXT;
                """)

    # Serialize this application's database changes for one physical card UID.
    def _lock_card(self, c, uid):
        c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("foodcourt-card:" + uid,))

    # Read one durable request; FOR UPDATE locks it when a caller will modify it.
    def _operation(self, c, operation_id, lock=False):
        c.execute("SELECT * FROM cashier_ui_operations WHERE operation_id=%s"
                  + (" FOR UPDATE" if lock else ""), (operation_id,))
        row = c.fetchone()
        return dict(row) if row else None

    # Find the wallet for one usage-cycle token, not all previous uses of a card.
    def wallet(self, token):
        if not token:
            return None
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("SELECT * FROM wallets WHERE token_uuid=%s", (token,))
                row = c.fetchone()
                return dict(row) if row else None

    # Look up the last registered cycle when inspecting a blank/legacy card.
    def latest_wallet(self, uid):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("""SELECT * FROM wallets WHERE card_uid=%s
                    ORDER BY created_at DESC,updated_at DESC LIMIT 1""", (uid,))
                row = c.fetchone()
                return dict(row) if row else None

    # Save the request in its own committed transaction BEFORE writing the card or changing money.
    def prepare(self, operation_id, kind, uid, token=None, amount=None, previous_token=None):
        if kind not in ("ISSUE", "TOP_UP", "RETURN_CARD"):
            raise CashierError("INVALID_OPERATION")
        value = None if amount is None else Decimal(str(amount))
        if kind == "TOP_UP" and (
            value is None or not value.is_finite() or value <= 0
            or value > Decimal("99999999.99") or value != value.quantize(Decimal("0.01"))
        ):
            raise CashierError("INVALID_AMOUNT")
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("foodcourt-terminal:" + self.terminal_id,))
                self._lock_card(c, uid)
                # A repeated operation ID must describe the same request and return its original state.
                existing = self._operation(c, operation_id, True)
                if existing:
                    if (existing["kind"] != kind or existing["card_uid"] != uid
                        or existing["token_uuid"] != token
                        or existing["terminal_id"] != self.terminal_id
                        or (kind == "TOP_UP" and existing["amount"] != value)):
                        raise CashierError("OPERATION_REQUEST_MISMATCH")
                    return existing
                c.execute("""SELECT operation_id FROM cashier_ui_operations
                    WHERE state='PENDING' AND (card_uid=%s OR terminal_id=%s) LIMIT 1""",
                    (uid, self.terminal_id))
                if c.fetchone():
                    raise CashierError("PENDING_OPERATION_EXISTS")
                if kind == "ISSUE":
                    # Lock all old usage cycles; finish_issue() replaces them atomically.
                    c.execute("""SELECT token_uuid FROM wallets WHERE card_uid=%s
                        ORDER BY created_at,token_uuid FOR UPDATE""", (uid,))
                    c.fetchall()
                c.execute("""INSERT INTO cashier_ui_operations
                    (operation_id,kind,token_uuid,card_uid,amount,terminal_id,previous_token,stage)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,'PREPARED') RETURNING *""",
                    (operation_id, kind, token, uid, value, self.terminal_id, previous_token))
                return dict(c.fetchone())

    # Persist that card writing is about to begin, so unsafe cancellation is refused.
    def mark_writing(self, operation_id):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("""UPDATE cashier_ui_operations SET stage='WRITING',updated_at=CURRENT_TIMESTAMP
                    WHERE operation_id=%s AND kind='ISSUE' AND state='PENDING' AND token_uuid IS NOT NULL
                    RETURNING operation_id""", (operation_id,))
                if not c.fetchone():
                    raise CashierError("ISSUE_NOT_PENDING")

    # Handle older unfinished setup requests that did not save their planned token.
    def adopt_issue_token(self, operation_id, token):
        """Upgrade an unfinished request created by the older application."""
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                op = self._operation(c, operation_id, True)
                if not op or op["terminal_id"] != self.terminal_id:
                    raise CashierError("OPERATION_NOT_FOUND")
                if op["state"] != "PENDING" or op["kind"] != "ISSUE":
                    return op
                if not op["token_uuid"]:
                    c.execute("""UPDATE cashier_ui_operations SET token_uuid=%s,
                        updated_at=CURRENT_TIMESTAMP WHERE operation_id=%s""", (token, operation_id))
                return self._operation(c, operation_id)

    # Save a known final result in the same transaction as its financial changes.
    def _save_result(self, c, op, result):
        c.execute("""UPDATE cashier_ui_operations SET state='DONE',result=%s,
            updated_at=CURRENT_TIMESTAMP WHERE operation_id=%s""", (Json(result), op["operation_id"]))
        return result

    # Atomically retire every older token and move its remaining value to the new token.
    def finish_issue(self, operation_id, uid, token):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                self._lock_card(c, uid)
                op = self._operation(c, operation_id, True)
                if not op or op["terminal_id"] != self.terminal_id:
                    raise CashierError("OPERATION_NOT_FOUND")
                if op["kind"] != "ISSUE" or op["card_uid"] != uid or op["token_uuid"] != token:
                    raise CashierError("OPERATION_REQUEST_MISMATCH")
                if op["state"] in ("DONE", "CANCELLED"):
                    return dict(op["result"] or {"success":False,"reason":"OPERATION_CANCELLED"})

                c.execute("""SELECT * FROM wallets WHERE card_uid=%s
                    ORDER BY created_at,token_uuid FOR UPDATE""", (uid,))
                old_wallets = [dict(row) for row in c.fetchall() if row["token_uuid"] != token]

                carry_balance = Decimal("0.00")
                keep_suspended = False
                for old in old_wallets:
                    old_balance = Decimal(str(old["balance"]))
                    if not old_balance.is_finite() or old_balance < 0:
                        raise CashierError("INVALID_BALANCE")
                    carry_balance += old_balance
                    if old["status"] not in ("ACTIVE", "AVAILABLE", "REPLACED") or (
                        old["status"] in ("AVAILABLE", "REPLACED") and old_balance != 0
                    ):
                        keep_suspended = True

                if carry_balance > Decimal("99999999.99"):
                    raise CashierError("BALANCE_LIMIT")

                # Preserve account holds: replacing the NFC token must not unsuspend a wallet.
                new_status = "SUSPENDED" if keep_suspended else "ACTIVE"

                c.execute("""UPDATE wallets SET balance=0,status='REPLACED',
                    updated_at=CURRENT_TIMESTAMP WHERE card_uid=%s AND token_uuid<>%s""",
                    (uid, token))

                c.execute("""INSERT INTO wallets(token_uuid,card_uid,balance,status,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT(token_uuid) DO NOTHING""",
                    (token, uid, carry_balance, new_status))
                c.execute("SELECT * FROM wallets WHERE token_uuid=%s FOR UPDATE", (token,))
                row = c.fetchone()
                if (
                    not row or row["card_uid"] != uid or row["status"] != new_status
                    or Decimal(str(row["balance"])) != carry_balance
                ):
                    raise CashierError("WALLET_REGISTRATION_FAILED")

                for old in old_wallets:
                    old_balance = Decimal(str(old["balance"]))
                    if old_balance > 0:
                        c.execute("""INSERT INTO transaction_ledger(
                            token_uuid,card_uid,terminal_type,terminal_id,action_type,
                            amount,balance_after,timestamp)
                            VALUES(%s,%s,'CASHIER',%s,'CARD_REISSUE_OUT',%s,0,CURRENT_TIMESTAMP)""",
                            (old["token_uuid"], uid, self.terminal_id, old_balance))

                action = "CARD_REISSUE_IN" if carry_balance > 0 else "SETUP_CARD"
                c.execute("""INSERT INTO transaction_ledger(
                    token_uuid,card_uid,terminal_type,terminal_id,action_type,
                    amount,balance_after,timestamp)
                    VALUES(%s,%s,'CASHIER',%s,%s,%s,%s,CURRENT_TIMESTAMP)""",
                    (token, uid, self.terminal_id, action, carry_balance, carry_balance))

                return self._save_result(c, op, {
                    "success":True,"kind":"ISSUE","token":token,"uid":uid,
                    "balance":str(carry_balance),"amount":str(carry_balance),
                    "status":new_status,"reissued":bool(old_wallets)})

    # Apply one prepared top-up/return, or return its saved result when retried.
    def execute_financial(self, operation_id):
        snapshot = self.operation(operation_id)
        if not snapshot:
            raise CashierError("OPERATION_NOT_FOUND")
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                self._lock_card(c, snapshot["card_uid"])
                op = self._operation(c, operation_id, True)
                if op["terminal_id"] != self.terminal_id:
                    raise CashierError("WRONG_TERMINAL")
                # DONE can contain success or a known rejection. Never apply the balance change again.
                if op["state"] in ("DONE", "CANCELLED"):
                    return dict(op["result"] or {"success":False,"reason":"OPERATION_CANCELLED"})
                kind, token, uid = op["kind"], op["token_uuid"], op["card_uid"]
                if kind not in ("TOP_UP", "RETURN_CARD"):
                    raise CashierError("INVALID_OPERATION")
                c.execute("SELECT * FROM wallets WHERE token_uuid=%s FOR UPDATE", (token,))
                row = c.fetchone()
                reason = None
                if not row:
                    reason = "WALLET_NOT_FOUND"
                elif row["card_uid"] != uid:
                    reason = "CARD_ID_MISMATCH"
                elif row["status"] != "ACTIVE":
                    reason = "CARD_NOT_ACTIVE"
                elif row["balance"] < 0:
                    reason = "INVALID_BALANCE"
                if reason:
                    return self._save_result(c, op, {"success":False,"reason":reason})
                # Read the authoritative balance only after locking the wallet row.
                before = Decimal(str(row["balance"]))
                amount = Decimal(str(op["amount"])) if kind == "TOP_UP" else before
                after = before + amount if kind == "TOP_UP" else Decimal("0.00")
                if kind == "TOP_UP" and (amount <= 0 or after > Decimal("99999999.99")):
                    return self._save_result(c, op, {"success":False,"reason":"BALANCE_LIMIT"})
                # Returning a card sets its stored balance to zero and marks that usage cycle unavailable for spending.
                status = "ACTIVE" if kind == "TOP_UP" else "AVAILABLE"
                c.execute("UPDATE wallets SET balance=%s,status=%s,updated_at=CURRENT_TIMESTAMP WHERE token_uuid=%s",
                          (after, status, token))
                c.execute("""INSERT INTO transaction_ledger(token_uuid,card_uid,terminal_type,terminal_id,
                    action_type,amount,balance_after,timestamp)
                    VALUES(%s,%s,'CASHIER',%s,%s,%s,%s,CURRENT_TIMESTAMP)""",
                    (token, uid, self.terminal_id, "TOP_UP" if kind == "TOP_UP" else "REFUND_RETURN", amount, after))
                return self._save_result(c, op, {
                    "success":True,"kind":kind,"token":token,"uid":uid,"amount":str(amount),
                    "before":str(before),"balance":str(after),"status":status})

    # Read a request by its original operation ID during recovery.
    def operation(self, operation_id):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                return self._operation(c, operation_id)

    # Only load unfinished requests owned by this terminal.
    def pending_operations(self):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute("""SELECT * FROM cashier_ui_operations WHERE state='PENDING'
                    AND terminal_id=%s ORDER BY created_at""", (self.terminal_id,))
                return [dict(row) for row in c.fetchall()]

    # Cancel an unexecuted request, or report its existing committed result.
    def cancel_operation(self, operation_id):
        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                op = self._operation(c, operation_id, True)
                if not op:
                    raise CashierError("OPERATION_NOT_FOUND")
                if op["terminal_id"] != self.terminal_id:
                    raise CashierError("WRONG_TERMINAL")
                # DONE can contain success or a known rejection. Never apply the balance change again.
                if op["state"] in ("DONE", "CANCELLED"):
                    return dict(op["result"] or {"success":False,"reason":"OPERATION_CANCELLED"})
                # After writing may have started, keep the request until the same card is repaired/verified.
                if op["kind"] == "ISSUE" and op["stage"] != "PREPARED":
                    raise CashierError("CARD_REPAIR_REQUIRED")
                result = {"success":False,"reason":"OPERATION_CANCELLED"}
                c.execute("""UPDATE cashier_ui_operations SET state='CANCELLED',result=%s,
                    updated_at=CURRENT_TIMESTAMP WHERE operation_id=%s""", (Json(result), operation_id))
                return result

    # Show this station's ledger by default, or one card cycle across all stations.
    def history(self, limit=200, token=None):
        if token is None:
            condition = "terminal_type='CASHIER' AND terminal_id=%s"
            value = self.terminal_id
        else:
            condition = "token_uuid=%s"
            value = token

        with self.connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as c:
                c.execute(f"""SELECT transaction_id,token_uuid,card_uid,terminal_type,terminal_id,
                    action_type,amount,balance_after,timestamp,'COMPLETED' AS operation_status
                    FROM transaction_ledger WHERE {condition}
                    ORDER BY transaction_id DESC LIMIT %s""", (value, limit))
                return [dict(row) for row in c.fetchall()]



# MODE BUTTON: keeps the English title and Thai subtitle together.
class ModeButton(QPushButton):
    # Preserve the compact four-mode row and vertically centered title/subtitle.
    def __init__(self, index, english, thai=""):
        super().__init__()
        self.index = index
        self.setObjectName("mode")
        self.setCheckable(True)
        # Keep the compact mode height agreed for the latest UI.
        self.setMinimumHeight(70)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)

        self.picture = QLabel()
        self.picture.setFixedSize(40, 40)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.picture)

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(4)
        # Center the two text lines together instead of spreading them vertically.
        texts.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.english = QLabel(english)
        self.english.setWordWrap(True)

        self.thai = QLabel(thai)
        self.thai.setWordWrap(True)

        texts.addWidget(self.english)
        if thai:
            texts.addWidget(self.thai)

        row.addLayout(texts, 1)

        for child in (self.picture, self.thai, self.english):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            )

        self.toggled.connect(self._colors)
        self._colors(False)

    # Change text/icon colors when the mode is selected.
    def _colors(self, checked):
        tone = (
            "#3571cc", "#00856b", "#3571cc", "#cc7915",
        )[self.index]

        self.picture.setPixmap(
            icon(self.index, "white" if checked else tone),
        )

        self.english.setStyleSheet(
            f"color: {'white' if checked else '#192c4c'};"
            "font-weight: bold; font-size: 15px;"
        )

        self.thai.setStyleSheet(
            f"color: {'#f0fff8' if checked else '#526577'};"
            "font-size: 16px;"
        )

# THREAD BRIDGE: forwards reader events to the Qt application through signals.
class NFCBridge(QObject):
    tag = pyqtSignal(str, bool, object, str)
    removed = pyqtSignal()

    # Send UID, validation result, token, and reader status through a Qt signal.
    def emit_tag(self, uid, valid, token, status):
        self.tag.emit(uid, valid, token, status)

    # Notify the GUI that the previously detected card is no longer present.
    def emit_removal(self):
        self.removed.emit()


# BACKGROUND JOB: performs blocking work without freezing the interface.
class Job(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(object)

    # Store the callable to execute in this worker thread.
    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    # Send either the return value or the actual exception back to the GUI.
    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as error:
            self.error.emit(error)


# CONFIRMATION UI: displays the proposed action; it never changes money itself.
class ConfirmationDialog(QDialog):
    """Presentation only; transaction validation stays in CashierApp."""

    # Build the existing confirmation panel; Cancel is the default keyboard action.
    def __init__(self, parent, title, english, card_id, caption, amount,
                 note, confirm_text, kind):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.resize(550, 420)
        self.setStyleSheet("""
            QDialog { background: #eff6f4; }
            QFrame#confirmationPanel {
                background: white; border: 1px solid #dbe5e6;
                border-radius: 12px;
            }
            QLabel#confirmationTitle {
                font-size: 22px; font-weight: bold; color: #192c4c;
            }
            QLabel#confirmationSubtitle {
                font-size: 16px; color: #526577;
            }
            QFrame#confirmationAmount {
                background: #e8f5ef; border: none; border-radius: 10px;
            }
            QLabel#confirmationMoney {
                font-size: 38px; font-weight: bold; color: #192c4c;
            }
            QLabel#confirmationNote {
                background: #fff3d8; color: #955900;
                border: none; border-radius: 8px; padding: 10px 12px;
            }
            QPushButton#confirmationCancel {
                background: white; color: #192c4c;
                border: 1px solid #cad8d9; border-radius: 8px;
                padding: 10px 16px; font-weight: bold;
            }
            QPushButton#confirmationAccept {
                background: #00856b; color: white;
                border: 1px solid #00856b; border-radius: 8px;
                padding: 10px 16px; font-weight: bold;
            }
            QPushButton#confirmationAccept:hover { background: #006e57; }
            QPushButton#confirmationCancel:focus { border: 2px solid #00856b; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        card = QFrame()
        card.setObjectName("confirmationPanel")
        box = QVBoxLayout(card)
        box.setContentsMargins(24, 22, 24, 22)
        box.setSpacing(16)
        heading = QHBoxLayout()
        picture = QLabel()
        picture.setPixmap(icon(kind, "#00856b", 34))
        heading.addWidget(picture)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label(english, "confirmationTitle"))
        titles.addWidget(label(title, "confirmationSubtitle"))
        heading.addLayout(titles, 1)
        box.addLayout(heading)
        identity = QHBoxLayout()
        identity.addWidget(label("Card ID", "confirmationSubtitle"))
        card_value = label(str(card_id or "—"))
        card_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        identity.addWidget(card_value, 1)
        box.addLayout(identity)
        amount_frame = QFrame()
        amount_frame.setObjectName("confirmationAmount")
        amount_box = QVBoxLayout(amount_frame)
        amount_box.setContentsMargins(18, 16, 18, 16)
        amount_box.setSpacing(6)
        amount_box.addWidget(label(caption, "confirmationSubtitle"))
        amount_box.addWidget(label(amount, "confirmationMoney"))
        box.addWidget(amount_frame)
        box.addWidget(label(note, "confirmationNote"))
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton("กลับไปตรวจสอบ")
        self.cancel_button.setObjectName("confirmationCancel")
        self.cancel_button.setMinimumHeight(44)
        self.cancel_button.setAutoDefault(False)
        # Pressing Enter by default cancels; committing requires the explicit confirmation action.
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton(confirm_text)
        self.confirm_button.setObjectName("confirmationAccept")
        self.confirm_button.setMinimumHeight(44)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.confirm_button)
        box.addLayout(actions)
        outer.addWidget(card)
        self.cancel_button.setFocus()


# APPLICATION CONTROLLER: coordinates the existing UI, card reader, and database.
class CashierApp(QMainWindow):
    MODE_ISSUE, MODE_TOPUP, MODE_CHECK, MODE_RETURN = range(4)
    HISTORY_LIMIT = 200
    MAX_BALANCE = Decimal("99999999.99")

    # Initialize state before building widgets, then start reader/status timers.
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NFC Cashier — แคชเชียร์")
        self.resize(1280, 800)
        self.setMinimumSize(960, 600)

        self.mode = self.MODE_ISSUE
        self.uid = None
        self.token = None
        self.valid = False
        self.card_status = ""
        self.wallet = None
        self.checked_uid = None
        self.pending = None
        self.blocked_uid = None
        self.uncertain = False
        self.busy = False
        self.db_ready = False
        self.reader_ready = False
        self.epoch = 0
        self.history_epoch = 0
        self.history_uid = None
        self.history_token = None
        self.checked_token = None
        self.current_operation = None
        self.operation_request = None
        self.jobs = set()
        self.compact = None
        # Read the station assigned on this workstation.
        self.terminal_id = terminal_registry.terminal_id("cashier")
        self.last_error = ""
        self.last_exception = None
        self.store = CashierStore(self.terminal_id)

        # Reader callbacks emit signals; the GUI receives card events through this bridge.
        self.bridge = NFCBridge()
        self.bridge.tag.connect(self._tag_detected)
        self.bridge.removed.connect(self._tag_removed)

        self._build_ui()

        self.worker = NFCWorker(
            port=terminal_registry.reader_port("cashier", DEFAULT_PORT),
            on_tag_detected=self.bridge.emit_tag,
            on_tag_removed=self.bridge.emit_removal,
        )
        # Start the shared NFC worker after all UI widgets have been built.
        self.worker.start()

        self.reader_timer = QTimer(self)
        self.reader_timer.timeout.connect(self._reader_state)
        # Poll reader status every 800 ms; this does not itself perform a financial transaction.
        self.reader_timer.start(800)

        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self._auto_history)
        # Refresh visible history every 15 seconds.
        self.history_timer.start(15000)

        self._initialize_db()
        self._empty_views()

    # Keep each QThread alive until completion and route results back to UI callbacks.
    def _job(self, function, done, failed):
        job = Job(function, self)
        self.jobs.add(job)
        job.result.connect(done)
        def failure(error):
            self.last_error = str(error)
            self.last_exception = error
            failed()
        job.error.connect(failure)
        job.finished.connect(lambda j=job: self.jobs.discard(j))
        job.finished.connect(job.deleteLater)
        job.start()


    # Build the unchanged header, navigation, four modes, and technical-details dialog.
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        header, header_box = panel()
        header.setObjectName("header")
        header_box.setContentsMargins(16, 10, 16, 10)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon(0, "#00856b", 40))
        head.addWidget(logo)
        head.addWidget(label("Food Court Cashier", "title"))
        head.addStretch()

        self.reader_label = QLabel("Reader: Connecting…")
        set_pill(self.reader_label, "warning", "Reader: Connecting…")
        head.addWidget(self.reader_label)

        self.db_label = QLabel("Database: Connecting…")
        set_pill(self.db_label, "warning", "Database: Connecting…")
        head.addWidget(self.db_label)

        terminal = label(self.terminal_id, "section")
        terminal.setStyleSheet("font-size:16px;")
        head.addWidget(terminal)

        self.db_retry = QPushButton("เชื่อมต่อใหม่")
        self.db_retry.clicked.connect(self._initialize_db)
        self.db_retry.hide()
        head.addWidget(self.db_retry)

        header_box.addLayout(head)
        outer.addWidget(header)

        nav = QHBoxLayout()
        self.operation_nav = QPushButton("Operations • ทำรายการ")
        self.history_nav = QPushButton("Transaction History • ประวัติธุรกรรม")

        for button in (self.operation_nav, self.history_nav):
            button.setObjectName("nav")
            button.setCheckable(True)
            nav.addWidget(button)

        nav.addStretch()
        self.details_toggle = QPushButton("รายละเอียดทางเทคนิคของบัตร")
        self.details_toggle.setObjectName("technicalButton")
        self.details_toggle.clicked.connect(self._toggle_details)
        nav.addWidget(self.details_toggle)
        self.recover_button = QPushButton("ตรวจสอบรายการก่อนหน้า")
        self.recover_button.setObjectName("danger")
        self.recover_button.clicked.connect(self._recover_operation)
        self.recover_button.hide()
        nav.addWidget(self.recover_button)
        outer.addLayout(nav)

        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)

        operation = QWidget()
        body = QVBoxLayout(operation)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        modes = QHBoxLayout()
        modes.setSpacing(10)
        self.mode_buttons = []

        mode_names = (
            ("Set Up a New Card", "ออกบัตรใหม่ / เปิดใช้บัตรหมุนเวียน"),
            ("Add Money to Card", "เติมเงินเข้าบัตร"),
            ("Check Card Balance", "ตรวจสอบยอดเงิน"),
            ("Return Card and Refund Balance", "คืนบัตรและคืนเงินคงเหลือ"),
        )
        for index, text in enumerate(mode_names):
            button = ModeButton(index, *text)
            button.clicked.connect(
                lambda _, i=index: self._switch_mode(i),
            )
            modes.addWidget(button, 1)
            self.mode_buttons.append(button)

        body.addLayout(modes)

        self.notice = label("", "notice")
        set_banner(self.notice, "info", "Ready for a New Card")
        body.addWidget(self.notice)

        self.mode_stack = QStackedWidget()
        self.mode_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        body.addWidget(self.mode_stack, 1)

        self.action_stack = QStackedWidget()
        self.action_stack.setFixedHeight(64)

        self._build_issue()
        self._build_topup()
        self._build_check()
        self._build_return()
        body.addWidget(self.action_stack)

        self.details_dialog = QDialog(self)
        self.details_dialog.setWindowTitle("รายละเอียดทางเทคนิคของบัตร")
        self.details_dialog.resize(620, 300)
        dialog_box = QVBoxLayout(self.details_dialog)
        self.details = QTextEdit(self.details_dialog)
        self.details.setReadOnly(True)
        dialog_box.addWidget(self.details)
        close = QPushButton("ปิด")
        close.clicked.connect(self.details_dialog.close)
        dialog_box.addWidget(close)

        self.pages.addWidget(operation)
        self._build_history()

        self.operation_nav.clicked.connect(
            lambda: self._navigate(0),
        )
        self.history_nav.clicked.connect(
            lambda: self._navigate(1),
        )
        self.operation_nav.setChecked(True)
        self.mode_buttons[0].setChecked(True)

    # Build the existing footer with Cancel and the mode-specific confirmation button.
    def _action_buttons(self, title, action, hint):
        frame, box = panel()
        frame.setObjectName("footer")
        box.setContentsMargins(16, 6, 16, 6)

        row = QHBoxLayout()
        row.addWidget(label(hint, "muted"), 1)

        cancel = QPushButton("ยกเลิก")
        cancel.clicked.connect(self._cancel)

        confirm = QPushButton(title)
        confirm.setObjectName("primary")
        confirm.clicked.connect(action)
        confirm.setEnabled(False)

        cancel.setMinimumHeight(42)
        confirm.setMinimumHeight(42)
        row.addWidget(cancel)
        row.addWidget(confirm)
        box.addLayout(row)

        self.action_stack.addWidget(frame)
        return confirm, cancel

    # Build a large read-only amount display.
    def _hero(self, box, caption, tone="green"):
        frame, hero = panel()
        frame.setObjectName("hero")
        frame.setProperty("tone", tone)

        hero.addStretch()

        title = label(caption, "muted")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(title)

        amount = label("—", "money")
        amount.setWordWrap(False)
        amount.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(amount)

        hero.addStretch()
        box.addWidget(frame, 1)
        return amount

    # Reusable panel helper retained from the previous UI.
    def _single_page(self):
        frame, box = panel()
        self.mode_stack.addWidget(frame)
        return box

    # Build the card-setup page and its How to Set Up a Card instructions.
    def _build_issue(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)

        left, box = panel()
        box.addWidget(label("Set Up a New Card", "section"))
        box.addWidget(label(
            "ออกบัตรใหม่หรือเปิดใช้บัตรหมุนเวียนที่รับคืนแล้ว",
            "muted",
        ))
        self.issue_heading = label("Ready for a New Card", "cardHeading")
        box.addWidget(self.issue_heading)
        self.issue_card = label("Card ID: —")
        self.issue_status = label("Card Status: Waiting")
        self.issue_balance = label("Starting Balance: ฿0.00", "largeValue")
        box.addWidget(self.issue_card)
        box.addWidget(self.issue_status)
        box.addWidget(self.issue_balance)
        box.addStretch()

        right, steps = panel()
        steps.addWidget(label("How to Set Up a Card", "section"))
        steps.addWidget(label("1  Place card on reader", "cardHeading"))
        steps.addWidget(label("วางบัตรบนเครื่องอ่าน", "muted"))
        steps.addWidget(label("2  Automatic card registration", "cardHeading"))
        steps.addWidget(label("ระบบจะสร้างบัญชีและเขียนข้อมูลลงบัตรให้อัตโนมัติ", "muted"))
        steps.addWidget(label("3  Wait for success", "cardHeading"))
        steps.addWidget(label("วางบัตรไว้จนระบบแจ้งว่าออกบัตรสำเร็จ", "muted"))
        steps.addStretch()

        row.addWidget(left, 60)
        row.addWidget(right, 40)
        self.mode_stack.addWidget(page)

        self.issue_confirm, self.issue_cancel = (
            self._action_buttons(
                "Confirm and Set Up Card",
                self._issue,
                "ระบบจะลงทะเบียนให้อัตโนมัติเมื่อแตะบัตร",
            )
        )
        self.issue_confirm.hide()

    # Build amount entry, preset amounts, and the top-up preview.
    def _build_topup(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)

        left, box = panel()
        box.addWidget(label("Add Money to Card", "section"))
        box.addWidget(label(
            "เลือกจำนวนเงิน รับเงินสด แล้วแตะบัตร",
            "muted",
        ))

        self.amount = QLineEdit("100.00")
        self.amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.amount.setMaxLength(16)
        self.amount.textChanged.connect(self._amount_changed)

        amount_row = QHBoxLayout()
        amount_row.addWidget(self.amount, 1)
        amount_row.addWidget(label("THB", "section"))
        box.addLayout(amount_row)

        grid = QGridLayout()
        self.preset_buttons = []

        for index, value in enumerate(
            (50, 100, 200, 300, 500, 1000),
        ):
            button = QPushButton(f"{value:,}")
            button.setObjectName("preset")
            button.setCheckable(True)
            button.setChecked(value == 100)
            button.clicked.connect(
                lambda _, v=value: self._choose_amount(v),
            )
            grid.addWidget(button, index // 3, index % 3)
            self.preset_buttons.append(button)

        box.addLayout(grid)
        box.addWidget(label("เลือกยอดด้านบน หรือพิมพ์จำนวนเงินเอง", "muted"))
        box.addStretch()

        self.topup_prepare = QPushButton("Scan card to continue")
        self.topup_prepare.hide()

        right, summary = panel()
        summary.addWidget(label("Top Up Summary", "section"))
        summary.addWidget(label("ตรวจสอบรายละเอียดก่อนยืนยัน", "muted"))

        self.topup_card = label("Card ID: —", "muted")
        summary.addWidget(self.topup_card)

        self.topup_status = label("Card Status: Waiting")
        summary.addWidget(self.topup_status)

        for caption, attribute in (
            ("Previous Balance", "old_balance"),
            ("Top Up Amount", "add_balance"),
        ):
            line = QHBoxLayout()
            line.addWidget(label(caption, "muted"), 1)
            value = label("—", "section")
            line.addWidget(value)
            setattr(self, attribute, value)
            summary.addLayout(line)

        self.new_balance = self._hero(
            summary, "New Balance",
        )
        summary.addWidget(label(
            "รับเงินสดแล้วกดยืนยัน และวางบัตรไว้จนรายการสำเร็จ",
            "muted",
        ))

        self.topup_confirm, self.topup_cancel = (
            self._action_buttons(
                "รับเงินสดแล้ว • ยืนยันเติมเงิน",
                self._topup,
                "วางบัตรไว้จนรายการสำเร็จ",
            )
        )

        row.addWidget(left, 55)
        row.addWidget(right, 45)
        self.mode_stack.addWidget(page)

    # Build the balance page; the last successful read can remain visible after removal.
    def _build_check(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)

        left, box = panel()
        box.addWidget(label("Check Card Balance", "section"))
        box.addWidget(label(
            "แตะบัตรเพื่อตรวจสอบยอดเงินล่าสุด",
            "muted",
        ))
        self.check_balance = self._hero(
            box, "Current Balance", "blue",
        )
        self.check_card = label("Card ID: —", "cardHeading")
        self.check_status = label("Card Status: Waiting")
        self.check_time = label("", "muted")
        box.addWidget(self.check_card)
        box.addWidget(self.check_status)
        box.addWidget(self.check_time)

        right, summary = panel()
        summary.addWidget(label("Current Card", "section"))
        summary.addWidget(label(
            "ยอดที่แสดงเป็นยอดเมื่ออ่านบัตรครั้งล่าสุด",
            "muted",
        ))
        summary.addStretch()
        self.card_history = QPushButton("View This Card’s History")
        self.card_history.setObjectName("link")
        self.card_history.setEnabled(False)
        self.card_history.clicked.connect(self._checked_history)
        summary.addWidget(self.card_history)

        row.addWidget(left, 60)
        row.addWidget(right, 40)
        self.mode_stack.addWidget(page)

        footer, footer_box = panel()
        footer.setObjectName("footer")
        footer_box.setContentsMargins(16, 6, 16, 6)
        footer_box.addWidget(label(
            "อ่านสำเร็จแล้วนำบัตรออกได้ • แตะบัตรใบถัดไปเพื่อแทนที่ผลเดิมโดยอัตโนมัติ",
            "muted",
        ))
        self.action_stack.addWidget(footer)
        self.next_card = QPushButton()
        self.next_card.hide()

    # Build the cash-refund preview. Actual cash is handed to the customer by staff.
    def _build_return(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)

        left, box = panel()
        box.addWidget(label("Return Card and Refund Balance", "section"))
        box.addWidget(label(
            "ตรวจสอบยอดคงเหลือ คืนเงินสด แล้วรับบัตรกลับมาหมุนเวียน",
            "muted",
        ))
        self.return_card = label("Card ID: —", "cardHeading")
        box.addWidget(self.return_card)
        self.return_amount = self._hero(
            box, "Cash Refund to Customer", "amber",
        )
        self.return_status = label("Card Status: Waiting")
        box.addWidget(self.return_status)

        right, summary = panel()
        summary.addWidget(label("After Confirmation", "section"))
        summary.addWidget(label("Balance After Return", "muted"))
        self.return_after = label("฿0.00", "largeValue")
        summary.addWidget(self.return_after)
        summary.addWidget(label("Card Status After Return", "muted"))
        self.return_after_status = label("Returned / Ready for reuse", "cardHeading")
        summary.addWidget(self.return_after_status)
        summary.addWidget(label(
            "วางบัตรไว้จนรายการสำเร็จ แล้วคืนเงินสดและเก็บบัตรไว้",
            "muted",
        ))
        summary.addStretch()

        row.addWidget(left, 60)
        row.addWidget(right, 40)
        self.mode_stack.addWidget(page)

        self.return_confirm, self.return_cancel = (
            self._action_buttons(
                "ยืนยันคืนบัตร",
                self._return_card,
                "ตรวจสอบยอดคืนและวางบัตรไว้จนรายการสำเร็จ",
            )
        )

    # Build the transaction table and its per-card history controls.
    def _build_history(self):
        page, box = panel()

        head = QHBoxLayout()
        head.addWidget(label("Transaction History", "section"))
        head.addStretch()

        self.show_all = QPushButton("กลับไปประวัติจุดนี้")
        self.show_all.clicked.connect(self._all_history)
        head.addWidget(self.show_all)

        self.history_refresh = QPushButton("รีเฟรช")
        self.history_refresh.clicked.connect(self._refresh_history)
        head.addWidget(self.history_refresh)
        box.addLayout(head)

        self.history_title = label(f"ประวัติของจุด {self.terminal_id}", "section")
        box.addWidget(self.history_title)
        self.history_focus = label("", "filterInfo")
        self.history_focus.hide()
        box.addWidget(self.history_focus)
        box.addWidget(label(
            "ดับเบิลคลิก Card ID เพื่อดูเฉพาะประวัติของบัตรใบนั้น • ไม่ต้องพิมพ์ Card ID",
            "muted",
        ))

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels((
            "วัน / เวลา", "Card ID", "จุดทำรายการ",
            "รายการ", "จำนวนเงิน", "ยอดคงเหลือ", "สถานะ",
        ))
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers,
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows,
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection,
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch,
        )
        self.table.cellDoubleClicked.connect(
            self._history_double_click,
        )
        box.addWidget(self.table, 1)

        self.history_message = label("", "muted")
        box.addWidget(self.history_message)
        self.pages.addWidget(page)

    # Open the technical dialog without cluttering normal operation pages.
    def _toggle_details(self):
        self._details()
        self.details_dialog.show()
        self.details_dialog.raise_()

    # Display diagnostic values here, including the operation ID and last error.
    def _details(self):
        self.details.setPlainText(
            f"Terminal: {self.terminal_id}\nNFC port: {getattr(self.worker, 'port', DEFAULT_PORT) if hasattr(self, 'worker') else DEFAULT_PORT}\n"
            f"Card ID: {self.uid or '—'}\nToken UUID: {self.token or '—'}\n"
            f"NFC status: {self.card_status or '—'}\n"
            f"Operation ID: {self.current_operation or '—'}\n"
            f"Last error: {self.last_error or '—'}"
        )


    # Connect and restore this terminal's unfinished request before accepting a new one.
    def _initialize_db(self):
        if self.busy:
            return
        self.db_ready = False
        self.db_retry.setEnabled(False)
        set_pill(self.db_label, "warning", "Database: Connecting…")
        self._disable_actions()
        def initialize():
            self.store.initialize()
            return self.store.pending_operations()
        def done(operations):
            self.db_ready = True
            self.db_retry.hide()
            self.db_retry.setEnabled(True)
            set_pill(self.db_label, "ready", "Database: Connected")
            if self.current_operation:
                self._unknown("กรุณาตรวจสอบผลรายการเดิมก่อนเริ่มรายการใหม่")
            elif operations:
                op = operations[0]
                self.current_operation = op["operation_id"]
                self.operation_request = dict(op)
                self._unknown("พบรายการที่ยังไม่เสร็จ กรุณากดตรวจสอบรายการก่อนหน้า")
            else:
                self._reload_card()
            self._refresh_history()
        self._job(initialize, done, self._db_failed)


    # Disable financial actions; retain any request whose result still needs checking.
    def _db_failed(self):
        self.db_ready = False
        self.pending = None
        set_pill(self.db_label, "error", "Database: Unavailable")
        self.db_retry.show()
        self.db_retry.setEnabled(True)
        self._disable_actions()
        if self.current_operation:
            self._unknown("เชื่อมต่อระบบไม่ได้ ต้องตรวจสอบผลรายการเดิมก่อนทำต่อ")
        else:
            set_banner(self.notice, "error", "เชื่อมต่อระบบไม่ได้ ตรวจสอบการเชื่อมต่อแล้วกดเชื่อมต่อใหม่")


    # Monitor reader connectivity. The matching NFC worker handles reconnect attempts.
    def _reader_state(self):
        connection = getattr(self.worker,"_serial_conn",None)
        ready = bool(self.worker.is_alive() and getattr(self.worker,"_pn532",None)
                     and connection and connection.is_open and self._compatible_worker())
        set_pill(self.reader_label,"ready" if ready else "error",
                 "Reader: Ready" if ready else "Reader: Disconnected")
        if ready == self.reader_ready:
            return
        self.reader_ready = ready
        if not ready:
            self._tag_removed()
        elif not self.busy and not self.uncertain:
            self._reload_card() if self.uid else self._idle_notice()


    # Explain why the UI is waiting or blocked instead of relying on color alone.
    def _idle_notice(self):
        if self.uncertain:
            set_banner(self.notice, "error", "ยังยืนยันผลรายการเดิมไม่ได้ กรุณากดตรวจสอบรายการก่อนหน้า")
        elif not self.db_ready:
            set_banner(self.notice, "warning", "Waiting for Database • รอเชื่อมต่อระบบก่อนทำรายการ")
        elif hasattr(self, "worker") and not self._compatible_worker():
            set_banner(self.notice, "error", "ส่วนติดต่อเครื่องอ่านยังไม่พร้อม กรุณาตรวจสอบการตั้งค่าระบบ")
        elif not self.reader_ready:
            set_banner(self.notice, "error", "Reader Not Ready • ตรวจสอบการเชื่อมต่อเครื่องอ่าน แล้วรอเชื่อมต่อใหม่")
        elif self.blocked_uid and self.uid == self.blocked_uid:
            set_banner(self.notice, "success", "Transaction Completed • นำบัตรออกก่อนเริ่มรายการถัดไป")
        else:
            text = {
                self.MODE_ISSUE:"Waiting for Card • วางบัตรสำหรับออกให้ลูกค้าบนเครื่องอ่าน",
                self.MODE_TOPUP:"Waiting for Card • เลือกจำนวนเงินและวางบัตรบนเครื่องอ่าน",
                self.MODE_CHECK:"Waiting for Card • วางบัตรเพื่อตรวจสอบยอดเงิน",
                self.MODE_RETURN:"Waiting for Card • วางบัตรเพื่อตรวจสอบยอดเงินที่จะคืน",
            }[self.mode]
            set_banner(self.notice, "warning", text)


    # Disable every action that could begin or confirm a card transaction.
    def _disable_actions(self):
        for button in (
            self.issue_confirm,
            self.topup_confirm,
            self.return_confirm,
            self.topup_prepare,
        ):
            button.setEnabled(False)

    # Clear transient previews, optionally preserving the last balance inquiry.
    def _empty_views(self, preserve_check=False):
        self._disable_actions()
        self.issue_card.setText("Card ID: —")
        self.issue_heading.setText("Ready for a New Card")
        self.issue_status.setText("Card Status: Waiting")
        self.topup_card.setText("Card ID: —")
        self.topup_status.setText("Card Status: Waiting")
        self.return_card.setText("Card ID: —")

        for item in (
            self.old_balance, self.add_balance,
            self.new_balance, self.return_amount,
        ):
            item.setText("—")

        self.return_status.setText("Card Status: Waiting")
        self.return_confirm.setText("ยืนยันคืนบัตร")
        self.topup_confirm.setText("รับเงินสดแล้ว • ยืนยันเติมเงิน")

        if not preserve_check:
            self.checked_uid = None
            self.checked_token = None
            self.check_card.setText("Card ID: —")
            self.check_balance.setText("—")
            self.check_status.setText("Card Status: Waiting")
            self.check_time.setText("")
            self.card_history.setEnabled(False)

        self._details()
        self._idle_notice()

    # Switch Operations/History without interrupting an active background transaction.
    def _navigate(self, index, *, for_card=False):
        if self.busy:
            return

        self.pages.setCurrentIndex(index)
        self.operation_nav.setChecked(index == 0)
        self.history_nav.setChecked(index == 1)

        if index == 1:
            self._cancel_pending()
            if not for_card:
                self.history_uid = self.history_token = None
            self._refresh_history()
        elif self.uid:
            self._reload_card()
        else:
            self._idle_notice()

    # Change modes and read the card again, even when it remains on the reader.
    def _switch_mode(self, mode):
        if self.busy:
            return

        self.mode = mode
        self.mode_stack.setCurrentIndex(mode)
        self.action_stack.setCurrentIndex(mode)

        for index, button in enumerate(self.mode_buttons):
            button.setChecked(index == mode)

        self._cancel_pending()
        self._empty_views()
        self._reload_card()

    # Invalidate old screen-read callbacks; this does NOT cancel a durable database request.
    def _cancel_pending(self):
        self.epoch += 1
        self.pending = None
        self._disable_actions()

    # Ask the database before cancellation; a committed operation must never be undone by guessing.
    def _cancel(self):
        if self.busy:
            return
        if self.current_operation:
            answer = QMessageBox.question(self,"ตรวจสอบก่อนยกเลิก",
                "ระบบจะตรวจผลรายการเดิมก่อน ยกเลิกได้เฉพาะรายการที่ยังไม่บันทึกยอดเงินหรือเริ่มเขียนบัตร ต้องการตรวจสอบและยกเลิกหรือไม่?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            operation_id = self.current_operation
            self._busy(True)
            def cancel():
                op = self.store.operation(operation_id)
                if not op:
                    return {"success":False,"reason":"OPERATION_CANCELLED"}
                return self.store.cancel_operation(operation_id)
            self._job(cancel,self._finish_result,self._request_failed)
            return
        if self.uid:
            self.blocked_uid = self.uid
        self._cancel_pending()
        self._empty_views()
        set_banner(self.notice,"warning","ยกเลิกรายการที่ยังไม่ยืนยันแล้ว นำบัตรออกก่อนเริ่มใหม่")


    # Clear the current preview and require removal before another interaction.
    def _next_card(self):
        if self.uid:
            self.blocked_uid = self.uid

        self._cancel_pending()
        self._empty_views()

    # Recalculate the preview and invalidate any earlier unconfirmed amount snapshot.
    def _amount_changed(self):
        for button in self.preset_buttons:
            try:
                button.setChecked(
                    Decimal(self.amount.text())
                    == Decimal(button.text().replace(",", ""))
                )
            except InvalidOperation:
                button.setChecked(False)

        if self.mode != self.MODE_TOPUP or self.busy:
            return

        self.pending = None
        self.topup_confirm.setEnabled(False)
        if self.wallet and self._can_read():
            self._display_wallet(self.wallet)
        else:
            for item in (self.old_balance, self.add_balance, self.new_balance):
                item.setText("—")
            self._idle_notice()

    # Copy a preset amount into the input and update selected preset buttons.
    def _choose_amount(self, value):
        self.amount.setText(f"{value:.2f}")
        for button in self.preset_buttons:
            button.setChecked(
                button.text().replace(",", "") == str(value),
            )

    # Central gate for new card actions: reader/database ready, correct page, and no unresolved request.
    def _can_read(self):
        return bool(self.uid and self.db_ready and self.reader_ready
                    and self._compatible_worker() and not self.busy and not self.uncertain
                    and self.uid != self.blocked_uid and self.pages.currentIndex() == 0)


    # Handle a reader event without replacing the identity of an in-progress request.
    def _tag_detected(self, uid, valid, token, status):
        self.epoch += 1
        self.uid, self.valid, self.token, self.card_status = uid, valid, token, status
        if self.busy:
            self._details()
            return
        if self.uncertain:
            expected = (self.operation_request or {}).get("card_uid")
            set_banner(self.notice, "warning" if uid == expected else "error",
                "พบบัตรใบเดิมแล้ว กดตรวจสอบรายการก่อนหน้าเพื่อดำเนินการต่อ"
                if uid == expected else "กรุณาวางบัตรใบเดิมของรายการที่ยังไม่เสร็จ")
            self._details()
            return
        self.wallet = None
        self.pending = None
        self._empty_views()
        self._reload_card()


    # Removal before confirmation clears the preview; after confirmation it does not prove rollback.
    def _tag_removed(self):
        self.epoch += 1
        self.uid = self.token = None
        self.valid = False
        self.card_status = ""
        self.wallet = None
        self.pending = None
        self.blocked_uid = None
        if self.busy:
            set_banner(self.notice, "warning",
                "บัตรถูกนำออก ระบบกำลังตรวจสอบรายการเดิม กรุณารอผลและอย่าทำรายการซ้ำ")
            self._details()
            return
        if self.uncertain:
            set_banner(self.notice, "error", "รายการยังไม่เสร็จ กรุณาวางบัตรใบเดิมกลับมาและตรวจสอบรายการก่อนหน้า")
            self._details()
            return
        keep = self.mode == self.MODE_CHECK and self.checked_uid is not None
        self._empty_views(preserve_check=keep)
        if keep:
            set_banner(self.notice, "success", "Card Read Successfully • นำบัตรออกแล้ว ยอดที่แสดงเป็นยอดเมื่ออ่านล่าสุด")


    # Read any supported NTAG card and automatically replace its token in Set Up mode.
    def _reload_card(self):
        self._disable_actions()
        if not self._can_read():
            self._idle_notice()
            return
        self.epoch += 1
        generation, uid, mode = self.epoch, self.uid, self.mode
        self.pending = None
        self.wallet = None
        set_banner(self.notice, "warning", "Checking Card • กำลังตรวจสอบบัตร กรุณาวางบัตรไว้")

        def read():
            snapshot = self.worker.read_current_card(uid)
            card_uid, valid, token, status = snapshot
            if mode == self.MODE_ISSUE:
                row = self.store.latest_wallet(card_uid)
            else:
                row = self.store.wallet(token) if valid and token else self.store.latest_wallet(card_uid)
            return snapshot, row

        def done(result):
            if generation != self.epoch or not self._can_read():
                return
            snapshot, row = result
            self.uid, self.valid, self.token, self.card_status = snapshot
            for item in (self.issue_card, self.topup_card, self.return_card):
                item.setText(f"Card ID: {uid}")
            self._details()

            if mode == self.MODE_ISSUE:
                if self.card_status == "UNSUPPORTED_TAG":
                    self.issue_status.setText("Card Status: Unsupported Tag")
                    set_banner(
                        self.notice, "error",
                        "บัตรชนิดนี้ไม่รองรับ ต้องใช้ NTAG213/215/216 ที่เขียนข้อมูลได้",
                    )
                    return

                self.issue_heading.setText("Registering Card...")
                self.issue_status.setText("Card Status: Replacing previous registration")
                set_banner(
                    self.notice, "warning",
                    "Registering Card • กำลังเขียน Token ใหม่และย้ายยอดเดิม กรุณาวางบัตรไว้",
                )
                self._start_request(
                    "ISSUE", uid, str(uuid.uuid4()), previous_token=self.token
                )
                return

            if not self.valid:
                self.issue_status.setText("Card Status: Cannot Use")
                set_banner(
                    self.notice, "error",
                    "Token ของบัตรไม่ถูกต้อง กรุณาไปที่ Set Up a New Card เพื่อเขียนทับ",
                )
                return

            if not row or row.get("card_uid") != uid:
                set_banner(self.notice, "error", "ไม่พบข้อมูลที่ตรงกับบัตร กรุณาให้ผู้ดูแลตรวจสอบ")
                return

            self.wallet = row
            self._display_wallet(row)

        def failed():
            if generation != self.epoch:
                return
            if isinstance(self.last_exception, psycopg2.Error):
                self._db_failed()
            else:
                self.pending = None
                self._disable_actions()
                set_banner(
                    self.notice, "error",
                    "อ่านบัตรไม่ได้หรือบัตรไม่รองรับ กรุณาตรวจสอบชนิด NTAG และวางบัตรให้ตรงเครื่องอ่าน",
                )

        self._job(read, done, failed)


    # Render wallet details, but never permit spending from a suspended/replaced cycle.
    def _display_wallet(self, wallet):
        balance = Decimal(str(wallet.get("balance", 0))) if wallet else Decimal(0)
        state = wallet.get("status", "UNAVAILABLE")

        if self.mode == self.MODE_ISSUE:
            self.issue_status.setText(f"Card Status: {state}")
            self.issue_confirm.setEnabled(False)
            return

        if state != "ACTIVE":
            self.topup_confirm.setEnabled(False)
            self.return_confirm.setEnabled(False)
            if self.mode == self.MODE_CHECK:
                self.checked_uid = self.uid
                self.checked_token = self.token
                self.check_card.setText(f"Card ID: {self.uid}")
                self.check_balance.setText(f"฿{balance:,.2f}")
                self.check_status.setText(f"Card Status: {state}")
                self.card_history.setEnabled(True)
            elif self.mode == self.MODE_TOPUP:
                self.topup_status.setText(f"Card Status: {state}")
            elif self.mode == self.MODE_RETURN:
                self.return_status.setText(f"Card Status: {state}")
            set_banner(
                self.notice, "error",
                "บัตรนี้ถูกระงับหรือเป็น Token รอบเก่า ไม่อนุญาตให้เติมเงินหรือชำระเงิน",
            )
            return

        # 3. โหมดตรวจสอบบัตร (Check Card Balance)
        if self.mode == self.MODE_CHECK:
            self.checked_uid = self.uid
            self.checked_token = self.token
            self.check_card.setText(f"Card ID: {self.uid}")
            self.check_balance.setText(f"฿{balance:,.2f}")
            self.check_status.setText("Card Status: ใช้งานได้")
            self.card_history.setEnabled(True)
            self.notice.show()
            set_banner(self.notice, "success", "อ่านยอดเงินสำเร็จ นำบัตรออกได้")

        # 4. โหมดคืนบัตร (Return Card)
        elif self.mode == self.MODE_RETURN:
            self.return_amount.setText(f"฿{balance:,.2f}")
            self.return_status.setText("Card Status: ใช้งานได้")
            self.return_confirm.setEnabled(True)  # บังคับเปิดปุ่มให้กดคืนบัตรได้

        # 5. โหมดเติมเงิน (Add Money to Card)
        else:
            self.old_balance.setText(f"฿{balance:,.2f}")
            self.topup_status.setText("Card Status: ใช้งานได้")
            try:
                amount = self._parse_amount()
            except ValueError:
                return

            self.add_balance.setText(f"฿{amount:,.2f}")
            self.new_balance.setText(f"฿{(balance + amount):,.2f}")
            self.pending = (self.uid, self.token, amount)
            self.topup_confirm.setEnabled(True)  # บังคับเปิดปุ่มให้เติมเงินได้

    # Reject non-finite, non-positive, oversized, and more-than-two-decimal amounts.
    def _parse_amount(self):
        try:
            text = self.amount.text().strip()
            value = Decimal(text)

            if (
                not value.is_finite()
                or value <= 0
                or value > self.MAX_BALANCE
            ):
                raise ValueError

            if value != value.quantize(Decimal("0.01")):
                raise ValueError

            return value
        except (InvalidOperation, ValueError):
            raise ValueError(
                "กรอกจำนวนเงินมากกว่า 0"
                " โดยมีทศนิยมไม่เกิน 2 ตำแหน่ง"
                " และไม่ใส่เครื่องหมายอื่น"
            )

    # Recheck that the displayed UID/token still matches after the modal confirmation closes.
    def _confirm_identity(self, uid, token):
        return (
            self._can_read()
            and self.uid == uid
            and self.token == token
        )

    # Build one of the three existing confirmation dialogs using the amount being confirmed.
    def _ask(self, title, message):
        lines = message.splitlines()
        if title == "ยืนยันออกบัตร":
            english = "Confirm Card Setup"
            caption = "Starting Balance"
            amount = money(0)
            note = "วางบัตรไว้จนระบบยืนยันออกบัตรสำเร็จ"
            confirm_text = "ยืนยันออกบัตร"
            kind = 0
        elif title == "ยืนยันเติมเงิน":
            english = "Confirm Top Up"
            caption = "Top Up Amount"
            amount = lines[1].removeprefix("เติมเงิน ")
            note = "ได้รับเงินสดจากลูกค้าแล้ว จึงกดยืนยัน และวางบัตรไว้จนสำเร็จ"
            confirm_text = "รับเงินสดแล้ว • ยืนยันเติมเงิน"
            kind = 1
        else:
            english = "Confirm Card Return"
            caption = "Cash Refund • ยอดคงเหลือที่อ่านล่าสุด"
            amount = lines[1].removeprefix("ยอดคงเหลือที่อ่านล่าสุด ")
            note = "เมื่อระบบยืนยันสำเร็จ ให้คืนเงินสดตามยอดที่แสดงและเก็บบัตรไว้"
            confirm_text = "ยืนยันคืนบัตร"
            kind = 3
        dialog = ConfirmationDialog(
            self, title, english, self.uid, caption, amount,
            note, confirm_text, kind,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    # Disable actions that could edit or duplicate a request while background work is running.
    def _busy(self, enabled):
        self.busy = enabled
        controls = self.mode_buttons + self.preset_buttons + [self.operation_nav,self.history_nav,
            self.issue_cancel,self.topup_cancel,self.return_cancel,self.next_card,self.card_history,
            self.db_retry,self.recover_button]
        for control in controls:
            control.setEnabled(not enabled)
        self.amount.setEnabled(not enabled)
        self._disable_actions()
        if not enabled:
            self.card_history.setEnabled(self.checked_uid is not None)


    # Confirm the selected card, then plan a new usage-cycle token before writing it.
    def _issue(self):
        if not self.issue_confirm.isEnabled() or not self._can_read():
            return
        uid, old_token = self.uid, self.token
        if not self._ask("ยืนยันออกบัตร", f"Card ID: {uid}\nยอดเงินเริ่มต้น ฿0.00"):
            return
        if not self._confirm_identity(uid, old_token) or not self.issue_confirm.isEnabled():
            set_banner(self.notice,"error","ข้อมูลบัตรเปลี่ยนแล้ว กรุณาวางบัตรและตรวจสอบใหม่")
            return
        self._start_request("ISSUE",uid,str(uuid.uuid4()),previous_token=old_token)


    # Confirm an immutable UID/token/amount snapshot before starting the top-up request.
    def _topup(self):
        if not self.pending or not self.topup_confirm.isEnabled():
            return
        snapshot = self.pending
        uid, token, amount = snapshot
        if not self._ask("ยืนยันเติมเงิน",f"Card ID: {uid}\nเติมเงิน {money(amount)}\nได้รับเงินสดแล้วใช่ไหม?"):
            return
        if self.pending != snapshot or not self._confirm_identity(uid,token):
            set_banner(self.notice,"error","ข้อมูลบัตรหรือจำนวนเงินเปลี่ยนแล้ว กรุณาตรวจสอบใหม่")
            return
        self._start_request("TOP_UP",uid,token,amount)


    # Confirm card return; use the committed database balance as the final cash-refund amount.
    def _return_card(self):
        if not self.return_confirm.isEnabled() or not self.wallet or not self._can_read():
            return
        uid, token = self.uid, self.token
        amount = self.wallet.get("balance",0)
        if not self._ask("ยืนยันคืนบัตร",f"Card ID: {uid}\nยอดคงเหลือที่อ่านล่าสุด {money(amount)}"):
            return
        if not self._confirm_identity(uid,token) or not self.return_confirm.isEnabled():
            set_banner(self.notice,"error","ข้อมูลบัตรเปลี่ยนแล้ว กรุณาตรวจสอบใหม่")
            return
        self._start_request("RETURN_CARD",uid,token)


    # Handle a known business rejection; keep uncertain outcomes in the recovery workflow.
    def _transaction_failure(self, reason):
        meanings = {
            "OPERATION_CANCELLED":"ยกเลิกรายการแล้ว ไม่มีการเปลี่ยนยอดเงินจากรายการนี้",
            "WALLET_NOT_FOUND":"ไม่พบข้อมูลบัตร กรุณาให้ผู้ดูแลตรวจสอบ",
            "CARD_ID_MISMATCH":"บัตรไม่ตรงกับข้อมูลรายการ",
            "CARD_NOT_ACTIVE":"บัตรนี้คืนแล้วหรือไม่พร้อมใช้งาน",
            "BALANCE_LIMIT":"ยอดเงินหลังเติมเกินขีดจำกัด",
            "INVALID_AMOUNT":"จำนวนเงินไม่ถูกต้อง",
            "INVALID_BALANCE":"ข้อมูลยอดเงินผิดปกติ กรุณาให้ผู้ดูแลตรวจสอบ",
        }
        if reason not in meanings:
            self._unknown("ยังยืนยันผลรายการไม่ได้ กรุณาตรวจสอบรายการเดิมก่อนทำต่อ")
            return
        self._busy(False)
        self.blocked_uid = self.uid
        self._clear_operation()
        set_banner(self.notice,"warning" if reason == "OPERATION_CANCELLED" else "error",meanings[reason])
        self._refresh_history()


    # Block new transactions and show recovery controls while the result is unresolved.
    def _unknown(self, message):
        self.uncertain = True
        self.pending = None
        self._busy(False)
        self._disable_actions()
        self.recover_button.setEnabled(True)
        self.recover_button.show()
        set_banner(self.notice,"error",message)
        self._details()


    # Clear only the local request state after its final result is known.
    def _clear_operation(self):
        self.current_operation = None
        self.operation_request = None
        self.uncertain = False
        self.recover_button.hide()

    # Retry/check the SAME operation ID; do not create a second financial request.
    def _recover_operation(self):
        if self.busy or not self.current_operation or not self.operation_request:
            return
        self._run_request(dict(self.operation_request))


    # Open history for the token that produced the displayed balance inquiry.
    def _checked_history(self):
        if self.checked_uid and self.checked_token:
            self.history_uid = self.checked_uid
            self.history_token = self.checked_token
            self._navigate(1, for_card=True)

    # Leave card history and return to this station's ledger.
    def _all_history(self):
        self.history_uid = None
        self.history_token = None
        self._refresh_history()

    # Use the hidden UID/token metadata attached to the selected Card ID cell.
    def _history_double_click(self, row, column):
        if column != 1:
            return

        item = self.table.item(row, column)
        if item and item.data(Qt.ItemDataRole.UserRole):
            identity = item.data(Qt.ItemDataRole.UserRole)
            self.history_uid = identity["uid"]
            self.history_token = identity["token"]
            self._refresh_history()

    # Refresh periodically only while the history page is visible and not already loading.
    def _auto_history(self):
        if (
            self.pages.currentIndex() == 1
            and self.history_refresh.isEnabled()
        ):
            self._refresh_history()

    # Load ledger rows asynchronously and ignore obsolete filter results.
    def _refresh_history(self):
        self.history_epoch += 1
        generation = self.history_epoch
        uid, token = self.history_uid, self.history_token

        self.history_title.setText(
            "ประวัติของบัตรใบนี้"
            if token else f"ประวัติของจุด {self.terminal_id}"
        )
        self.show_all.setEnabled(token is not None)
        self.history_focus.setVisible(token is not None)
        if token:
            self.history_focus.setText(
                f"กำลังดู Card ID: {uid} • รวมรายการจากทุกจุดในรอบการใช้งานนี้"
            )
        self.table.setRowCount(0)

        if not self.db_ready:
            self.history_message.setText(
                "ฐานข้อมูลไม่พร้อม"
                " • เชื่อมต่อฐานข้อมูลก่อนดูประวัติ"
            )
            return

        self.history_refresh.setEnabled(False)
        self.history_message.setText("กำลังโหลดประวัติ…")

        def done(records):
            if generation != self.history_epoch:
                return

            self.history_refresh.setEnabled(True)
            self.table.setRowCount(len(records))

            for row, record in enumerate(records):
                stamp = record.get("timestamp", "")
                try:
                    stamp = datetime.fromisoformat(
                        str(stamp),
                    ).strftime("%d/%m/%Y %H:%M:%S")
                except (ValueError, TypeError):
                    stamp = str(stamp)

                action = record.get("action_type", "")
                action_text = {
                    "SETUP_CARD": "ออกบัตร / เปิดรอบใหม่",
                    "CARD_REISSUE_OUT": "ย้ายยอดจาก Token เก่า",
                    "CARD_REISSUE_IN": "รับยอดจาก Token เดิม",
                    "TOP_UP": "เติมเงิน",
                    "PAY": "ชำระค่าอาหาร",
                    "REFUND_MEAL": "คืนเงินค่าอาหารเข้าบัตร",
                    "REFUND_RETURN": "คืนเงิน / คืนบัตร",
                }.get(action, action)

                terminal = record.get("terminal_type", "")
                terminal_text = record.get("terminal_id") or {
                    "CASHIER": "แคชเชียร์",
                    "STALL_POS": "ร้านค้า",
                    "STALL": "ร้านค้า",
                }.get(terminal, terminal)

                amount = Decimal(str(record.get("amount", 0)))

                if action in ("TOP_UP", "REFUND_MEAL", "CARD_REISSUE_IN"):
                    prefix = "+"
                elif action in ("PAY", "REFUND_RETURN", "CARD_REISSUE_OUT"):
                    prefix = "−"
                else:
                    prefix = ""

                card_uid = record.get("card_uid")
                values = (
                    stamp,
                    card_uid or "—",
                    terminal_text,
                    action_text,
                    prefix + money(abs(amount)),
                    money(record.get("balance_after", 0)),
                    record.get("operation_status", "COMPLETED").title(),
                )

                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))

                    if column == 1 and card_uid:
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            {
                                "uid": card_uid,
                                "token": record.get("token_uuid"),
                            },
                        )
                        item.setForeground(QColor("#08774f"))
                        font = item.font()
                        font.setUnderline(True)
                        item.setFont(font)

                    if column in (4, 5):
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter,
                        )

                    if column == 4:
                        if prefix == "+":
                            color = "#08774f"
                        elif prefix == "−":
                            color = "#b34b37"
                        else:
                            color = "#20392f"
                        item.setForeground(QColor(color))

                    self.table.setItem(row, column, item)

            if records:
                self.history_message.setText(
                    f"แสดงรายการล่าสุด {len(records)} รายการ"
                    f" (สูงสุด {self.HISTORY_LIMIT})"
                    " • จำนวนเงินเป็นการเคลื่อนไหวของยอดในบัตร"
                )
            else:
                self.history_message.setText(
                    "ยังไม่มีธุรกรรมในรายการที่เลือก",
                )

        def failed():
            if generation == self.history_epoch:
                self.history_refresh.setEnabled(True)
                self.history_message.setText(
                    "โหลดประวัติไม่ได้"
                    " • ตรวจสอบฐานข้อมูลแล้วกดรีเฟรช"
                )

        self._job(
            lambda: self.store.history(self.HISTORY_LIMIT, token),
            done,
            failed,
        )

    # Allow ordinary closing after jobs finish; durable unfinished requests survive reopening.
    def closeEvent(self, event):
        if self.busy or any(
            job.isRunning() for job in self.jobs
        ):
            QMessageBox.information(
                self,
                "กรุณารอ",
                "รอให้โปรแกรมตรวจสอบหรือทำรายการเสร็จก่อนปิดค่ะ",
            )
            event.ignore()
            return

        self.reader_timer.stop()
        self.history_timer.stop()
        self.worker.stop()
        event.accept()

    # Preserve the existing compact-window adjustments without shrinking Thai helper text.
    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.height() < 720

        if compact == self.compact:
            return

        self.compact = compact
        extra = """
        QLabel#title { font-size: 20px; }
        QLabel#section { font-size: 18px; }
        QLabel#money { font-size: 38px; }
        QPushButton#preset { font-size: 18px; padding: 6px; }
        QLineEdit { font-size: 28px; padding: 6px 10px; }
        """ if compact else ""

        self.setStyleSheet(STYLE + extra)

        for frame in self.findChildren(QFrame):
            if (
                frame.objectName() in ("panel", "hero")
                and frame.layout()
            ):
                margins = (
                    (12, 10, 12, 10)
                    if compact else (20, 18, 20, 18)
                )
                frame.layout().setContentsMargins(*margins)
                frame.layout().setSpacing(7 if compact else 12)

    # Require the reader API that supports fresh reads and repeatable token provisioning.
    def _compatible_worker(self):
        return getattr(self.worker, "API_VERSION", 0) >= 2

    # Create ONE operation ID and keep its immutable request for later recovery.
    def _start_request(self, kind, uid, token, amount=None, previous_token=None):
        if self.busy or self.current_operation:
            return
        request = {
            "operation_id":str(uuid.uuid4()),"kind":kind,"card_uid":uid,
            "token_uuid":token,"amount":None if amount is None else str(amount),
            "previous_token":previous_token,"state":"PENDING","stage":"PREPARED",
        }
        # Retain the same ID on errors and retries so one confirmation cannot credit money twice.
        self.current_operation = request["operation_id"]
        self.operation_request = request
        self.pending = None
        self._run_request(request)

    # Check the durable result first, then resume only the remaining work.
    def _run_request(self, request):
        self._busy(True)
        self.recover_button.hide()
        set_banner(self.notice,"warning","Processing • กำลังดำเนินการ กรุณาวางบัตรไว้และรอผล")
        def execute():
            operation_id, uid = request["operation_id"], request["card_uid"]
            # Always look up the durable result before touching the card again.
            # A saved final result can be displayed even if the physical card has already been removed.
            op = self.store.operation(operation_id)
            if op and op["state"] in ("DONE","CANCELLED"):
                return dict(op["result"] or {"success":False,"reason":"OPERATION_CANCELLED"})
            if not self._compatible_worker():
                raise CashierError("WORKER_UPDATE_REQUIRED")
            if not op:
                self.worker.check_configuration()
                if request["kind"] == "ISSUE":
                    self.worker.read_current_card(uid)
                else:
                    self.worker.verify_current_card(uid,request["token_uuid"])
                # Commit the planned request separately before any card write or balance update.
                op = self.store.prepare(operation_id,request["kind"],uid,request["token_uuid"],
                                        request.get("amount"),request.get("previous_token"))
            if op["terminal_id"] != self.terminal_id:
                raise CashierError("WRONG_TERMINAL")
            if op["kind"] == "ISSUE":
                if not op.get("token_uuid"):
                    # Older requests without a saved token may only be resolved
                    # against the actual card, never from cached screen values.
                    snap = self.worker.read_current_card(uid)
                    token = snap[2] if snap[1] else str(uuid.uuid4())
                    old = self.store.wallet(token) if snap[1] else None
                    if old:
                        raise CashierError("LEGACY_RECOVERY_REQUIRES_REVIEW")
                    op = self.store.adopt_issue_token(operation_id,token)
                self.worker.read_current_card(uid)
                # Persist the writing stage before touching tag memory; interrupted writes must be recoverable.
                self.store.mark_writing(operation_id)
                # Pass the saved token back to the reader: recovery must not generate another token.
                success, result = self.worker.provision_active_card(expected_uid=uid,token_uuid=op["token_uuid"])
                if not success:
                    raise CashierError(result)
                # Only register the wallet after the worker has written and verified the complete signed NDEF record.
                return self.store.finish_issue(operation_id,uid,op["token_uuid"])
            # Check the actual physical UID, token, and HMAC immediately before financial execution.
            self.worker.verify_current_card(uid,op["token_uuid"])
            # Once SQL starts, card removal must not start a replacement request.
            # The database atomically updates the wallet, ledger, and final result.
            return self.store.execute_financial(operation_id)
        self._job(execute, self._finish_result, self._request_failed)

    # Report configuration/business errors; keep uncertain writes in the recovery workflow.
    def _request_failed(self):
        self._busy(False)
        error = str(self.last_error).splitlines()[0]
        known = {
            "SECRET_KEY_NOT_CONFIGURED": (
                "ยังไม่ได้ตั้งค่า FOODCOURT_SECRET_KEY (อย่างน้อย 32 ตัวอักษร) "
                "ให้ตั้งค่า Secret Key ชุดเดียวกันในทุกส่วนของระบบ แล้วเปิดโปรแกรมใหม่"
            ),
            "WORKER_UPDATE_REQUIRED": "กรุณาใช้ไฟล์ส่วนติดต่อเครื่องอ่านชุดเดียวกับแอปนี้",
            "CARD_ALREADY_ACTIVE": "บัตรนี้ยังใช้งานอยู่ ไม่อนุญาตให้ออกบัตรซ้ำ",
            "CARD_NOT_AVAILABLE": "บัตรนี้ยังไม่พร้อมออกให้ลูกค้ารายใหม่",
            "PENDING_OPERATION_EXISTS": "มีรายการเดิมที่ยังไม่เสร็จ กรุณากดตรวจสอบรายการก่อนหน้า",
            "WRONG_TERMINAL": "รายการนี้เป็นของจุดบริการอื่น กรุณาให้ผู้ดูแลตรวจสอบ",
        }
        if error in known:
            self._clear_operation()
            set_banner(self.notice, "error", known[error])
            self._details()
            return
        self._unknown(
            "ยังยืนยันผลการลงทะเบียนไม่ได้ กรุณากดตรวจสอบรายการก่อนหน้า "
            "และอย่าเพิ่งนำบัตรไปใช้หรือเริ่มรายการใหม่"
        )

    # Show values from the saved result, not a stale preview or assumed outcome.
    def _finish_result(self, result):
        request = self.operation_request or {}
        kind, uid = request.get("kind"), request.get("card_uid")
        self._busy(False)
        self.db_ready = True
        set_pill(self.db_label,"ready","Database: Connected")
        self.db_retry.hide()
        if not result.get("success"):
            self._transaction_failure(result.get("reason"))
            return
        token = result.get("token") or request.get("token_uuid")
        self._clear_operation()
        if kind == "ISSUE":
            self.blocked_uid = None
            self.issue_card.setText(f"Card ID: {uid}")
            new_status = result.get("status", "ACTIVE")
            new_balance = result.get("balance", "0.00")
            self.issue_balance.setText(f"Starting Balance: {money(new_balance)}")
            self.issue_status.setText(f"Card Status: {new_status}")
            self.issue_heading.setText(
                "Card Re-registration Successful"
                if result.get("reissued") else "Card Setup Successful"
            )
            if self.uid == uid:
                self.token, self.valid, self.card_status = token, True, "TOKEN_VERIFIED"
            if new_status == "ACTIVE":
                set_banner(
                    self.notice, "success",
                    f"Card Registration Successful • ลงทะเบียน Token ใหม่สำเร็จ ยอดคงเหลือ {money(new_balance)}",
                )
            else:
                set_banner(
                    self.notice, "warning",
                    f"เขียน Token ใหม่แล้วและรักษายอด {money(new_balance)} ไว้ แต่บัญชีเดิมถูกระงับ จึงยังใช้จ่ายไม่ได้",
                )
        elif kind == "TOP_UP":
            # After a financial success, require a new interaction before another request for that card.
            self.blocked_uid = uid
            self.topup_card.setText(f"Card ID: {uid}")
            self.old_balance.setText(money(result["before"]))
            self.add_balance.setText(money(result["amount"]))
            self.new_balance.setText(money(result["balance"]))
            set_banner(self.notice,"success",
                f"Top Up Successful • เติมเงินสำเร็จ {money(result['amount'])} • ยอดคงเหลือ {money(result['balance'])} • นำบัตรออกได้")
        else:
            # After a financial success, require a new interaction before another request for that card.
            self.blocked_uid = uid
            self.return_card.setText(f"Card ID: {uid}")
            self.return_amount.setText(money(result["amount"]))
            self.return_status.setText("Card Status: Returned • Balance ฿0.00")
            set_banner(self.notice,"success",
                f"Card Returned • คืนเงินสด {money(result['amount'])} ให้ลูกค้าและเก็บบัตรไว้")
        self._details()
        self._refresh_history()



# ENTRY POINT: importing ConfirmationDialog for preview does not start the Cashier application.
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Tahoma", 10))

    window = CashierApp()
    window.showMaximized()

    sys.exit(app.exec())
