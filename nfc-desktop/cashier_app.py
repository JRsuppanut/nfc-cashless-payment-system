"""Food Court Cashier UI.

Replace the project's ``cashier_app.py`` with this entire file. It uses the
existing ``database.py`` and ``nfc_worker.py`` files. Only card setup writes NFC; 
top-up and return update PostgreSQL while requiring the same physical card 
to remain on the reader until the commit is confirmed.
"""

import sys
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QDialog, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QHeaderView,
)
from psycopg2.extras import DictCursor, Json

import database
from nfc_worker import NFCWorker, DEFAULT_PORT


STYLE = """
QWidget {
    font-family: 'Tahoma';
    font-size: 14px;
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
    color: #728095;
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 13px;
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
    font-size: 14px;
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


def money(value):
    return f"฿{Decimal(str(value)):,.2f}"


def label(text="", name=None):
    item = QLabel(text)
    item.setWordWrap(True)
    if name:
        item.setObjectName(name)
    return item


def panel():
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


def set_banner(widget, tone, text):
    widget.setProperty("tone", tone)
    widget.setText(("● " if not str(text).lstrip().startswith("●") else "") + str(text))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


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


def icon(kind, color, size=36):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 36, size / 36)
    painter.setPen(QPen(QColor(color), 2.5))

    if kind == 0:
        painter.drawRoundedRect(3, 7, 25, 20, 3, 3)
        painter.drawLine(4, 13, 27, 13)
        painter.drawLine(29, 23, 29, 33)
        painter.drawLine(24, 28, 34, 28)
    elif kind == 1:
        for y in (24, 18, 12):
            painter.drawEllipse(4, y, 19, 8)
        painter.drawEllipse(14, 3, 18, 8)
        painter.drawLine(14, 7, 14, 16)
        painter.drawLine(32, 7, 32, 18)
        painter.drawArc(14, 14, 18, 8, 180 * 16, 180 * 16)
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


class CashierStore:
    """Cashier-side transactional layer with idempotent writes."""

    def initialize(self):
        database.initialize_database()
        with database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cashier_ui_operations (
                        operation_id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        token_uuid TEXT,
                        card_uid TEXT NOT NULL,
                        amount NUMERIC(10,2),
                        state TEXT NOT NULL DEFAULT 'PENDING',
                        result JSONB,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS cashier_ui_operations_state
                    ON cashier_ui_operations(state, created_at)
                """)
            conn.commit()

    def wallet(self, token):
        if not token:
            return None
        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM wallets WHERE token_uuid=%s",
                    (token,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def latest_wallet(self, uid):
        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM wallets WHERE card_uid=%s
                    ORDER BY created_at DESC, updated_at DESC LIMIT 1
                """, (uid,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def begin_issue(self, operation_id, uid, previous_token=None):
        with database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO cashier_ui_operations
                        (operation_id,kind,token_uuid,card_uid,state)
                    VALUES(%s,'ISSUE',%s,%s,'PENDING')
                    ON CONFLICT(operation_id) DO NOTHING
                """, (operation_id, None, uid))
            conn.commit()

    def attach_issue_token(self, operation_id, uid, token):
        with database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE cashier_ui_operations
                    SET token_uuid=%s,updated_at=CURRENT_TIMESTAMP
                    WHERE operation_id=%s AND card_uid=%s
                      AND kind='ISSUE' AND state='PENDING'
                """, (token, operation_id, uid))
                if cursor.rowcount != 1:
                    raise RuntimeError('ISSUE_OPERATION_NOT_PENDING')
            conn.commit()

    def finish_issue(self, operation_id, uid, token):
        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM cashier_ui_operations
                    WHERE operation_id=%s FOR UPDATE
                """, (operation_id,))
                operation = cursor.fetchone()
                if not operation:
                    raise RuntimeError('ISSUE_OPERATION_NOT_FOUND')
                if operation['state'] == 'DONE':
                    return dict(operation['result'])
                if operation['state'] != 'PENDING':
                    raise RuntimeError('ISSUE_OPERATION_NOT_PENDING')
                if operation['card_uid'] != uid:
                    raise RuntimeError('CARD_CHANGED')

                cursor.execute("""
                    INSERT INTO wallets
                        (token_uuid,card_uid,balance,status,created_at,updated_at)
                    VALUES(%s,%s,0,'ACTIVE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT(token_uuid) DO NOTHING
                """, (token, uid))
                cursor.execute("""
                    SELECT card_uid,balance,status FROM wallets
                    WHERE token_uuid=%s FOR UPDATE
                """, (token,))
                wallet = cursor.fetchone()
                if (
                    not wallet or wallet['card_uid'] != uid
                    or wallet['status'] != 'ACTIVE'
                    or Decimal(str(wallet['balance'])) != Decimal('0')
                ):
                    raise RuntimeError('WALLET_REGISTRATION_FAILED')

                cursor.execute("""
                    SELECT 1 FROM transaction_ledger
                    WHERE token_uuid=%s AND action_type='SETUP_CARD'
                """, (token,))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO transaction_ledger
                            (token_uuid,card_uid,terminal_type,action_type,
                             amount,balance_after,timestamp)
                        VALUES(%s,%s,'CASHIER','SETUP_CARD',0,0,CURRENT_TIMESTAMP)
                    """, (token, uid))
                result = {
                    'success': True, 'token': token, 'uid': uid,
                    'balance': '0.00', 'status': 'ACTIVE',
                }
                cursor.execute("""
                    UPDATE cashier_ui_operations
                    SET state='DONE',result=%s,token_uuid=%s,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE operation_id=%s
                """, (Json(result), token, operation_id))
            conn.commit()
            return result

    def _financial(self, operation_id, kind, token, uid, amount=None):
        if kind not in ('TOP_UP', 'RETURN_CARD'):
            raise ValueError('UNSUPPORTED_OPERATION')
        requested = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
        if kind == 'TOP_UP' and requested <= 0:
            return {'success': False, 'reason': 'INVALID_AMOUNT'}

        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    INSERT INTO cashier_ui_operations
                        (operation_id,kind,token_uuid,card_uid,amount,state)
                    VALUES(%s,%s,%s,%s,%s,'PENDING')
                    ON CONFLICT(operation_id) DO NOTHING
                """, (operation_id, kind, token, uid,
                       requested if kind == 'TOP_UP' else None))
                cursor.execute("""
                    SELECT * FROM cashier_ui_operations
                    WHERE operation_id=%s FOR UPDATE
                """, (operation_id,))
                operation = cursor.fetchone()
                if not operation:
                    raise RuntimeError('OPERATION_NOT_FOUND')
                if (
                    operation['kind'] != kind
                    or operation['token_uuid'] != token
                    or operation['card_uid'] != uid
                ):
                    raise RuntimeError('OPERATION_REQUEST_MISMATCH')
                if kind == 'TOP_UP' and Decimal(str(operation['amount'])) != requested:
                    raise RuntimeError('OPERATION_AMOUNT_MISMATCH')
                if operation['state'] == 'DONE':
                    return dict(operation['result'])
                if operation['state'] != 'PENDING':
                    return {'success': False, 'reason': 'OPERATION_CANCELLED'}

                cursor.execute("""
                    SELECT card_uid,balance,status FROM wallets
                    WHERE token_uuid=%s FOR UPDATE
                """, (token,))
                wallet = cursor.fetchone()
                if not wallet:
                    result = {'success': False, 'reason': 'WALLET_NOT_FOUND'}
                elif wallet['card_uid'] != uid:
                    result = {'success': False, 'reason': 'CARD_ID_MISMATCH'}
                elif wallet['status'] != 'ACTIVE':
                    result = {'success': False, 'reason': 'CARD_NOT_ACTIVE'}
                else:
                    before = Decimal(str(wallet['balance'])).quantize(Decimal('0.01'))
                    if kind == 'TOP_UP':
                        after = before + requested
                        if after > Decimal('99999999.99'):
                            result = {'success': False, 'reason': 'BALANCE_LIMIT'}
                        else:
                            cursor.execute("""
                                UPDATE wallets SET balance=%s,updated_at=CURRENT_TIMESTAMP
                                WHERE token_uuid=%s
                            """, (after, token))
                            cursor.execute("""
                                INSERT INTO transaction_ledger
                                    (token_uuid,card_uid,terminal_type,action_type,
                                     amount,balance_after,timestamp)
                                VALUES(%s,%s,'CASHIER','TOP_UP',%s,%s,CURRENT_TIMESTAMP)
                            """, (token, uid, requested, after))
                            result = {
                                'success': True, 'reason': 'SUCCESS',
                                'amount': str(requested), 'before': str(before),
                                'balance': str(after),
                            }
                    else:
                        refund = before
                        cursor.execute("""
                            UPDATE wallets
                            SET balance=0,status='AVAILABLE',updated_at=CURRENT_TIMESTAMP
                            WHERE token_uuid=%s
                        """, (token,))
                        cursor.execute("""
                            INSERT INTO transaction_ledger
                                (token_uuid,card_uid,terminal_type,action_type,
                                 amount,balance_after,timestamp)
                            VALUES(%s,%s,'CASHIER','REFUND_RETURN',%s,0,CURRENT_TIMESTAMP)
                        """, (token, uid, refund))
                        result = {
                            'success': True, 'reason': 'SUCCESS',
                            'amount': str(refund), 'before': str(before),
                            'balance': '0.00', 'status': 'AVAILABLE',
                        }

                cursor.execute("""
                    UPDATE cashier_ui_operations
                    SET state='DONE',result=%s,updated_at=CURRENT_TIMESTAMP
                    WHERE operation_id=%s
                """, (Json(result), operation_id))
            conn.commit()
            return result

    def top_up(self, operation_id, token, uid, amount):
        return self._financial(operation_id, 'TOP_UP', token, uid, amount)

    def return_card(self, operation_id, token, uid):
        return self._financial(operation_id, 'RETURN_CARD', token, uid)

    def operation(self, operation_id):
        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM cashier_ui_operations WHERE operation_id=%s",
                    (operation_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def pending_operations(self):
        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM cashier_ui_operations
                    WHERE state='PENDING' ORDER BY created_at
                """)
                return [dict(row) for row in cursor.fetchall()]

    def cancel_operation(self, operation_id, reason):
        result = {'success': False, 'reason': reason}
        with database.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE cashier_ui_operations
                    SET state='CANCELLED',result=%s,updated_at=CURRENT_TIMESTAMP
                    WHERE operation_id=%s AND state='PENDING'
                """, (Json(result), operation_id))
            conn.commit()
        return result

    def history(self, limit=300, token=None):
        with database.get_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cursor:
                cursor.execute("""
                    SELECT transaction_id,token_uuid,card_uid,terminal_type,
                           action_type,amount,balance_after,timestamp,
                           'COMPLETED' AS operation_status
                    FROM transaction_ledger
                    WHERE (%s IS NULL OR token_uuid=%s)
                    ORDER BY transaction_id DESC LIMIT %s
                """, (token, token, limit))
                return [dict(row) for row in cursor.fetchall()]


class ModeButton(QPushButton):
    def __init__(self, index, english, thai=""):
        super().__init__()
        self.index = index
        self.setObjectName("mode")
        self.setCheckable(True)
        self.setMinimumHeight(70)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)

        self.picture = QLabel()
        self.picture.setFixedSize(36, 36)
        row.addWidget(self.picture)

        texts = QVBoxLayout()
        texts.setSpacing(4)

        self.english = QLabel(english)
        self.thai = QLabel(thai)
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
            f"color: {'#d8f4e9' if checked else '#728095'};"
            "font-size: 11px;"
        )


class NFCBridge(QObject):
    tag = pyqtSignal(str, bool, object, str)
    removed = pyqtSignal()

    def emit_tag(self, uid, valid, token, status):
        self.tag.emit(uid, valid, token, status)

    def emit_removal(self):
        self.removed.emit()


class Job(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal()

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception:
            self.error.emit()


class CashierApp(QMainWindow):
    MODE_ISSUE, MODE_TOPUP, MODE_CHECK, MODE_RETURN = range(4)
    HISTORY_LIMIT = 200
    MAX_BALANCE = Decimal("99999999.99")

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
        self.store = CashierStore()

        self.bridge = NFCBridge()
        self.bridge.tag.connect(self._tag_detected)
        self.bridge.removed.connect(self._tag_removed)

        self._build_ui()

        self.worker = NFCWorker(
            on_tag_detected=self.bridge.emit_tag,
            on_tag_removed=self.bridge.emit_removal,
        )
        self.worker.start()

        self.reader_timer = QTimer(self)
        self.reader_timer.timeout.connect(self._reader_state)
        self.reader_timer.start(800)

        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self._auto_history)
        self.history_timer.start(15000)

        self._initialize_db()
        self._empty_views()

    def _job(self, function, done, failed):
        job = Job(function, self)
        self.jobs.add(job)

        job.result.connect(done)
        job.error.connect(failed)
        job.finished.connect(lambda j=job: self.jobs.discard(j))
        job.finished.connect(job.deleteLater)
        job.start()

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

        terminal = label("CASHIER-01", "section")
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
        self.details_dialog.resize(580, 250)

        dialog_box = QVBoxLayout(self.details_dialog)
        dialog_box.addWidget(label(
            "Token UUID แสดงเต็มสำหรับทดสอบเว็บ"
            " • ไม่ใช่ข้อมูลที่ต้องแสดงให้ลูกค้าดู",
            "muted",
        ))

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

    def _single_page(self):
        frame, box = panel()
        self.mode_stack.addWidget(frame)
        return box

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
        issue_note = label(
            "บัตรที่รับคืนจะได้รับ Token และรอบการใช้งานใหม่ "
            "ประวัติของลูกค้ารอบก่อนจะไม่ปะปนกับรอบใหม่",
            "muted",
        )
        box.addWidget(issue_note)
        box.addStretch()

        right, steps = panel()
        steps.addWidget(label("Card Setup Summary", "section"))
        steps.addWidget(label("1  Place card on reader", "cardHeading"))
        steps.addWidget(label("วางบัตรบนเครื่องอ่าน", "muted"))
        steps.addWidget(label("2  Review card status", "cardHeading"))
        steps.addWidget(label("ตรวจสอบว่าเป็นบัตรใหม่หรือบัตรที่รับคืนแล้ว", "muted"))
        steps.addWidget(label("3  Confirm and keep card in place", "cardHeading"))
        steps.addWidget(label("วางบัตรไว้จนเขียนและตรวจสอบสำเร็จ", "muted"))
        steps.addStretch()

        row.addWidget(left, 60)
        row.addWidget(right, 40)
        self.mode_stack.addWidget(page)

        self.issue_confirm, self.issue_cancel = (
            self._action_buttons(
                "Confirm and Set Up Card",
                self._issue,
                "ยังไม่เขียนข้อมูลลงบัตรจนกดยืนยัน",
            )
        )

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
            "รับเงินสดแล้วกดยืนยัน โดยวางบัตรไว้เพื่อยืนยันว่าเป็นใบเดิม\n"
            "โหมดนี้เปลี่ยนเฉพาะยอดใน Database ไม่ได้เขียน NFC",
            "muted",
        ))

        self.topup_confirm, self.topup_cancel = (
            self._action_buttons(
                "รับเงินสดแล้ว • ยืนยันเติมเงิน",
                self._topup,
                "วางบัตรไว้จน Database บันทึกรายการสำเร็จ",
            )
        )

        row.addWidget(left, 55)
        row.addWidget(right, 45)
        self.mode_stack.addWidget(page)

    def _build_check(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)

        left, box = panel()
        box.addWidget(label("Check Card Balance", "section"))
        box.addWidget(label(
            "แตะบัตรเพื่ออ่านยอดเงินล่าสุดจาก Database",
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
            "ยอดที่แสดงเป็นยอดเมื่ออ่านล่าสุด ไม่ได้เปลี่ยนยอดเงินในบัตร",
            "muted",
        ))
        self.check_cycle = label("Usage Cycle: —")
        summary.addWidget(self.check_cycle)
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
        summary.addWidget(label("Database Balance", "muted"))
        self.return_after = label("฿0.00", "largeValue")
        summary.addWidget(self.return_after)
        summary.addWidget(label("Usage Cycle Status", "muted"))
        self.return_after_status = label("AVAILABLE / Ready for reuse", "cardHeading")
        summary.addWidget(self.return_after_status)
        summary.addWidget(label(
            "รายการนี้แก้ยอดและสถานะใน Database เท่านั้น ไม่ได้เขียน NFC\n"
            "แต่ต้องวางบัตรไว้เพื่อยืนยันว่าเป็นบัตรใบเดิมจนบันทึกสำเร็จ",
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
                "คืนเงินคงเหลือในบัตร ไม่ใช่การคืนค่าอาหาร • วางบัตรไว้จนสำเร็จ",
            )
        )

    def _build_history(self):
        page, box = panel()

        head = QHBoxLayout()
        head.addWidget(label("Transaction History", "section"))
        head.addStretch()

        self.show_all = QPushButton("Back to All Transactions")
        self.show_all.clicked.connect(self._all_history)
        head.addWidget(self.show_all)

        self.history_refresh = QPushButton("รีเฟรช")
        self.history_refresh.clicked.connect(self._refresh_history)
        head.addWidget(self.history_refresh)
        box.addLayout(head)

        self.history_title = label("รายการทั้งหมด", "section")
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

    def _toggle_details(self):
        self._details()
        self.details_dialog.show()
        self.details_dialog.raise_()

    def _details(self):
        self.details.setPlainText(
            f"NFC port: {DEFAULT_PORT}\n"
            f"Card ID: {self.uid or '—'}\n"
            f"Token UUID: {self.token or '—'}\n"
            f"NFC status: {self.card_status or '—'}"
        )

    def _initialize_db(self):
        if self.busy or self.uncertain:
            return

        self.db_ready = False
        self.db_retry.setEnabled(False)
        set_pill(self.db_label, "warning", "Database: Connecting…")
        self._disable_actions()

        def initialize_and_find_pending():
            self.store.initialize()
            return self.store.pending_operations()

        def done(pending_operations):
            self.db_ready = True
            set_pill(self.db_label, "ready", "Database: Connected")
            self.db_retry.hide()
            self.db_retry.setEnabled(True)
            if pending_operations:
                pending = dict(pending_operations[0])
                self.current_operation = pending["operation_id"]
                kind = pending["kind"]
                self.operation_request = {
                    "kind": kind,
                    "uid": pending["card_uid"],
                }
                if kind == "ISSUE":
                    self.operation_request.update(
                        old_token=None,
                        new_token=pending.get("token_uuid"),
                    )
                else:
                    self.operation_request["token"] = pending.get("token_uuid")
                    if kind == "TOP_UP":
                        self.operation_request["amount"] = str(pending.get("amount"))
                self.uncertain = True
                self.recover_button.show()
                set_banner(
                    self.notice,
                    "error",
                    f"Unfinished {kind.replace('_', ' ').title()} • พบรายการเดิมที่ยังยืนยันผลไม่ได้ "
                    "แตะบัตรใบเดิมแล้วกดตรวจสอบรายการก่อนหน้า",
                )
                self._disable_actions()
                self._refresh_history()
                return
            self._reload_card()
            self._refresh_history()

        self._job(
            initialize_and_find_pending,
            done,
            self._db_failed,
        )

    def _db_failed(self):
        self.db_ready = False
        self.pending = None
        set_pill(self.db_label, "error", "Database: Unavailable")
        self.db_retry.show()
        self.db_retry.setEnabled(True)
        self._disable_actions()
        set_banner(self.notice, "error",
            "เชื่อมต่อฐานข้อมูลไม่ได้ ตรวจสอบ PostgreSQL"
            " แล้วกดเชื่อมต่อฐานข้อมูลใหม่"
        )

    def _reader_state(self):
        connection = getattr(self.worker, "_serial_conn", None)
        ready = bool(
            self.worker.is_alive()
            and getattr(self.worker, "_pn532", None)
            and connection
            and connection.is_open
        )

        set_pill(
            self.reader_label,
            "ready" if ready else "error",
            "Reader: Ready" if ready else "Reader: Disconnected",
        )
        self.reader_label.setToolTip(
            f"พอร์ต NFC: {DEFAULT_PORT}"
            " • ตรวจสอบสายและอุปกรณ์หากไม่พร้อม"
        )
        if ready == self.reader_ready:
            return

        self.reader_ready = ready
        if not ready:
            self._tag_removed()
        elif not self.busy and not self.uncertain:
            if self.uid:
                self._reload_card()
            else:
                self._idle_notice()

    def _idle_notice(self):
        if self.uncertain:
            set_banner(self.notice, "error",
                "ต้องตรวจสอบผลรายการก่อนทำต่อ"
                " ดูประวัติและอย่าทำรายการเดิมซ้ำ"
            )
        elif not self.db_ready:
            set_banner(self.notice, "warning", "Waiting for Database • รอฐานข้อมูลพร้อมก่อนทำรายการ")
        elif not self.reader_ready:
            set_banner(self.notice, "warning",
                "NFC Reader Not Ready • ยังทำรายการบัตรไม่ได้ เครื่องอ่านไม่พร้อม"
                " แต่เปิดดูประวัติได้"
            )
        elif self.blocked_uid and self.uid == self.blocked_uid:
            set_banner(self.notice, "success",
                "Transaction Completed • นำบัตรออกก่อน แล้วแตะใหม่เพื่อเริ่มรายการถัดไป"
            )
        elif self.mode == self.MODE_CHECK:
            set_banner(self.notice, "info",
                "Waiting for Card • แตะบัตรเพื่อตรวจสอบยอดเงิน"
                " • อ่านสำเร็จแล้วนำบัตรออกได้"
            )
        elif self.mode == self.MODE_ISSUE:
            set_banner(self.notice, "info",
                "Ready for a New Card • แตะบัตรใหม่หรือบัตรหมุนเวียนที่รับคืนแล้ว"
            )
        elif self.mode == self.MODE_TOPUP:
            set_banner(self.notice, "info",
                "Ready to Add Money • เลือกจำนวนเงิน แล้วแตะบัตรและวางไว้จนรายการสำเร็จ"
            )
        else:
            set_banner(self.notice, "warning",
                "Ready to Return Card • แตะบัตรและวางไว้บนเครื่องอ่าน"
                " จนคืนเงิน รับบัตร และบันทึกรายการสำเร็จ"
            )

    def _disable_actions(self):
        for button in (
            self.issue_confirm,
            self.topup_confirm,
            self.return_confirm,
            self.topup_prepare,
        ):
            button.setEnabled(False)

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
            self.check_cycle.setText("Usage Cycle: —")
            self.check_time.setText("")
            self.card_history.setEnabled(False)

        self._details()
        self._idle_notice()

    def _navigate(self, index):
        if self.busy:
            return

        self.pages.setCurrentIndex(index)
        self.operation_nav.setChecked(index == 0)
        self.history_nav.setChecked(index == 1)

        if index == 1:
            self._cancel_pending()
            self._refresh_history()
        elif self.uid:
            self._reload_card()
        else:
            self._idle_notice()

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

    def _cancel_pending(self):
        self.epoch += 1
        self.pending = None
        self._disable_actions()

    def _cancel(self):
        if self.busy or self.uncertain:
            return

        if self.uid:
            self.blocked_uid = self.uid

        self._cancel_pending()
        self._empty_views()
        self.notice.setText(
            "ยกเลิกรายการที่ยังไม่ยืนยันแล้ว"
            " • นำบัตรออกก่อนเริ่มใหม่"
        )

    def _next_card(self):
        if self.uid:
            self.blocked_uid = self.uid

        self._cancel_pending()
        self._empty_views()

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

    def _choose_amount(self, value):
        self.amount.setText(f"{value:.2f}")
        for button in self.preset_buttons:
            button.setChecked(
                button.text().replace(",", "") == str(value),
            )

    def _can_read(self):
        return bool(
            self.uid
            and self.db_ready
            and self.reader_ready
            and not self.busy
            and not self.uncertain
            and self.uid != self.blocked_uid
            and self.pages.currentIndex() == 0
        )

    def _tag_detected(self, uid, valid, token, status):
        self.epoch += 1
        self.uid = uid
        self.valid = valid
        self.token = token
        self.card_status = status
        self.wallet = None
        self.pending = None

        if self.busy:
            self._details()
            return

        self._empty_views()
        self._reload_card()

    def _tag_removed(self):
        self.epoch += 1
        self.uid = None
        self.token = None
        self.valid = False
        self.card_status = ""
        self.wallet = None
        self.pending = None
        self.blocked_uid = None

        if self.busy:
            self._details()
            return

        keep = (
            self.mode == self.MODE_CHECK
            and self.checked_uid is not None
        )
        self._empty_views(preserve_check=keep)

        if keep and not self.uncertain:
            set_banner(self.notice, "success",
                "Card Read Successfully • นำบัตรออกแล้ว"
                " • ยอดที่แสดงคือยอดเมื่ออ่านล่าสุด"
                " ไม่ใช่การอ่านแบบสด"
            )

    def _reload_card(self):
        self._disable_actions()

        if not self._can_read():
            self._idle_notice()
            return

        self.epoch += 1
        generation = self.epoch
        self.pending = None
        self.wallet = None

        uid, token, mode = self.uid, self.token, self.mode
        self._details()

        for item in (
            self.issue_card, self.topup_card, self.return_card,
        ):
            item.setText(f"Card ID: {uid}")

        if not self.valid or not token:
            if self.card_status != "FOREIGN_OR_UNINITIALIZED_CARD":
                self.issue_status.setText("Card Status: Verification Failed")
                set_banner(self.notice, "error",
                    "Card Verification Failed • ไม่อนุญาตให้ทำรายการกับบัตรนี้"
                )
                return

            set_banner(self.notice, "info", "Checking Card Registration… • กำลังตรวจสอบบัตร")

            def unregistered_done(latest):
                if generation != self.epoch or not self._can_read():
                    return
                if latest and latest.get("status") == "ACTIVE":
                    self.issue_status.setText("Card Status: Active record found")
                    set_banner(self.notice, "error",
                        "Card Data Cannot Be Verified • พบรายการที่ยังใช้งานอยู่ใน Database "
                        "กรุณาให้ผู้ดูแลตรวจสอบ ห้ามออกบัตรซ้ำ"
                    )
                    return
                if mode == self.MODE_ISSUE:
                    self.issue_heading.setText("Ready for a New Card")
                    self.issue_status.setText(
                        "Card Status: Returned / Ready for setup" if latest
                        else "Card Status: New / Not registered"
                    )
                    self.issue_confirm.setEnabled(True)
                    set_banner(self.notice, "info",
                        "Ready for a New Card • ตรวจสอบแล้วกดยืนยัน "
                        "และวางบัตรไว้จนเขียนข้อมูลสำเร็จ"
                    )
                else:
                    set_banner(self.notice, "error",
                        "Card Not Registered • บัตรนี้ยังไม่มีรอบการใช้งาน "
                        "ให้ไปที่ Set Up a New Card ก่อน"
                    )

            self._job(lambda: self.store.latest_wallet(uid), unregistered_done, failed=lambda: self._db_failed())
            return

        set_banner(self.notice, "info", "Checking Card… • กำลังตรวจสอบข้อมูลบัตร")

        def done(wallet):
            if generation != self.epoch or not self._can_read():
                return

            if wallet and wallet.get("card_uid") != uid:
                set_banner(self.notice, "error",
                    "Card ID ไม่ตรงกับข้อมูลบัตรในฐานข้อมูล"
                    " • ไม่อนุญาตให้ทำรายการ"
                )
                return

            if not wallet:
                set_banner(self.notice, "error",
                    "Card Record Not Found • Token บนบัตรผ่านการตรวจสอบ "
                    "แต่ไม่พบใน Database กรุณาให้ผู้ดูแลตรวจสอบ"
                )
                return

            self.wallet = wallet
            self._display_wallet(wallet)

        def failed():
            if generation == self.epoch:
                self._db_failed()

        self._job(
            lambda: self.store.wallet(token),
            done,
            failed,
        )

    def _display_wallet(self, wallet):
        if self.mode == self.MODE_ISSUE:
            allowed = not wallet or (
                wallet.get("status") == "AVAILABLE"
                and Decimal(str(wallet.get("balance", 0))) == 0
            )
            self.issue_confirm.setEnabled(allowed)
            self.issue_status.setText(
                "Card Status: Returned / Ready for setup" if allowed
                else "Card Status: Active"
            )
            set_banner(
                self.notice,
                "info" if allowed else "error",
                "Ready for a New Card • วางบัตรไว้จนรายการสำเร็จ"
                if allowed else
                "Card Already Active • บัตรนี้ยังใช้งานอยู่ ต้องคืนบัตรก่อนออกบัตรรอบใหม่",
            )
            return

        if not wallet:
            set_banner(self.notice, "error", "Wallet Not Found • ตรวจสอบการออกบัตรก่อน")
            return

        balance = Decimal(str(wallet.get("balance", 0)))
        state = wallet.get("status", "")
        state_text = {
            "ACTIVE": "ใช้งานได้",
            "AVAILABLE": "คืนบัตรแล้ว",
            "SUSPENDED": "ระงับการใช้งาน",
        }.get(state, state)

        if self.mode == self.MODE_CHECK:
            self.checked_uid = self.uid
            self.checked_token = self.token
            self.check_card.setText(f"Card ID: {self.uid}")
            self.check_balance.setText(money(balance))
            self.check_status.setText(f"Card Status: {state_text}")
            self.check_cycle.setText(f"Usage Cycle: {str(self.token)[:8]}…")
            self.check_time.setText(
                f"อ่านล่าสุด {datetime.now():%d/%m/%Y %H:%M:%S}",
            )
            self.card_history.setEnabled(True)
            set_banner(self.notice, "success",
                "Balance Read Successfully • อ่านยอดเงินแล้ว"
                " • นำบัตรออกได้ หรือเปิดดูประวัติของบัตรนี้"
            )

        elif self.mode == self.MODE_RETURN:
            self.return_amount.setText(money(balance))
            self.return_status.setText(f"Card Status: {state_text}")
            self.return_confirm.setText(
                f"คืนเงินสด {money(balance)} • ยืนยันคืนบัตร"
            )
            self.return_confirm.setEnabled(
                state == "ACTIVE" and balance >= 0,
            )
            set_banner(self.notice, "warning" if state == "ACTIVE" else "error",
                "Review Refund and Confirm • ตรวจสอบยอดคืน แล้วกดยืนยัน"
                " • วางบัตรไว้จนสำเร็จ"
                if state == "ACTIVE" else
                "Card Cannot Be Returned • บัตรนี้ไม่อยู่ในสถานะที่คืนบัตรได้"
            )

        else:
            self.old_balance.setText(money(balance))
            self.topup_status.setText(f"Card Status: {state_text}")

            if state != "ACTIVE":
                set_banner(self.notice, "error", "Card Cannot Be Topped Up • บัตรนี้ไม่อยู่ในสถานะที่เติมเงินได้")
                return

            try:
                amount = self._parse_amount()
            except ValueError as error:
                set_banner(self.notice, "error", str(error))
                return

            if balance + amount > self.MAX_BALANCE:
                set_banner(self.notice, "error",
                    "ยอดเงินหลังเติมเกินขนาดที่ฐานข้อมูลรองรับ",
                )
                return

            self.add_balance.setText(money(amount))
            self.new_balance.setText(money(balance + amount))
            self.topup_confirm.setText(
                f"รับเงินสด {money(amount)} • ยืนยันเติมเงิน"
            )
            self.pending = (self.uid, self.token, amount)
            self.topup_confirm.setEnabled(True)
            set_banner(self.notice, "warning",
                "Review and Confirm • ตรวจสอบจำนวนเงิน รับเงินสดแล้วจึงยืนยัน"
                " • วางบัตรไว้จนสำเร็จ"
            )

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

    def _confirm_identity(self, uid, token):
        return (
            self._can_read()
            and self.uid == uid
            and self.token == token
        )

    def _ask(self, title, message):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(message)

        yes = dialog.addButton(
            "ยืนยัน", QMessageBox.ButtonRole.AcceptRole,
        )
        no = dialog.addButton(
            "กลับไปตรวจสอบ", QMessageBox.ButtonRole.RejectRole,
        )
        dialog.setDefaultButton(no)
        dialog.exec()
        return dialog.clickedButton() == yes

    def _busy(self, enabled):
        self.busy = enabled

        buttons = self.mode_buttons + self.preset_buttons + [
            self.operation_nav,
            self.history_nav,
            self.issue_cancel,
            self.topup_cancel,
            self.return_cancel,
            self.next_card,
            self.card_history,
            self.db_retry,
        ]
        for button in buttons:
            button.setEnabled(not enabled)

        self.amount.setEnabled(not enabled)
        self._disable_actions()

        if not enabled:
            self.card_history.setEnabled(
                self.checked_uid is not None,
            )

    def _issue(self):
        if not self.issue_confirm.isEnabled() or not self._can_read():
            return

        uid, token = self.uid, self.token

        if not self._ask(
            "ยืนยันออกบัตร",
            f"ออกบัตร {uid}\nยอดเงินเริ่มต้น ฿0.00\nวางบัตรไว้จนรายการสำเร็จ"
        ):
            return

        if not self._confirm_identity(uid, token) or not self.issue_confirm.isEnabled():
            set_banner(self.notice, "error", "ข้อมูลบัตรเปลี่ยนแล้ว • นำบัตรออกแล้วแตะใหม่")
            return

        operation_id = str(uuid.uuid4())
        self.current_operation = operation_id
        self.operation_request = {
            "kind": "ISSUE", "uid": uid, "old_token": token,
            "new_token": None,
        }
        self._busy(True)
        set_banner(self.notice, "warning", "กำลังออกบัตร • ห้ามนำบัตรออกหรือปิดโปรแกรม")

        def operation():
            self.store.begin_issue(operation_id, uid, token)
            # Use the new active provisioning method
            success, new_token = self.worker.provision_active_card(expected_uid=uid)
            if not success:
                return self.store.cancel_operation(operation_id, new_token)
            self.operation_request["new_token"] = new_token
            self.store.attach_issue_token(operation_id, uid, new_token)
            return self.store.finish_issue(operation_id, uid, new_token)

        def done(result):
            if not result.get("success"):
                self._busy(False)
                self._clear_operation()
                set_banner(self.notice, "error", "เขียนหรือตรวจสอบบัตรไม่สำเร็จ นำบัตรออกแล้วลองใหม่")
                return

            new_token = result["token"]
            if self.uid == uid:
                self.token = new_token
                self.valid = True
                self.card_status = "TOKEN_VERIFIED"
                self.blocked_uid = uid

            self._busy(False)
            self._clear_operation()
            self._details()
            set_banner(self.notice, "success", "ออกบัตรสำเร็จ ยอดเงิน ฿0.00 • นำบัตรออก แล้วเลือกเติมเงินและแตะใหม่")
            self._refresh_history()

        self._job(
            operation,
            done,
            lambda: self._unknown("ไม่สามารถยืนยันผลการออกบัตรได้ อย่าออกบัตรซ้ำทันที")
        )

    def _topup(self):
        if (
            not self.pending
            or not self.topup_confirm.isEnabled()
        ):
            return

        snapshot = self.pending
        uid, token, amount = snapshot

        if not self._ask(
            "ยืนยันเติมเงิน",
            f"Card ID: {uid}\n"
            f"เติมเงิน {money(amount)}\n"
            "ได้รับเงินสดแล้วใช่ไหม?",
        ):
            return

        if (
            self.pending != snapshot
            or not self._confirm_identity(uid, token)
        ):
            set_banner(self.notice, "error",
                "ข้อมูลบัตรหรือจำนวนเงินเปลี่ยนแล้ว"
                " • ตรวจสอบสรุปใหม่ก่อนยืนยัน"
            )
            return

        operation_id = str(uuid.uuid4())
        self.current_operation = operation_id
        self.operation_request = {
            "kind": "TOP_UP", "uid": uid, "token": token,
            "amount": str(amount),
        }
        self.pending = None
        self._busy(True)
        set_banner(self.notice, "warning",
            "Saving Top Up • กำลังเติมเงิน"
            " • ห้ามนำบัตรออกหรือปิดโปรแกรม"
        )

        def done(result):
            if not result.get("success"):
                self._transaction_failure(result.get("reason"))
                return

            balance = Decimal(str(result["balance"]))
            self.blocked_uid = uid
            self._busy(False)
            self._clear_operation()
            self.new_balance.setText(money(balance))
            set_banner(self.notice, "success",
                f"Top Up Successful • เติมเงินสำเร็จ {money(amount)}"
                f" • ยอดคงเหลือ {money(balance)}"
                " • นำบัตรออกได้"
            )
            self._refresh_history()

        self._job(
            lambda: self.store.top_up(operation_id, token, uid, amount),
            done,
            lambda: self._unknown(
                "ติดต่อฐานข้อมูลขณะเติมเงินผิดพลาด"
                " ต้องตรวจสอบผลก่อนทำซ้ำ"
            ),
        )

    def _return_card(self):
        if (
            not self.return_confirm.isEnabled()
            or not self.wallet
        ):
            return

        uid, token = self.uid, self.token
        displayed_amount = self.wallet.get("balance", 0)

        if not self._ask(
            "ยืนยันคืนบัตร",
            f"Card ID: {uid}\n"
            f"ยอดคงเหลือที่อ่านล่าสุด {money(displayed_amount)}\n"
            "ระบบจะคืนเงินคงเหลือทั้งหมดและปิดการใช้งานรอบนี้\n"
            "เก็บบัตรไว้ที่แคชเชียร์",
        ):
            return

        if (
            not self._confirm_identity(uid, token)
            or not self.return_confirm.isEnabled()
        ):
            set_banner(self.notice, "error",
                "ข้อมูลบัตรเปลี่ยนแล้ว"
                " • ตรวจสอบบัตรใหม่ก่อนยืนยัน"
            )
            return

        operation_id = str(uuid.uuid4())
        self.current_operation = operation_id
        self.operation_request = {
            "kind": "RETURN_CARD", "uid": uid, "token": token,
        }
        self._busy(True)
        set_banner(self.notice, "warning",
            "Returning Card • กำลังคืนบัตร"
            " • ห้ามนำบัตรออกหรือปิดโปรแกรม"
        )

        def done(result):
            if not result.get("success"):
                self._transaction_failure(result.get("reason"))
                return

            refund = Decimal(str(result["amount"]))
            self.blocked_uid = uid
            self._busy(False)
            self._clear_operation()
            self.return_amount.setText(money(refund))
            self.return_status.setText(
                "Card Status: Returned / Available • Balance ฿0.00",
            )
            set_banner(self.notice, "success",
                f"Card Returned Successfully • คืนเงินสด {money(refund)}"
                " ให้ลูกค้า และเก็บบัตรไว้"
            )
            self._refresh_history()

        self._job(
            lambda: self.store.return_card(operation_id, token, uid),
            done,
            lambda: self._unknown(
                "ติดต่อฐานข้อมูลขณะคืนบัตรผิดพลาด"
                " ต้องตรวจสอบผลก่อนทำซ้ำ"
            ),
        )

    def _transaction_failure(self, reason):
        known = {
            "INVALID_AMOUNT": "จำนวนเงินไม่ถูกต้อง",
            "WALLET_NOT_FOUND": "ไม่พบกระเป๋าเงิน",
            "WALLET_SUSPENDED": "บัตรไม่พร้อมใช้งาน",
            "CARD_NOT_ACTIVE": "บัตรนี้คืนแล้วหรือไม่พร้อมใช้งาน",
            "CARD_ID_MISMATCH": "Card ID ไม่ตรงกับรอบการใช้งาน",
            "BALANCE_LIMIT": "ยอดเงินหลังเติมเกินขีดจำกัด",
            "OPERATION_CANCELLED": "รายการนี้ถูกยกเลิกแล้ว",
        }

        if reason not in known:
            self._unknown(
                "ไม่สามารถยืนยันผลธุรกรรมได้"
                " • ดูประวัติก่อน และอย่าทำรายการเดิมซ้ำ"
            )
            return

        self.blocked_uid = self.uid
        self._busy(False)
        self._clear_operation()
        set_banner(self.notice, "error",
            f"ไม่ได้ทำรายการ: {known[reason]}"
            " • นำบัตรออกแล้วตรวจสอบใหม่"
        )

    def _unknown(self, message):
        self.uncertain = True
        self.pending = None
        self._busy(False)
        self._disable_actions()
        self.recover_button.show()
        set_banner(self.notice, "error", message)

        QMessageBox.warning(
            self,
            "ต้องตรวจสอบผลรายการ",
            message
            + "\nหยุดทำรายการบัตรนี้และติดต่อผู้ดูแลก่อนเริ่มใหม่",
        )
        self._refresh_history()

    def _clear_operation(self):
        self.current_operation = None
        self.operation_request = None
        self.uncertain = False
        self.recover_button.hide()

    def _recover_operation(self):
        request = self.operation_request
        operation_id = self.current_operation
        if not request or not operation_id or self.busy:
            return
        if self.uid != request.get("uid"):
            set_banner(self.notice, "error",
                "Tap the Same Card • ต้องวางบัตรใบเดิมเพื่อทำการตรวจสอบรายการก่อนหน้า"
            )
            return

        self._busy(True)
        self.recover_button.hide()
        set_banner(self.notice, "warning", "Checking Previous Operation… • กำลังตรวจสอบผลรายการก่อนหน้า")

        def recover():
            kind = request["kind"]
            if kind == "TOP_UP":
                return self.store.top_up(
                    operation_id, request["token"], request["uid"],
                    Decimal(request["amount"]),
                )
            if kind == "RETURN_CARD":
                return self.store.return_card(
                    operation_id, request["token"], request["uid"],
                )
            token = request.get("new_token")
            if not token and self.valid and self.token:
                token = self.token
            if not token:
                raise RuntimeError("ISSUE_TOKEN_UNKNOWN")
            self.store.begin_issue(operation_id, request["uid"], request.get("old_token"))
            try:
                self.store.attach_issue_token(operation_id, request["uid"], token)
            except RuntimeError as error:
                if str(error) != "ISSUE_OPERATION_NOT_PENDING":
                    raise
            return self.store.finish_issue(operation_id, request["uid"], token)

        def done(result):
            kind = request["kind"]
            if not result.get("success"):
                self._transaction_failure(result.get("reason"))
                return
            self._busy(False)
            self._clear_operation()
            if kind == "ISSUE":
                self.blocked_uid = request["uid"]
                set_banner(self.notice, "success", "Card Setup Confirmed • ยืนยันผลการออกบัตรสำเร็จ นำบัตรออกได้")
            elif kind == "TOP_UP":
                self.blocked_uid = request["uid"]
                set_banner(self.notice, "success",
                    f"Top Up Confirmed • ยอดคงเหลือ {money(result['balance'])} • นำบัตรออกได้"
                )
            else:
                self.blocked_uid = request["uid"]
                set_banner(self.notice, "success",
                    f"Return Confirmed • คืนเงินสด {money(result['amount'])} และเก็บบัตรไว้"
                )
            self._refresh_history()

        self._job(recover, done, lambda: self._unknown(
            "ยังยืนยันผลรายการไม่ได้ • กรุณาคงบัตรไว้และให้ผู้ดูแลตรวจสอบ Database"
        ))

    def _checked_history(self):
        if self.checked_uid and self.checked_token:
            self.history_uid = self.checked_uid
            self.history_token = self.checked_token
            self._navigate(1)

    def _all_history(self):
        self.history_uid = None
        self.history_token = None
        self._refresh_history()

    def _history_double_click(self, row, column):
        if column != 1:
            return

        item = self.table.item(row, column)
        if item and item.data(Qt.ItemDataRole.UserRole):
            identity = item.data(Qt.ItemDataRole.UserRole)
            self.history_uid = identity["uid"]
            self.history_token = identity["token"]
            self._refresh_history()

    def _auto_history(self):
        if (
            self.pages.currentIndex() == 1
            and self.history_refresh.isEnabled()
        ):
            self._refresh_history()

    def _refresh_history(self):
        self.history_epoch += 1
        generation = self.history_epoch
        uid, token = self.history_uid, self.history_token

        self.history_title.setText(
            "ประวัติของบัตรใบนี้"
            if token else "รายการทั้งหมด"
        )
        self.show_all.setEnabled(token is not None)
        self.history_focus.setVisible(token is not None)
        if token:
            self.history_focus.setText(
                f"กำลังดู Card ID: {uid} • แสดงเฉพาะรายการหลังออกบัตรครั้งล่าสุด"
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
                    "TOP_UP": "เติมเงิน",
                    "PAY": "ชำระค่าอาหาร",
                    "REFUND_RETURN": "คืนเงิน / คืนบัตร",
                }.get(action, action)

                terminal = record.get("terminal_type", "")
                terminal_text = {
                    "CASHIER": "แคชเชียร์",
                    "STALL_POS": "ร้านค้า",
                    "STALL": "ร้านค้า",
                }.get(terminal, terminal)

                amount = Decimal(str(record.get("amount", 0)))

                if action == "TOP_UP":
                    prefix = "+"
                elif action in ("PAY", "REFUND_RETURN"):
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Tahoma", 10))

    window = CashierApp()
    window.showMaximized()

    sys.exit(app.exec())