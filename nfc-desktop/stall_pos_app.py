"""Stall POS with per-stall menus, shared images and recoverable payments.

Uses the existing database.py and NFCWorker API version 2.
Configure STALL_ID separately for each stall terminal.
STALL_NAME can provision a missing stall during initial setup.
Terminal configuration identifies a stall; it is not account authorization.
"""

import os
import sys
import json
import uuid
from html import escape
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager

import psycopg2
import database
from psycopg2.extras import RealDictCursor, Json
from nfc_worker import NFCWorker, DEFAULT_PORT

from PyQt6.QtCore import (
    Qt, QObject, QThread, QTimer, QLocale,
    QBuffer, QIODevice, QSize, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QTextDocument, QPixmap, QImageReader,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QFrame, QLabel,
    QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedWidget, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QInputDialog, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QFormLayout, QPlainTextEdit,
    QTabWidget, QSizePolicy, QFileDialog, QTextBrowser,
)

STALL = os.getenv('STALL_ID', 'STALL-01')
MAX = Decimal('99999999.99')
IMAGE_UNCHANGED = object()

# Bound connection waits, including calls made by the original database module.
database.DB_CONFIG.setdefault('connect_timeout', 5)

STYLE = '''
QWidget {font-family:Tahoma; font-size:17px; color:#12294a;}
QMainWindow, QDialog {background:#f5f8fe;}
QFrame#panel {background:white; border:1px solid #d5e2f6; border-radius:12px;}
QLabel#title {font-size:24px; font-weight:bold;}
QLabel#money {font-size:36px; font-weight:bold; color:#215be8;}
QLabel#muted {color:#526577; font-size:16px;}

QLabel#notice, QLabel#noticeInfo {
 background:#eaf3ff; color:#164ca1; border:1px solid #b9d3ff;
 border-left:7px solid #2563eb; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;
}
QLabel#noticeWarning {
 background:#fff4d6; color:#a85b00; border:1px solid #f3cd72;
 border-left:7px solid #f59e0b; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;
}
QLabel#noticeSuccess {
 background:#e5f8eb; color:#087a38; border:1px solid #a9dfb9;
 border-left:7px solid #16a34a; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;
}
QLabel#noticeError {
 background:#ffebeb; color:#bd2020; border:1px solid #f1b0b0;
 border-left:7px solid #dc2626; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;
}
QLabel#instruction {
 background:#edf5ff; color:#164ca1; border-radius:7px;
 padding:10px 12px; font-size:18px; font-weight:bold;
}

QPushButton {
 background:white; border:1px solid #bbcff0; border-radius:8px;
 padding:9px 13px; font-weight:bold;
}
QPushButton:hover {background:#eef5ff;}
QPushButton#primary, QPushButton:checked {
 background:#2563eb; color:white; border-color:#2563eb;
}
QPushButton#danger {color:#be3030; border-color:#edb4b4;}
QPushButton#success {
 background:#16a34a; color:white; border-color:#16a34a;
}
QPushButton#warning {
 background:#f59e0b; color:white; border-color:#f59e0b;
}

/* Explicit ID selectors prevent primary colors from overriding disabled colors. */
QPushButton#primary:disabled, QPushButton#danger:disabled,
QPushButton#success:disabled, QPushButton#warning:disabled,
QPushButton:checked:disabled, QPushButton:disabled {
 background:#e4ebf5; color:#93a3ba; border-color:#e4ebf5;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
 background:white; border:1px solid #bbcff0; border-radius:7px; padding:7px;
}
QTableWidget {
 background:white; alternate-background-color:#f5f9ff;
 border:1px solid #d5e2f6; gridline-color:#edf2fb;
 selection-background-color:#dfebff; selection-color:#12294a;
}
QHeaderView::section {
 background:#edf4fc; padding:9px; border:0; font-weight:bold;
}
QScrollArea {border:0; background:transparent;}
QScrollArea > QWidget > QWidget {background:transparent;}
QPushButton#quantity {padding:0; font-size:20px; border-radius:6px;}
QPushButton#category {padding:8px 12px; min-height:26px;}
QCheckBox::indicator {width:22px; height:22px;}
QTabBar::tab {background:#edf4fc; color:#12294a; padding:10px;}
QTabBar::tab:selected {background:#2563eb; color:white;}
QLabel#quantityNumber {font-size:17px; font-weight:bold;}

QLabel#statusReady {
 background:#e5f8eb; color:#087a38; border:1px solid #a9dfb9;
 border-radius:12px; padding:7px 12px; font-weight:bold; font-size:15px;
}
QLabel#statusWarning {
 background:#fff4d6; color:#a85b00; border:1px solid #f3cd72;
 border-radius:12px; padding:7px 12px; font-weight:bold; font-size:15px;
}
QLabel#statusError {
 background:#ffebeb; color:#bd2020; border:1px solid #f1b0b0;
 border-radius:12px; padding:7px 12px; font-weight:bold; font-size:15px;
}

QFrame#queueWaiting {
 background:#fffaf0; border:1px solid #f3cd72; border-radius:12px;
}
QFrame#queuePreparing {
 background:#f3f8ff; border:1px solid #b9d3ff; border-radius:12px;
}
QFrame#queueReady {
 background:#effbf3; border:1px solid #a9dfb9; border-radius:12px;
}
QFrame#queueCardWaiting {
 background:#fffaf0; border:1px solid #f0c45c; border-radius:10px;
}
QFrame#queueCardPreparing {
 background:#f6f9ff; border:1px solid #a7c7ff; border-radius:10px;
}
QFrame#queueCardReady {
 background:#f3fff6; border:1px solid #8dd7a4; border-radius:10px;
}
'''


# ---------- Common UI and money helpers ----------

def product_id(key):
    """Decode a cart line while accepting previous integer product keys."""
    return int(str(key).split(':', 1)[0])


def line_key(item):
    """Old snapshots retain their refund keys; new rows use unique line IDs."""
    return str(item.get('line_id') or item['pid'])


def fit_dialog(dialog, width, height):
    screen = dialog.screen() or QApplication.primaryScreen()
    area = screen.availableGeometry()
    dialog.resize(min(width, area.width()-40), min(height, area.height()-60))


def scroll_content(widget, minimum_height=340):
    widget.setMinimumHeight(minimum_height)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    return scroll


def dec(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n > MAX or n != n.quantize(Decimal('.01')):
            raise ValueError
        return n
    except (InvalidOperation, ValueError):
        raise ValueError('จำนวนเงินไม่ถูกต้อง หรือมีทศนิยมเกิน 2 ตำแหน่ง')


def baht(value):
    return f'฿{Decimal(str(value)):,.2f}'


def lab(text='', name=None):
    w = QLabel(text)
    w.setWordWrap(True)
    if name:
        w.setObjectName(name)
    return w


def button(text, action, primary=False, danger=False):
    w = QPushButton(text)
    if primary or danger:
        w.setObjectName('primary' if primary else 'danger')
    w.clicked.connect(action)
    return w


def panel():
    w = QFrame()
    w.setObjectName('panel')
    b = QVBoxLayout(w)
    b.setContentsMargins(16, 14, 16, 14)
    b.setSpacing(10)
    return w, b


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(42)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return t


def fill(t, rows):
    t.setRowCount(len(rows))
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if str(value) in ('—', '-'):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setItem(r, c, item)


def banner(widget, kind, text):
    names = {
        'info': 'noticeInfo', 'warning': 'noticeWarning',
        'success': 'noticeSuccess', 'error': 'noticeError',
    }
    widget.setObjectName(names.get(kind, 'noticeInfo'))
    prefix = '' if str(text).lstrip().startswith('●') else '● '
    widget.setText(prefix+str(text))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def pill(widget, kind, text):
    names = {'ready': 'statusReady', 'warning': 'statusWarning', 'error': 'statusError'}
    widget.setObjectName(names.get(kind, 'statusWarning'))
    widget.setText(text)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def card_error(exc):
    messages = {
        'CARD_NOT_PRESENT': 'กรุณาวางบัตรบนเครื่องอ่าน',
        'CARD_CHANGED': 'บัตรเปลี่ยนแล้ว กรุณาตรวจสอบใหม่',
        'TOKEN_CHANGED': 'ข้อมูลบัตรเปลี่ยนแล้ว กรุณาตรวจสอบใหม่',
        'HARDWARE_NOT_INITIALIZED': 'ยังเชื่อมต่อเครื่องอ่านไม่ได้',
        'LEGACY_UNSIGNED_CARD': 'บัตรนี้ยังไม่รองรับระบบล่าสุด กรุณาติดต่อจุดบริการบัตร',
        'SECRET_KEY_NOT_CONFIGURED': 'ยังตั้งค่าระบบอ่านบัตรไม่ครบ กรุณาติดต่อผู้ดูแล',
        'SIGNATURE_VERIFICATION_FAILED': 'ตรวจสอบบัตรไม่ผ่าน กรุณาติดต่อจุดบริการบัตร',
    }
    return messages.get(str(exc), 'อ่านบัตรไม่สำเร็จ กรุณาตรวจสอบบัตรและเครื่องอ่าน')


def picture(data, width=180, height=110):
    """Return a consistently sized image or a no-image placeholder."""
    label = lab('ยังไม่มีรูปอาหาร')
    label.setFixedSize(width, height)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet('background:#edf2f8;color:#526577;border-radius:8px;')
    if data:
        pixmap = QPixmap()
        if pixmap.loadFromData(bytes(data)):
            label.setText('')
            label.setPixmap(pixmap.scaled(
                width, height, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
    return label


def choose_image(parent):
    """Resize images before storing shared bytes instead of local file paths."""
    path, _ = QFileDialog.getOpenFileName(
        parent, 'เลือกรูปอาหาร', '', 'รูปอาหาร (*.jpg *.jpeg *.png)',
    )
    if not path:
        return IMAGE_UNCHANGED
    if os.path.getsize(path) > 8*1024*1024:
        raise BusinessError('กรุณาเลือกรูปขนาดไม่เกิน 8 MB')
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid():
        raise BusinessError('เปิดรูปนี้ไม่ได้')
    reader.setScaledSize(size.scaled(QSize(640, 480), Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise BusinessError('เปิดรูปนี้ไม่ได้')
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise BusinessError('บันทึกรูปไม่สำเร็จ')
    return bytes(buffer.data())


class QuantityControl(QWidget):
    """Use explicit minus/plus buttons instead of ambiguous native arrows."""
    valueChanged = pyqtSignal(int)

    def __init__(self, value, maximum, parent=None, minimum=0):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(4)
        self.minus = button('−', lambda: self.spin.stepDown())
        self.plus = button('+', lambda: self.spin.stepUp())
        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(value)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setMinimumWidth(45)
        for control in (self.minus, self.plus):
            control.setObjectName('quantity')
            control.setFixedSize(32, 38)
        row.addWidget(self.minus)
        row.addWidget(self.spin)
        row.addWidget(self.plus)
        self.spin.valueChanged.connect(self.changed)
        self.changed(value)

    def changed(self, value):
        self.minus.setEnabled(value > self.spin.minimum())
        self.plus.setEnabled(value < self.spin.maximum())
        self.valueChanged.emit(value)

    def value(self):
        return self.spin.value()


class ConfirmDialog(QDialog):
    """Keep confirmations readable and default to going back."""
    def __init__(self, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        b = QVBoxLayout(self)
        frame, box = panel()
        box.addWidget(lab(title, 'title'))
        details = lab(text)
        details.setStyleSheet('font-size:21px;padding:12px 0;')
        box.addWidget(details)
        row = QHBoxLayout()
        no = button('กลับไปตรวจสอบ', self.reject)
        yes = button('ยืนยัน', self.accept, True)
        no.setDefault(True)
        yes.setAutoDefault(False)
        row.addWidget(no)
        row.addWidget(yes)
        box.addLayout(row)
        b.addWidget(frame)


class BusinessError(Exception):
    pass


# ---------- Shared database and recoverable transactions ----------

class Store:
    @contextmanager
    def tx(self):
        conn = psycopg2.connect(**database.DB_CONFIG)
        try:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as c:
                    c.execute("SET LOCAL statement_timeout = '5s'")
                    c.execute("SET LOCAL lock_timeout = '3s'")
                    yield c
        finally:
            conn.close()

    def init(self):
        database.initialize_database()

        # Provision a missing configured stall without renaming existing data.
        with self.tx() as c:
            name = os.getenv('STALL_NAME', '').strip()[:100]
            if name:
                c.execute(
                    'INSERT INTO stalls(stall_id,stall_name,is_active,created_at,updated_at) '
                    'VALUES(%s,%s,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING',
                    (STALL, name),
                )

        with self.tx() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_menu (
                product_id INTEGER PRIMARY KEY REFERENCES products(product_id),
                description TEXT NOT NULL DEFAULT '', deleted BOOLEAN NOT NULL DEFAULT FALSE)''')
            c.execute('ALTER TABLE stall_ui_menu ADD COLUMN IF NOT EXISTS image_data BYTEA')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_categories (
                stall_id TEXT NOT NULL REFERENCES stalls(stall_id), name TEXT NOT NULL,
                PRIMARY KEY(stall_id,name))''')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_orders (
                id TEXT PRIMARY KEY, stall_id TEXT NOT NULL REFERENCES stalls(stall_id),
                items JSONB NOT NULL, note TEXT NOT NULL DEFAULT '',
                total NUMERIC(10,2) NOT NULL, paid NUMERIC(10,2) NOT NULL DEFAULT 0,
                returned NUMERIC(10,2) NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'OPEN', queue_state TEXT NOT NULL DEFAULT 'NONE',
                queue_no INTEGER, queue_day DATE, created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_payments (
                id SERIAL PRIMARY KEY, order_id TEXT NOT NULL REFERENCES stall_ui_orders(id),
                token TEXT NOT NULL REFERENCES wallets(token_uuid), uid TEXT NOT NULL,
                amount NUMERIC(10,2) NOT NULL, returned NUMERIC(10,2) NOT NULL DEFAULT 0,
                balance NUMERIC(10,2) NOT NULL, created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_refunds (
                id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES stall_ui_orders(id),
                items JSONB NOT NULL, reason TEXT NOT NULL, amount NUMERIC(10,2) NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE, created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_refund_parts (
                id SERIAL PRIMARY KEY, refund_id TEXT NOT NULL REFERENCES stall_ui_refunds(id),
                payment_id INTEGER NOT NULL REFERENCES stall_ui_payments(id),
                token TEXT NOT NULL, uid TEXT NOT NULL, amount NUMERIC(10,2) NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE)''')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_operations (
                id TEXT PRIMARY KEY, stall_id TEXT NOT NULL, request JSONB NOT NULL,
                state TEXT NOT NULL DEFAULT 'PENDING', result JSONB,
                created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_events (
                id SERIAL PRIMARY KEY, order_id TEXT NOT NULL REFERENCES stall_ui_orders(id),
                uid TEXT NOT NULL, kind TEXT NOT NULL, amount NUMERIC(10,2) NOT NULL,
                balance NUMERIC(10,2) NOT NULL, created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('''CREATE UNIQUE INDEX IF NOT EXISTS stall_ui_queue_unique
                ON stall_ui_orders(stall_id,queue_day,queue_no) WHERE queue_no IS NOT NULL''')
            c.execute('CREATE INDEX IF NOT EXISTS stall_ui_orders_by_stall ON stall_ui_orders(stall_id,created DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS stall_ui_payments_by_order ON stall_ui_payments(order_id)')
            c.execute('CREATE INDEX IF NOT EXISTS stall_ui_refunds_by_order ON stall_ui_refunds(order_id)')
            c.execute('CREATE INDEX IF NOT EXISTS stall_ui_operations_pending ON stall_ui_operations(stall_id,state)')
            c.execute('''INSERT INTO stall_ui_categories(stall_id,name)
                SELECT DISTINCT stall_id,category FROM products ON CONFLICT DO NOTHING''')

            # Import historical paid orders without rewriting the original tables.
            c.execute('''SELECT o.*,jsonb_agg(jsonb_build_object(
                'pid','legacy-item:'||i.order_item_id::text,'name',i.product_name,'qty',i.quantity,
                'price',i.unit_price::text,'returned',0,'note',i.item_note)) AS items
                FROM orders o JOIN order_items i USING(order_id)
                WHERE o.stall_id=%s AND o.payment_status='PAID'
                GROUP BY o.order_id''', (STALL,))
            for old in list(c.fetchall()):
                oid = 'legacy:'+str(old['order_id'])
                c.execute('''INSERT INTO stall_ui_orders(id,stall_id,items,total,paid,state,created)
                    VALUES(%s,%s,%s,%s,%s,'PAID',%s) ON CONFLICT DO NOTHING RETURNING id''',
                    (oid, STALL, Json(old['items']), old['total_amount'],
                     old['total_amount'], old['created_at']))
                if c.fetchone():
                    c.execute('''INSERT INTO stall_ui_payments(order_id,token,uid,amount,balance,created)
                        VALUES(%s,%s,%s,%s,%s,%s)''',
                        (oid, old['token_uuid'], old['card_uid'], old['total_amount'],
                         old['balance_after'], old['created_at']))
                    c.execute('''INSERT INTO stall_ui_events(order_id,uid,kind,amount,balance,created)
                        VALUES(%s,%s,'PAY',%s,%s,%s)''',
                        (oid, old['card_uid'], old['total_amount'],
                         old['balance_after'], old['created_at']))
                else:
                    c.execute('SELECT items FROM stall_ui_orders WHERE id=%s FOR UPDATE', (oid,))
                    items = c.fetchone()['items']
                    notes = {i['pid']: i.get('note') or '' for i in old['items']}
                    changed = False
                    for item in items:
                        if 'note' not in item:
                            item['note'] = notes.get(item['pid'], '')
                            changed = True
                    if changed:
                        c.execute('UPDATE stall_ui_orders SET items=%s WHERE id=%s', (Json(items), oid))

            c.execute('SELECT stall_name FROM stalls WHERE stall_id=%s AND is_active=1', (STALL,))
            if not c.fetchone():
                raise BusinessError('ไม่พบร้านที่เปิดใช้งาน ตรวจสอบ STALL_ID')

    def products(self, all_items=False):
        with self.tx() as c:
            c.execute('''SELECT p.*,COALESCE(m.description,'') AS description,m.image_data
                FROM products p LEFT JOIN stall_ui_menu m USING(product_id)
                WHERE p.stall_id=%s AND NOT COALESCE(m.deleted,FALSE)
                AND (%s OR p.is_available=1) ORDER BY p.product_id''', (STALL, all_items))
            return [dict(x) for x in c.fetchall()]

    def categories(self):
        with self.tx() as c:
            c.execute('SELECT name FROM stall_ui_categories WHERE stall_id=%s ORDER BY name', (STALL,))
            return [r['name'] for r in c.fetchall()]

    def menu_save(self, pid, name, category, price, available, description, image=IMAGE_UNCHANGED):
        clean_name, clean_category = name.strip(), category.strip()
        if not clean_name or not clean_category or dec(price) <= 0:
            raise BusinessError('กรอกชื่อ หมวด และราคามากกว่า 0')
        with self.tx() as c:
            c.execute('''SELECT p.product_id,COALESCE(m.deleted,FALSE) AS deleted
                FROM products p LEFT JOIN stall_ui_menu m USING(product_id)
                WHERE p.stall_id=%s AND LOWER(p.product_name)=LOWER(%s)
                AND (%s IS NULL OR p.product_id<>%s) LIMIT 1''',
                (STALL, clean_name, pid, pid))
            existing = c.fetchone()
            if existing and (pid or not existing['deleted']):
                raise BusinessError('มีเมนูชื่อ “'+clean_name+'” อยู่แล้ว กรุณาใช้ชื่ออื่น')
            c.execute('''INSERT INTO stall_ui_categories(stall_id,name)
                VALUES(%s,%s) ON CONFLICT(stall_id,name) DO NOTHING''', (STALL, clean_category))
            if pid:
                c.execute('''UPDATE products SET product_name=%s,category=%s,price=%s,
                    is_available=%s,updated_at=CURRENT_TIMESTAMP WHERE product_id=%s AND stall_id=%s
                    RETURNING product_id''',
                    (clean_name, clean_category, dec(price), int(available), pid, STALL))
            elif existing:
                # Reuse a soft-deleted product without changing historical snapshots.
                c.execute('''UPDATE products SET product_name=%s,category=%s,price=%s,
                    is_available=%s,updated_at=CURRENT_TIMESTAMP
                    WHERE product_id=%s AND stall_id=%s RETURNING product_id''',
                    (clean_name, clean_category, dec(price), int(available),
                     existing['product_id'], STALL))
            else:
                c.execute('''INSERT INTO products(stall_id,product_name,category,price,is_available,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING product_id''',
                    (STALL, clean_name, clean_category, dec(price), int(available)))
            row = c.fetchone()
            if not row:
                raise BusinessError('ไม่พบเมนูของร้านนี้')
            c.execute('''INSERT INTO stall_ui_menu(product_id,description,deleted)
                VALUES(%s,%s,FALSE)
                ON CONFLICT(product_id) DO UPDATE SET description=EXCLUDED.description,deleted=FALSE''',
                (row['product_id'], description))
            if image is not IMAGE_UNCHANGED:
                if image is not None and len(image) > 2*1024*1024:
                    raise BusinessError('รูปมีขนาดใหญ่เกินไป')
                c.execute('UPDATE stall_ui_menu SET image_data=%s WHERE product_id=%s',
                          (image, row['product_id']))

    def menu_delete(self, pid):
        with self.tx() as c:
            c.execute('UPDATE products SET is_available=0,updated_at=CURRENT_TIMESTAMP '
                      'WHERE product_id=%s AND stall_id=%s RETURNING product_id', (pid, STALL))
            if not c.fetchone():
                raise BusinessError('ไม่พบเมนู')
            c.execute('''INSERT INTO stall_ui_menu(product_id,deleted) VALUES(%s,TRUE)
                ON CONFLICT(product_id) DO UPDATE SET deleted=TRUE''', (pid,))

    def category(self, old, new=None):
        old = old.strip() if old else None
        new = new.strip() if new else None
        with self.tx() as c:
            if new:
                c.execute('''SELECT name FROM stall_ui_categories
                    WHERE stall_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1''', (STALL, new))
                existing = c.fetchone()
                if existing:
                    if not old:
                        raise BusinessError('มีหมวด “'+existing['name']+'” อยู่แล้ว ไม่ต้องเพิ่มซ้ำ')
                    if existing['name'] != old:
                        raise BusinessError('มีหมวด “'+existing['name']+'” อยู่แล้ว กรุณาใช้ชื่ออื่น')
                    return
                c.execute('INSERT INTO stall_ui_categories(stall_id,name) VALUES(%s,%s)', (STALL, new))
                if old:
                    c.execute('UPDATE products SET category=%s,updated_at=CURRENT_TIMESTAMP '
                              'WHERE stall_id=%s AND category=%s', (new, STALL, old))
            else:
                c.execute('SELECT 1 FROM products WHERE stall_id=%s AND category=%s LIMIT 1', (STALL, old))
                if c.fetchone():
                    raise BusinessError('หมวดนี้ยังมีเมนู รวมเมนูที่ปิดขาย ต้องย้ายหมวดก่อน')
            if old:
                c.execute('DELETE FROM stall_ui_categories WHERE stall_id=%s AND name=%s', (STALL, old))

    def create(self, oid, cart, note, item_notes=None):
        with self.tx() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('operation:'+STALL,))
            c.execute('SELECT id FROM stall_ui_orders WHERE id=%s AND stall_id=%s', (oid, STALL))
            if c.fetchone():
                return oid
            self.require_no_other_open_order(c, oid)
            items = []
            for key, qty in cart.items():
                pid = product_id(key)
                if not isinstance(qty, int) or not 1 <= qty <= 999:
                    raise BusinessError('จำนวนอาหารไม่ถูกต้อง')
                c.execute('''SELECT p.* FROM products p LEFT JOIN stall_ui_menu m USING(product_id)
                    WHERE p.product_id=%s AND p.stall_id=%s AND p.is_available=1
                    AND NOT COALESCE(m.deleted,FALSE) FOR SHARE OF p''', (pid, STALL))
                p = c.fetchone()
                if not p:
                    raise BusinessError('เมนูบางรายการปิดขายแล้ว ตรวจสอบตะกร้าใหม่')
                items.append(dict(
                    line_id=str(key), pid=pid, name=p['product_name'], qty=qty,
                    price=str(p['price']), returned=0,
                    note=str((item_notes or {}).get(key, ''))[:250],
                ))
            total = sum((dec(i['price'])*i['qty'] for i in items), Decimal(0))
            if not items or total <= 0:
                raise BusinessError('ไม่มีอาหารในออเดอร์')
            if total > MAX:
                raise BusinessError('ยอดออเดอร์เกินวงเงินที่รองรับ')
            c.execute('INSERT INTO stall_ui_orders(id,stall_id,items,note,total) VALUES(%s,%s,%s,%s,%s)',
                      (oid, STALL, Json(items), note, total))
            return oid

    def require_no_other_open_order(self, c, oid):
        # Call while holding the stall lock so two terminals cannot open orders together.
        c.execute('''SELECT 1 FROM stall_ui_orders WHERE stall_id=%s AND id<>%s
            AND state IN ('OPEN','PARTIAL','REFUND_PENDING') LIMIT 1''', (STALL, oid))
        if c.fetchone():
            raise BusinessError('กรุณาจัดการออเดอร์เดิมให้เสร็จก่อน')

    def order(self, oid):
        with self.tx() as c:
            c.execute('SELECT o.*,s.stall_name FROM stall_ui_orders o JOIN stalls s USING(stall_id) '
                      'WHERE o.id=%s AND o.stall_id=%s', (oid, STALL))
            o = c.fetchone()
            if not o:
                raise BusinessError('ไม่พบออเดอร์ของร้านนี้')
            o = dict(o)
            c.execute('SELECT * FROM stall_ui_payments WHERE order_id=%s ORDER BY id', (oid,))
            o['payments'] = [dict(x) for x in c.fetchall()]
            c.execute('''SELECT p.*,r.reason,r.amount AS refund_total FROM stall_ui_refund_parts p
                JOIN stall_ui_refunds r ON r.id=p.refund_id WHERE r.order_id=%s ORDER BY p.id''', (oid,))
            o['refunds'] = [dict(x) for x in c.fetchall()]
            return o

    def orders(self, queues=False):
        with self.tx() as c:
            if queues:
                c.execute('''SELECT * FROM stall_ui_orders WHERE stall_id=%s
                    AND queue_state IN ('WAITING','PREPARING','READY')
                    ORDER BY queue_day,queue_no''', (STALL,))
            else:
                c.execute('''SELECT * FROM stall_ui_orders WHERE stall_id=%s
                    AND state IN ('OPEN','PARTIAL','REFUND_PENDING')
                    UNION SELECT * FROM (SELECT * FROM stall_ui_orders WHERE stall_id=%s
                    ORDER BY created DESC LIMIT 300) recent ORDER BY created DESC''', (STALL, STALL))
            return [dict(x) for x in c.fetchall()]

    def stall_name(self):
        with self.tx() as c:
            c.execute('SELECT stall_name FROM stalls WHERE stall_id=%s', (STALL,))
            row = c.fetchone()
            return row['stall_name'] if row else STALL

    def rename_stall(self, name):
        if not name.strip():
            raise BusinessError('กรอกชื่อร้าน')
        with self.tx() as c:
            c.execute('UPDATE stalls SET stall_name=%s WHERE stall_id=%s', (name.strip()[:100], STALL))
            if c.rowcount != 1:
                raise BusinessError('ไม่พบร้าน '+STALL+' ในฐานข้อมูล')

    def wallet(self, token, uid):
        with self.tx() as c:
            c.execute('SELECT * FROM wallets WHERE token_uuid=%s AND card_uid=%s', (token, uid))
            row = c.fetchone()
            if not row:
                raise BusinessError('ไม่พบกระเป๋าเงินของบัตรนี้')
            return dict(row)

    def operation(self, op):
        with self.tx() as c:
            c.execute('SELECT * FROM stall_ui_operations WHERE id=%s AND stall_id=%s', (op, STALL))
            row = c.fetchone()
            return dict(row) if row else None

    def cancel_open(self, oid):
        # Match the financial lock order before cancelling an unpaid order.
        with self.tx() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('operation:'+STALL,))
            c.execute("SELECT id FROM stall_ui_operations WHERE stall_id=%s AND state='PENDING' LIMIT 1",
                      (STALL,))
            if c.fetchone():
                raise BusinessError('ตรวจผลรายการเดิมก่อนยกเลิกออเดอร์')
            c.execute('SELECT * FROM stall_ui_orders WHERE id=%s AND stall_id=%s FOR UPDATE', (oid, STALL))
            row = c.fetchone()
            if not row:
                raise BusinessError('ไม่พบออเดอร์')
            if row['state'] == 'CANCELLED' and row['paid'] == 0:
                return dict(row)
            if row['state'] != 'OPEN' or row['paid'] != 0:
                raise BusinessError('ออเดอร์นี้ต้องคืนยอดที่ชำระแล้วก่อนยกเลิก')
            c.execute("UPDATE stall_ui_orders SET state='CANCELLED',queue_state='CANCELLED' WHERE id=%s", (oid,))
            return dict(row)

    def perform(self, op, request, verify):
        # Resolve committed results before requesting another physical card read.
        old = self.operation(op)
        if old and old['request'] != request:
            raise BusinessError('ข้อมูลคำขอเดิมไม่ตรงกัน')
        if old and old['state'] == 'DONE':
            return old['result']
        if old and old['state'] == 'CANCELLED':
            return dict(cancelled=True)
        verify(request['uid'], request['token'])
        self.intent(op, request)
        verify(request['uid'], request['token'])
        try:
            return self.execute(op)
        except BusinessError as exc:
            result = self.reject(op, request)
            return result or dict(error=str(exc))

    def intent(self, op, request):
        with self.tx() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('operation:'+STALL,))
            c.execute("SELECT id FROM stall_ui_operations WHERE stall_id=%s "
                      "AND state='PENDING' AND id<>%s LIMIT 1", (STALL, op))
            if c.fetchone():
                raise BusinessError('มีคำขอเดิมรอตรวจผล ต้องตรวจคำขอนั้นก่อน')
            c.execute('INSERT INTO stall_ui_operations(id,stall_id,request) '
                      'VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (op, STALL, Json(request)))
            c.execute('SELECT request,stall_id FROM stall_ui_operations WHERE id=%s', (op,))
            row = c.fetchone()
            if row['request'] != request or row['stall_id'] != STALL:
                raise BusinessError('ข้อมูลรายการตรวจสอบไม่ตรงกัน')

    def pending(self):
        with self.tx() as c:
            c.execute("SELECT * FROM stall_ui_operations WHERE stall_id=%s "
                      "AND state='PENDING' ORDER BY created", (STALL,))
            return [dict(x) for x in c.fetchall()]

    def execute(self, op):
        with self.tx() as c:
            c.execute('SELECT * FROM stall_ui_operations WHERE id=%s AND stall_id=%s FOR UPDATE', (op, STALL))
            operation = c.fetchone()
            if not operation:
                raise BusinessError('ไม่พบเลขอ้างอิงการทำรายการ')
            if operation['state'] == 'DONE':
                return operation['result']
            if operation['state'] != 'PENDING':
                raise BusinessError('คำขอนี้ถูกยุติแล้ว ไม่ดำเนินรายการซ้ำ')
            req = operation['request']
            c.execute('SELECT * FROM stall_ui_orders WHERE id=%s AND stall_id=%s FOR UPDATE',
                      (req['order'], STALL))
            o = c.fetchone()
            if not o:
                raise BusinessError('ไม่พบออเดอร์')

            # Balance, ledger, order and operation result commit atomically.
            c.execute('SELECT * FROM wallets WHERE token_uuid=%s FOR UPDATE', (req['token'],))
            w = c.fetchone()
            if not w or w['card_uid'] != req['uid'] or w['status'] != 'ACTIVE':
                raise BusinessError('บัตรไม่พร้อมใช้งาน หรือรอบการออกบัตรเปลี่ยนแล้ว')
            amount = dec(req['amount'])
            if amount <= 0:
                raise BusinessError('ยอดต้องมากกว่า 0')

            if req['kind'] == 'PAY':
                if o['state'] not in ('OPEN', 'PARTIAL') or amount > o['total']-o['paid']:
                    raise BusinessError('ออเดอร์นี้ไม่อยู่ในสถานะที่ชำระยอดนี้ได้')
                if w['balance'] < amount:
                    raise BusinessError('ยอดเงินไม่พอ ไม่ได้ทำรายการนี้')
                balance, paid = w['balance']-amount, o['paid']+amount
                c.execute('INSERT INTO stall_ui_payments(order_id,token,uid,amount,balance) '
                          'VALUES(%s,%s,%s,%s,%s)', (o['id'], req['token'], req['uid'], amount, balance))
                c.execute('UPDATE stall_ui_orders SET paid=%s,state=%s WHERE id=%s',
                          (paid, 'PAID' if paid == o['total'] else 'PARTIAL', o['id']))

                if paid == o['total']:
                    # Serialize queue numbering across terminals of the same stall.
                    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('queue:'+STALL,))
                    c.execute('SELECT COALESCE(MAX(queue_no),0)+1 AS n FROM stall_ui_orders '
                              'WHERE stall_id=%s AND queue_day=CURRENT_DATE', (STALL,))
                    number = c.fetchone()['n']
                    c.execute("UPDATE stall_ui_orders SET queue_no=%s,queue_day=CURRENT_DATE,"
                              "queue_state='WAITING' WHERE id=%s", (number, o['id']))
                kind = 'PAY'

            elif req['kind'] == 'REFUND':
                if o['state'] != 'REFUND_PENDING':
                    raise BusinessError('ออเดอร์นี้ไม่มีแผนคืนที่รอดำเนินการ')
                c.execute('''SELECT p.*,r.order_id FROM stall_ui_refund_parts p
                    JOIN stall_ui_refunds r ON r.id=p.refund_id
                    WHERE p.id=%s FOR UPDATE OF p,r''', (req['part'],))
                part = c.fetchone()
                if (not part or part['order_id'] != o['id'] or part['token'] != req['token']
                        or part['uid'] != req['uid'] or part['amount'] != amount or part['done']):
                    raise BusinessError('แผนคืนไม่ตรง หรือคืนรายการนี้แล้ว')
                balance = w['balance']+amount
                if balance > MAX:
                    raise BusinessError('ยอดเงินหลังคืนเกินวงเงินที่รองรับ')
                c.execute('UPDATE stall_ui_payments SET returned=returned+%s '
                          'WHERE id=%s AND returned+%s<=amount RETURNING id',
                          (amount, part['payment_id'], amount))
                if not c.fetchone():
                    raise BusinessError('ยอดคืนเกินยอดที่บัตรนี้จ่าย')
                c.execute('UPDATE stall_ui_refund_parts SET done=TRUE WHERE id=%s', (part['id'],))
                c.execute('UPDATE stall_ui_orders SET returned=returned+%s WHERE id=%s', (amount, o['id']))
                c.execute('SELECT 1 FROM stall_ui_refund_parts WHERE refund_id=%s AND NOT done',
                          (part['refund_id'],))
                if not c.fetchone():
                    c.execute('UPDATE stall_ui_refunds SET done=TRUE WHERE id=%s RETURNING items',
                              (part['refund_id'],))
                    quantities = c.fetchone()['items']
                    items = o['items']
                    for item in items:
                        item['returned'] += int(quantities.get(line_key(item), 0))
                    full = o['returned']+amount == o['paid']
                    cancelled = full and (
                        o['paid'] < o['total'] or all(i['returned'] == i['qty'] for i in items)
                    )
                    c.execute('''UPDATE stall_ui_orders SET items=%s,state=%s,
                        queue_state=CASE WHEN %s THEN %s ELSE queue_state END WHERE id=%s''',
                        (Json(items), 'CANCELLED' if cancelled else 'PAID',
                         cancelled, 'CANCELLED', o['id']))
                kind = 'REFUND_MEAL'
            else:
                raise BusinessError('ประเภทการทำรายการไม่ถูกต้อง')

            c.execute('UPDATE wallets SET balance=%s,updated_at=CURRENT_TIMESTAMP WHERE token_uuid=%s',
                      (balance, req['token']))
            c.execute('''INSERT INTO transaction_ledger(
                token_uuid,card_uid,terminal_type,action_type,amount,balance_after,timestamp)
                VALUES(%s,%s,'STALL_POS',%s,%s,%s,CURRENT_TIMESTAMP)''',
                (req['token'], req['uid'], kind, amount, balance))
            c.execute('INSERT INTO stall_ui_events(order_id,uid,kind,amount,balance) VALUES(%s,%s,%s,%s,%s)',
                      (o['id'], req['uid'], kind, amount, balance))
            result = dict(kind=kind, amount=str(amount), balance=str(balance), order=o['id'])
            c.execute("UPDATE stall_ui_operations SET state='DONE',result=%s WHERE id=%s",
                      (Json(result), op))
            return result

    def reject(self, op, request=None):
        # A cancellation tombstone blocks a delayed preparation from charging later.
        with self.tx() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('operation:'+STALL,))
            if request is not None:
                c.execute("INSERT INTO stall_ui_operations(id,stall_id,request,state) "
                          "VALUES(%s,%s,%s,'CANCELLED') ON CONFLICT DO NOTHING",
                          (op, STALL, Json(request)))
            c.execute('SELECT state,result,request FROM stall_ui_operations '
                      'WHERE id=%s AND stall_id=%s FOR UPDATE', (op, STALL))
            row = c.fetchone()
            if not row:
                return None
            if request is not None and row['request'] != request:
                raise BusinessError('ข้อมูลคำขอไม่ตรงกัน')
            if row['state'] == 'DONE':
                return row['result']
            c.execute("UPDATE stall_ui_operations SET state='CANCELLED' "
                      "WHERE id=%s AND state='PENDING'", (op,))
            return None

    def plan(self, oid, quantities, reason, cancel_partial=False):
        with self.tx() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('operation:'+STALL,))
            self.require_no_other_open_order(c, oid)
            c.execute('SELECT * FROM stall_ui_orders WHERE id=%s AND stall_id=%s FOR UPDATE', (oid, STALL))
            o = c.fetchone()
            c.execute("SELECT 1 FROM stall_ui_operations WHERE stall_id=%s "
                      "AND state='PENDING' LIMIT 1", (STALL,))
            if c.fetchone():
                raise BusinessError('ตรวจผลคำขอเดิมก่อนคืนเงิน')
            if not o or o['state'] not in ('PAID', 'PARTIAL'):
                raise BusinessError('ออเดอร์นี้ไม่พร้อมสร้างแผนคืน')

            if cancel_partial:
                if o['state'] != 'PARTIAL':
                    raise BusinessError('ไม่ใช่ออเดอร์ที่ชำระบางส่วน')
                amount = o['paid']-o['returned']
                quantities = {line_key(i): i['qty']-i['returned'] for i in o['items']}
            else:
                amount = Decimal(0)
                valid_ids = {line_key(i) for i in o['items']}
                if set(quantities)-valid_ids:
                    raise BusinessError('รายการอาหารไม่ตรงกับออเดอร์')
                for item in o['items']:
                    qty = quantities.get(line_key(item), 0)
                    if not isinstance(qty, int) or qty < 0 or qty > item['qty']-item['returned']:
                        raise BusinessError('จำนวนคืนไม่ถูกต้อง')
                    amount += dec(item['price'])*qty

            if amount <= 0 or amount > o['paid']-o['returned'] or not reason.strip():
                raise BusinessError('เลือกอาหารที่จะคืนและระบุเหตุผล')
            rid = str(uuid.uuid4())
            c.execute('INSERT INTO stall_ui_refunds(id,order_id,items,reason,amount) VALUES(%s,%s,%s,%s,%s)',
                      (rid, oid, Json(quantities), reason, amount))
            c.execute('SELECT * FROM stall_ui_payments WHERE order_id=%s ORDER BY id DESC FOR UPDATE', (oid,))
            left = amount
            for payment in c.fetchall():
                take = min(left, payment['amount']-payment['returned'])
                if take > 0:
                    c.execute('INSERT INTO stall_ui_refund_parts(refund_id,payment_id,token,uid,amount) '
                              'VALUES(%s,%s,%s,%s,%s)',
                              (rid, payment['id'], payment['token'], payment['uid'], take))
                    left -= take
            if left:
                raise BusinessError('ยอดชำระเดิมไม่ตรง ตรวจสอบก่อนคืน')
            c.execute("UPDATE stall_ui_orders SET state='REFUND_PENDING' WHERE id=%s", (oid,))
            return rid

    def queue(self, oid, expected, target):
        transitions = {'WAITING': 'PREPARING', 'PREPARING': 'READY', 'READY': 'COLLECTED'}
        if transitions.get(expected) != target:
            raise BusinessError('ลำดับคิวไม่ถูกต้อง')
        with self.tx() as c:
            c.execute('UPDATE stall_ui_orders SET queue_state=%s '
                      'WHERE id=%s AND stall_id=%s AND queue_state=%s AND state=%s RETURNING id',
                      (target, oid, STALL, expected, 'PAID'))
            if not c.fetchone():
                raise BusinessError('คิวเปลี่ยนแล้ว หรือมีการคืนเงินค้างอยู่ กรุณารีเฟรช')

    def history(self, uid=None):
        with self.tx() as c:
            c.execute('''SELECT e.*,o.queue_no,o.state FROM stall_ui_events e
                JOIN stall_ui_orders o ON o.id=e.order_id
                WHERE o.stall_id=%s AND (%s IS NULL OR e.uid=%s)
                ORDER BY e.id DESC LIMIT 300''', (STALL, uid, uid))
            return [dict(x) for x in c.fetchall()]


class Bridge(QObject):
    tag = pyqtSignal(str, bool, object, str)
    removed = pyqtSignal()


class Job(QThread):
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.error.emit(str(exc))


# ---------- One customer receipt with aligned HTML columns ----------

class ReceiptDialog(QDialog):
    def __init__(self, o, parent=None, allow_refund=False):
        super().__init__(parent)
        self.setWindowTitle('รายละเอียดออเดอร์และสลิป')
        self.refund_requested = False
        self.setMinimumSize(900, 580)
        fit_dialog(self, 1180, 780)
        b = QVBoxLayout(self)
        queue = f"Q{o['queue_no']:03}" if o['queue_no'] else '—'
        b.addWidget(lab('รายละเอียดออเดอร์ • คิว '+queue, 'title'))
        body = QWidget()
        content = QHBoxLayout(body)
        detail_box, left = panel()
        left.addWidget(lab('รายการอาหาร', 'title'))

        # Refund columns appear only when an actual refund exists.
        has_refund = dec(o['returned']) > 0 or any(i['returned'] for i in o['items'])
        headers = ['ที่', 'อาหาร', 'จำนวน', 'ราคาต่อหน่วย', 'รวม', 'หมายเหตุ']
        if has_refund:
            headers.append('คืนแล้ว')
        foods = table(headers)
        rows = []
        for n, item in enumerate(o['items'], 1):
            row = [
                n, item['name'], item['qty'], baht(item['price']),
                baht(dec(item['price'])*item['qty']), item.get('note') or '—',
            ]
            if has_refund:
                row.append(item['returned'])
            rows.append(row)
        fill(foods, rows)
        foods.setMinimumHeight(170)
        for col in (0, 2, 3, 4):
            foods.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        left.addWidget(foods, 1)
        left.addWidget(lab(
            'รวม '+str(sum(i['qty'] for i in o['items']))+' หน่วย • '+baht(o['total']), 'money',
        ))
        left.addWidget(lab('การชำระเงิน', 'title'))
        headers = ['บัตรที่ชำระ', 'ยอดก่อนจ่าย', 'จ่าย', 'ยอดหลังจ่าย']
        if has_refund:
            headers.append('คืนเข้าบัตรแล้ว')
        payments = table(headers)
        fill(payments, [
            [p['uid'], baht(dec(p['balance'])+dec(p['amount'])), baht(p['amount']), baht(p['balance'])]
            + ([baht(p['returned'])] if has_refund else [])
            for p in o['payments']
        ])
        payments.setMinimumHeight(110)
        left.addWidget(payments)
        if o['payments']:
            left.addWidget(lab('ยอดบัตร ณ เวลาชำระ', 'muted'))
        completed_refunds = [p for p in o['refunds'] if p['done']]
        if completed_refunds:
            details = '\n'.join('• '+baht(p['amount'])+' • บัตร '+p['uid']+' • '+p['reason'] for p in completed_refunds)
            label = lab(details, 'muted')
            label.setTextFormat(Qt.TextFormat.PlainText)
            left.addWidget(lab('รายการคืนเงิน', 'title'))
            left.addWidget(label)

        receipt_box, right = panel()
        self.receipt = QTextBrowser()
        self.receipt.setOpenExternalLinks(False)
        self.receipt.setStyleSheet(
            'QTextBrowser{background:white;border:1px solid #bbcff0;padding:12px;}'
        )
        self.receipt_html = self.html(o, queue, has_refund)
        self.receipt.setHtml(self.receipt_html)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.receipt, 'ใบเสร็จรับเงิน')
        self.documents = [self.receipt]
        self.kitchen = QTextBrowser()
        self.kitchen.setOpenExternalLinks(False)
        self.kitchen.setStyleSheet(self.receipt.styleSheet())
        self.kitchen.setHtml(self.kitchen_html(o, queue))
        self.tabs.addTab(self.kitchen, 'ใบสั่งอาหาร')
        self.documents.append(self.kitchen)
        self.kitchen_available = bool(o['queue_no'] and o['state'] == 'PAID' and any(i['qty'] > i['returned'] for i in o['items']))
        self.tabs.setTabEnabled(1, self.kitchen_available)
        right.addWidget(self.tabs, 1)
        content.addWidget(detail_box, 58)
        content.addWidget(receipt_box, 42)
        b.addWidget(scroll_content(body, 380), 1)
        row = QHBoxLayout()
        self.print_btn = button('พิมพ์ใบเสร็จรับเงิน', self.print_current, True)
        self.print_btn.setEnabled(o['paid'] > 0)
        self.tabs.currentChanged.connect(lambda index: self.print_btn.setText('พิมพ์ใบสั่งอาหาร' if index else 'พิมพ์ใบเสร็จรับเงิน'))
        row.addWidget(self.print_btn)
        if allow_refund and o['state'] == 'PAID' and o['returned'] < o['paid']:
            row.addWidget(button('คืนค่าอาหาร', self.request_refund, danger=True))
        row.addWidget(button('ปิด', self.accept))
        b.addLayout(row)

    def request_refund(self):
        self.refund_requested = True
        self.accept()

    @staticmethod
    def kitchen_html(o, queue):
        # A kitchen ticket contains remaining quantities only and no card data.
        rows = []
        for item in o['items']:
            qty = item['qty']-item['returned']
            if qty > 0:
                rows.append('<tr><td>'+escape(item['name'])+'</td><td align="center">'+str(qty)+'</td><td>'+escape(item.get('note') or '—')+'</td></tr>')
        note = '<p>หมายเหตุออเดอร์: '+escape(o['note'])+'</p>' if o.get('note') else ''
        return ('<html><body style="font-family:Tahoma;font-size:12pt;">'
                '<h2>ใบสั่งอาหาร • คิว '+escape(queue)+'</h2><p>'+escape(o.get('stall_name', STALL))
                +'<br/>ออเดอร์: '+escape(o['id'][:8])+'<br/>วันที่: '+escape(str(o['created'])[:19])+'</p>'
                '<table width="100%" cellpadding="6"><tr style="background:#edf4fc;"><th>อาหาร</th><th>จำนวน</th><th>หมายเหตุ</th></tr>'
                +''.join(rows)+'</table>'+note+'</body></html>')

    @staticmethod
    def html(o, queue, has_refund):
        # Real table cells align Thai names, quantities and money without spaces.
        e = lambda value: escape(str(value))
        name, sid = e(o.get('stall_name', STALL)), e(o.get('stall_id', STALL))
        state = {
            'PAID': 'ชำระครบแล้ว', 'PARTIAL': 'ชำระบางส่วน',
            'CANCELLED': 'ยกเลิกแล้ว', 'REFUND_PENDING': 'รอคืนเงิน',
            'OPEN': 'ยังไม่ชำระ',
        }.get(o['state'], o['state'])
        rows = []
        for item in o['items']:
            note = (
                '<br/><span style="color:#526577">'+e(item['note'])+'</span>'
                if item.get('note') else ''
            )
            if has_refund and item['returned']:
                note += (
                    '<br/><span style="color:#a85b00">คืนอาหารแล้ว '
                    +str(item['returned'])+' หน่วย</span>'
                )
            rows.append(
                '<tr><td>'+e(item['name'])+note
                +'</td><td align="center">'+str(item['qty'])
                +'</td><td align="right">'+e(baht(item['price']))
                +'</td><td align="right">'+e(baht(dec(item['price'])*item['qty']))
                +'</td></tr>'
            )
        summary = '<tr><td>ยอดรวม</td><td align="right">'+e(baht(o['total']))+'</td></tr>'
        if has_refund:
            summary += (
                '<tr><td>คืนเงินแล้ว</td><td align="right">'+e(baht(o['returned']))
                +'</td></tr><tr><td>ยอดชำระสุทธิ</td><td align="right">'
                +e(baht(o['paid']-o['returned']))+'</td></tr>'
            )
        elif o['paid'] != o['total']:
            summary += '<tr><td>ชำระแล้ว</td><td align="right">'+e(baht(o['paid']))+'</td></tr>'
        payment_details = ''
        if o['payments']:
            payment_details = '<hr/><p><b>ยอดบัตร ณ เวลาชำระ</b></p>'
            for index, p in enumerate(o['payments'], 1):
                ending = p['uid'].replace(':', '')[-4:]
                before = dec(p['balance'])+dec(p['amount'])
                payment_details += ('<p><b>รายการชำระ '+str(index)+' • บัตรลงท้าย '+e(ending)+'</b>'
                                    '<br/>ยอดก่อนชำระ: '+e(baht(before))
                                    +'<br/>หักจากบัตร: '+e(baht(p['amount']))
                                    +'<br/>ยอดคงเหลือหลังชำระ: '+e(baht(p['balance']))+'</p>')
        note = '<p>หมายเหตุ: '+e(o['note'])+'</p>' if o.get('note') else ''
        return (
            '<html><head><meta charset="utf-8"/><style>'
            'body{font-family:Tahoma;font-size:12pt;color:#12294a;}'
            'td,th{padding:6px;}th{background:#edf4fc;}h2{font-size:17pt;}'
            '</style></head><body>'
            '<h2 align="center">ใบเสร็จรับเงิน</h2><p align="center">'
            +name+'<br/>'+sid+'<br/><b>คิว '+e(queue)+'</b></p>'
            '<p>ออเดอร์: '+e(o['id'][:8])+'<br/>วันที่: '+e(str(o['created'])[:19])
            +'<br/>สถานะ: '+e(state)+'</p>'
            '<table width="100%" cellspacing="0" cellpadding="4">'
            '<tr><th align="left">อาหาร</th><th width="64">จำนวน</th>'
            '<th width="85">ราคา</th><th width="85">รวม</th></tr>'
            +''.join(rows)+'</table>'+note
            +'<hr/><table width="100%">'+summary+'</table>'+payment_details
            +'<p align="center">ขอบคุณที่ใช้บริการ</p></body></html>'
        )

    def print_current(self):
        try:
            from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            if QPrintDialog(printer, self).exec() == QDialog.DialogCode.Accepted:
                document = QTextDocument()
                document.setDefaultFont(QFont('Tahoma', 12))
                document.setHtml(self.documents[self.tabs.currentIndex()].toHtml())
                document.print(printer)
        except Exception:
            QMessageBox.information(self, 'พิมพ์ใบเสร็จ', 'พิมพ์ไม่ได้ ตรวจสอบเครื่องพิมพ์และไดรเวอร์')


# ---------- Payment and original-card refund workflow ----------

class Checkout(QDialog):
    """Finish one sale at the counter; unresolved requests retain their IDs."""
    def __init__(self, app, oid, refund=False):
        super().__init__(app)
        self.app, self.oid, self.refund = app, oid, refund
        if refund:
            app.must_remove = False
        self.wallet = self.o = self.part = None
        self.op = self.request = None
        self.split = self.locked = self.receipt_shown = False
        self.last_payment = None
        self.split_next = False
        self.generation = 0
        self.closing = False
        self.remaining = Decimal(0)
        self.setWindowTitle('คืนค่าอาหาร' if refund else 'ชำระค่าอาหาร')
        self.setMinimumSize(940, 600)
        fit_dialog(self, 1120, 800)
        b = QVBoxLayout(self)
        b.addWidget(lab(self.windowTitle(), 'title'))
        self.mode_label = lab('ชำระเต็มยอด', 'instruction')
        self.mode_label.setMinimumHeight(42)
        b.addWidget(self.mode_label)
        body = QWidget()
        content = QHBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)

        frame, left = panel()
        left.addWidget(lab('รายการอาหาร', 'title'))
        self.order_items = table(['ลำดับ', 'อาหาร', 'จำนวน', 'รวม', 'หมายเหตุ'])
        for col in (0, 2, 3):
            self.order_items.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents,
            )
        left.addWidget(self.order_items, 1)
        self.summary = lab('กำลังโหลดออเดอร์', 'instruction')
        self.summary.setMinimumHeight(96)
        left.addWidget(self.summary)
        self.contributions = table(['บัตรที่ชำระ', 'จ่ายแล้ว', 'คืนแล้ว'])
        self.contributions.setMaximumHeight(150)
        left.addWidget(self.contributions)
        content.addWidget(frame, 56)

        frame, right = panel()
        right.addWidget(lab('ตรวจสอบบัตรก่อนยืนยัน', 'title'))
        self.card = lab('กรุณาวางบัตรบนเครื่องอ่าน', 'instruction')
        self.balance = lab('ยอดเงินในบัตร: —', 'money')
        self.balance.setStyleSheet('font-size:27px;font-weight:bold;color:#215be8;')
        self.amount = lab('ยอดที่ต้องชำระ: —', 'instruction')
        self.after = lab('ยอดหลังทำรายการ: —', 'instruction')
        for w in (self.card, self.balance, self.amount, self.after):
            w.setMinimumHeight(48)
            w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            right.addWidget(w)
        right.addStretch()
        right.addWidget(lab('อ่านยอดอย่างเดียวจะไม่หักเงิน\nวางบัตรไว้จนระบบแจ้งผลสำเร็จ', 'muted'))
        content.addWidget(frame, 44)
        b.addWidget(scroll_content(body, 360), 1)

        self.notice = lab('กำลังตรวจสอบออเดอร์', 'noticeWarning')
        self.notice.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        b.addWidget(self.notice)
        row = QHBoxLayout()
        self.change = button('ใช้บัตรใบอื่น', self.change_card)
        self.split_btn = button('แบ่งจ่ายหลายบัตร', self.enable_split)
        self.confirm = button('ยืนยันชำระเงิน', self.pay, True)
        for w in (self.change, self.split_btn, self.confirm):
            row.addWidget(w)
        b.addLayout(row)
        row = QHBoxLayout()
        self.edit = button('กลับไปแก้ไขออเดอร์', self.edit_order)
        self.cancel = button('ยกเลิกออเดอร์', self.cancel_order, danger=True)
        row.addWidget(self.edit)
        row.addWidget(self.cancel)
        b.addLayout(row)
        self.check = button('ตรวจผลและดำเนินรายการเดิม', self.recover, True)
        self.abandon = button('ตรวจผลและยุติคำขอที่ยังไม่สำเร็จ', self.abandon_op)
        b.addWidget(self.check)
        b.addWidget(self.abandon)
        self.check.hide()
        self.abandon.hide()
        self.confirm.setEnabled(False)
        self.sync_mode()
        self.refresh()

    def refresh(self):
        if self.closing:
            return
        if not self.app.run(lambda: self.app.db.order(self.oid), self.loaded, self.uncertain):
            QTimer.singleShot(180, self.refresh)

    def loaded(self, o):
        if self.closing:
            return
        self.o = o
        fill(self.order_items, [
            (n, i['name'], i['qty']-i['returned'],
             baht(dec(i['price'])*(i['qty']-i['returned'])), i.get('note') or '—')
            for n, i in enumerate(o['items'], 1)
        ])
        self.order_items.resizeRowsToContents()
        fill(self.contributions, [
            (p['uid'], baht(p['amount']), baht(p['returned'])) for p in o['payments']
        ])
        self.contributions.setVisible(bool(o['payments']))
        self.contributions.setColumnHidden(2, not self.refund and not o['returned'])
        self.edit.setVisible(o['state'] == 'OPEN' and not self.refund)
        self.cancel.setVisible(not self.refund and o['state'] in ('OPEN', 'PARTIAL'))
        self.cancel.setText('ยกเลิกและคืนยอดที่ชำระแล้ว' if o['paid'] else 'ยกเลิกออเดอร์')
        self.sync_mode()
        if self.op:
            self.uncertain('พบคำขอเดิมที่ต้องตรวจผล')
            return

        if self.refund:
            pending = [p for p in o['refunds'] if not p['done']]
            if not pending:
                self.app.sale_wallet = None
                banner(self.app.notice, 'success', 'คืนเงินครบแล้ว • นำบัตรออกได้')
                self.finish()
                return
            self.part = pending[0]
            if self.app.current == (self.part['uid'], self.part['token']):
                self.app.must_remove = False
            self.remaining = self.part['amount']
            self.summary.setText(
                'ยังต้องคืนทั้งหมด '+baht(sum((p['amount'] for p in pending), Decimal(0)))
            )
            self.card.setText('กรุณาวางบัตรเดิม: '+self.part['uid'])

        elif o['state'] == 'PAID':
            self.confirm.setEnabled(False)
            self.app.sale_wallet = None
            text = (
                f"ชำระเงินสำเร็จ • คิว Q{o['queue_no']:03} • นำบัตรออกได้"
                if o['queue_no'] else 'ชำระเงินสำเร็จ • นำบัตรออกได้'
            )
            banner(self.app.notice, 'success', text)
            if not self.receipt_shown:
                self.receipt_shown = True
                ReceiptDialog(o, self).exec()
            self.finish()
            return
        elif o['state'] == 'CANCELLED':
            self.finish()
            return
        elif o['state'] == 'REFUND_PENDING':
            self.refund = True
            self.loaded(o)
            return
        else:
            self.remaining = o['total']-o['paid']
            self.summary.setText(
                'ยอดรวม '+baht(o['total'])+'\nชำระแล้ว '+baht(o['paid'])
                +'\nยังต้องชำระ '+baht(self.remaining)
            )

        self.clear_card_balance()
        self.amount.setEnabled(True)
        self.preview()
        if self.split_next and not self.refund:
            banner(
                self.notice, 'warning',
                'ชำระจากบัตรก่อนแล้ว '+baht(self.last_payment)
                +' • ยังต้องชำระ '+baht(self.remaining)
                +'\nนำบัตรออก แล้ววางบัตรใบถัดไป',
            )

        # A card can remain on the reader from balance inquiry to confirmation.
        if self.app.seen_uid and not self.app.must_remove and not self.op:
            QTimer.singleShot(0, self.read_card)

    def read_card(self):
        if (self.closing or self.app.busy or self.locked or self.op
                or self.app.must_remove or not self.o):
            return
        uid = self.app.seen_uid
        if not uid:
            self.removed()
            return
        self.generation += 1
        generation = self.generation
        self.clear_card_balance()
        self.confirm.setEnabled(False)
        self.card.setText('กำลังตรวจสอบบัตรและอ่านยอด…')

        def work():
            snapshot = self.app.fresh_card(uid)
            return snapshot, self.app.db.wallet(snapshot[2], uid)

        def done(data):
            if self.closing or generation != self.generation or self.app.seen_uid != uid:
                return
            snapshot, self.wallet = data
            self.app.current = (uid, snapshot[2])
            self.card.setText('บัตร: '+uid)
            self.split_next = False
            self.balance.setText('ยอดเงินในบัตร: '+baht(self.wallet['balance']))
            banner(self.app.notice, 'info', 'อ่านบัตรเดิมแล้ว • ยังไม่ได้คืนเงิน' if self.refund else 'อ่านบัตรแล้ว • ยังไม่หักเงิน')
            self.preview()

        def failed(message):
            if generation == self.generation and not self.closing:
                self.clear_card_balance()
                self.card.setText(message)
                self.preview()
                banner(self.notice, 'error', message)

        self.app.run(work, done, failed)

    def clear_card_balance(self):
        self.wallet = None
        self.balance.setText('ยอดเงินในบัตร: —')
        self.after.setText('ยอดหลังทำรายการ: —')

    def on_card(self):
        self.generation += 1
        self.clear_card_balance()
        self.preview()
        self.card.setText('กำลังตรวจสอบบัตรและอ่านยอด…')
        self.read_card()

    def sync_mode(self):
        self.change.setVisible(not self.refund)
        self.split_btn.setVisible(not self.refund)
        self.split_btn.setText('✓ กำลังแบ่งจ่ายหลายบัตร' if self.split and not self.refund else 'แบ่งจ่ายหลายบัตร')
        if self.refund:
            mode = 'คืนเงินเข้าบัตรเดิม'
        elif self.split:
            mode = 'กำลังแบ่งจ่ายหลายบัตร'
        elif self.o and self.o['paid']:
            mode = 'ชำระยอดที่เหลือด้วยบัตรใบเดียว'
        else:
            mode = 'ชำระเต็มยอดด้วยบัตรใบเดียว'
        self.mode_label.setText(mode)

    def fixed_amount(self):
        # A split uses the smaller of the card balance and unpaid total.
        if not self.refund and self.split:
            return min(self.remaining, self.wallet['balance']) if self.wallet else Decimal(0)
        return self.remaining

    def removed(self):
        self.generation += 1
        self.clear_card_balance()
        self.confirm.setEnabled(False)
        if not self.locked and not self.op:
            if self.refund and self.part:
                self.card.setText('กรุณาวางบัตรเดิม: '+self.part['uid'])
                banner(self.notice, 'warning', 'รอวางบัตรที่ใช้ชำระเพื่อคืนเงิน')
            else:
                self.card.setText('กรุณาวางบัตรบนเครื่องอ่าน')
                if self.split_next:
                    banner(self.notice, 'warning', 'ชำระแล้ว '+baht(self.last_payment)+' • ยังต้องชำระ '+baht(self.remaining)+'\nวางบัตรใบถัดไป')
                else:
                    banner(self.notice, 'warning', 'รอวางบัตร • ยังไม่ทำรายการ')
        self.preview()

    def preview(self, *_):
        self.confirm.setEnabled(False)
        if self.closing or self.locked or self.op or self.app.busy:
            return
        n = self.fixed_amount()
        label = 'ยอดคืนเข้าบัตร' if self.refund else 'ยอดที่จะหักจากบัตรนี้' if self.split else 'ยอดที่ต้องชำระ'
        self.amount.setText(label+': '+('—' if self.split and not self.refund and not self.wallet else baht(n)))
        if not self.wallet or not self.o or self.app.must_remove:
            return
        w = self.wallet
        valid = (self.app.current == (w['card_uid'], w['token_uuid'])
                 and self.app.seen_uid == w['card_uid'] and w['status'] == 'ACTIVE'
                 and 0 < n <= self.remaining)
        if self.refund:
            original = self.part and (w['card_uid'], w['token_uuid']) == (self.part['uid'], self.part['token'])
            valid = (valid and original and self.o['state'] == 'REFUND_PENDING'
                     and not self.part['done'] and n == self.part['amount'] and w['balance']+n <= MAX)
            self.after.setText('ยอดเงินหลังคืน: '+baht(w['balance']+n) if valid else 'ยอดเงินหลังคืน: —')
            if not original:
                banner(self.notice, 'error', 'บัตรนี้ใช้รับเงินคืนรายการนี้ไม่ได้ • วางบัตรเดิม '+self.part['uid'] if self.part else 'ไม่พบรายการคืน')
            elif not valid:
                banner(self.notice, 'error', 'บัตรเดิมยังรับเงินคืนไม่ได้ กรุณาตรวจสอบสถานะหรือยอดเงิน')
            else:
                banner(self.notice, 'warning', 'ตรวจยอดคืน แล้วกดยืนยัน • คืนเข้าบัตรเดิมเท่านั้น')
        else:
            enough = w['balance'] >= n and n > 0
            valid = valid and enough and self.o['state'] in ('OPEN', 'PARTIAL')
            self.after.setText('ยอดเงินหลังชำระ: '+baht(w['balance']-n) if enough else 'ยอดเงินหลังชำระ: —')
            if not enough:
                short = max(Decimal(0), self.remaining-w['balance'])
                banner(self.notice, 'error', 'ยอดเงินในบัตรไม่เพียงพอ • ขาดอีก '+baht(short)+'\nใช้บัตรใบอื่น หรือเลือกแบ่งจ่ายหลายบัตร')
            else:
                banner(self.notice, 'warning', 'แบ่งจ่ายหลายบัตร • ตรวจยอดที่จะหักจากบัตรนี้ แล้วกดยืนยัน' if self.split else 'ยังไม่หักเงิน • ตรวจยอดแล้วกดยืนยันชำระเงิน')
        if w['status'] != 'ACTIVE':
            banner(self.notice, 'error', 'บัตรนี้ไม่อยู่ในรอบการใช้งาน กรุณาติดต่อจุดบริการบัตร')
        prefix = 'ยืนยันคืนเงิน ' if self.refund else 'ยืนยันชำระจากบัตรนี้ ' if self.split else 'ยืนยันชำระเงิน '
        self.confirm.setText(prefix+baht(n))
        self.confirm.setEnabled(bool(valid) and self.app.reader_ready)

    def change_card(self):
        if self.locked or self.op or self.app.busy or self.refund:
            return
        # Change the next contribution mode without altering past payments.
        self.split = False
        self.sync_mode()
        self.app.must_remove = bool(self.app.seen_uid)
        self.removed()
        banner(self.notice, 'warning', 'วางบัตรใบอื่นเพื่อชำระยอดที่เหลือ '+baht(self.remaining))

    def enable_split(self):
        if self.locked or self.op or self.app.busy or self.refund:
            return
        self.split = True
        self.sync_mode()
        self.preview()
        if not self.wallet:
            banner(self.notice, 'warning', 'เปิดการแบ่งจ่ายแล้ว • วางบัตรแล้วตรวจยอดที่จะชำระ')

    def pay(self):
        if self.app.busy or self.locked or self.op or not self.wallet or not self.confirm.isEnabled():
            return
        if not self.refund:
            self.confirm_request()
            return

        # Refresh the original card balance before presenting the refund confirmation.
        current, generation = self.app.current, self.generation
        self.locked = True
        self.confirm.setEnabled(False)
        banner(self.notice, 'warning', 'กำลังตรวจยอดเงินล่าสุดของบัตรเดิม')

        def work():
            self.app.verify_physical_card(*current)
            return self.app.db.wallet(current[1], current[0])

        def done(wallet):
            self.locked = False
            if self.closing or generation != self.generation or current != self.app.current:
                self.removed()
                return
            self.wallet = wallet
            self.balance.setText('ยอดเงินในบัตร: '+baht(wallet['balance']))
            self.preview()
            if self.confirm.isEnabled():
                self.confirm_request()

        def failed(message):
            self.locked = False
            self.clear_card_balance()
            banner(self.notice, 'error', 'ยังไม่ได้คืนเงิน • '+message)

        if not self.app.run(work, done, failed):
            self.locked = False

    def confirm_request(self):
        current, generation = self.app.current, self.generation
        amount = self.fixed_amount()
        detail = self.confirm.text()+'\nบัตร: '+current[0]
        if self.refund:
            balance = self.wallet['balance']
            detail += '\nยอดล่าสุด: '+baht(balance)+' • ยอดหลังคืน: '+baht(balance+amount)
        if not self.app.ask('ยืนยันคืนค่าอาหาร' if self.refund else 'ยืนยันชำระค่าอาหาร',
                            detail+'\nวางบัตรไว้จนระบบแจ้งผลสำเร็จ'):
            return
        self.preview()
        if (generation != self.generation or self.app.current != current
                or not self.confirm.isEnabled() or amount != self.fixed_amount()):
            banner(self.notice, 'error', 'บัตรหรือข้อมูลเปลี่ยนแล้ว กรุณาตรวจสอบใหม่')
            return
        self.op = str(uuid.uuid4())
        self.request = dict(kind='REFUND' if self.refund else 'PAY', order=self.oid,
                            uid=current[0], token=current[1], amount=str(amount))
        if self.refund:
            self.request['part'] = self.part['id']
        self.submit()

    def submit(self):
        if self.app.busy or not self.op:
            return
        self.locked = True
        for w in (
            self.confirm, self.change, self.split_btn, self.amount,
            self.edit, self.cancel, self.check, self.abandon,
        ):
            w.setEnabled(False)
        banner(self.notice, 'warning', 'กำลังทำรายการ • กรุณาวางบัตรค้างไว้และรอผล')
        op, request = self.op, dict(self.request)
        self.app.run(
            lambda: self.app.db.perform(op, request, self.app.verify_physical_card),
            self.completed, self.uncertain,
        )

    def completed(self, result):
        self.op = self.request = None
        self.locked = False
        self.check.hide()
        self.abandon.hide()
        for w in (self.change, self.split_btn, self.edit, self.cancel):
            w.setEnabled(True)
        if result.get('error') or result.get('cancelled'):
            banner(self.notice, 'error', result.get('error', 'ยุติคำขอแล้ว • ยังไม่ทำรายการนี้'))
            self.wallet = None
        else:
            # A committed result stays valid even if the card has been removed.
            self.last_payment = dec(result['amount'])
            self.split_next = not self.refund
            self.app.must_remove = bool(self.app.seen_uid)
            self.app.sale_wallet = None
            self.removed()
            banner(
                self.notice, 'success',
                'รายการสำเร็จ '+baht(result['amount'])
                +' • ยอดคงเหลือ '+baht(result['balance'])+' • นำบัตรออกได้',
            )
        self.refresh()

    def uncertain(self, message):
        self.locked = False
        self.confirm.setEnabled(False)
        banner(self.notice, 'error', message+'\nตรวจผลรายการเดิมก่อน • อย่าชำระหรือคืนซ้ำ')
        self.check.show()
        self.check.setEnabled(True)
        if self.op:
            self.abandon.show()
            self.abandon.setEnabled(True)

    def recover(self):
        if self.op:
            self.submit()
        else:
            self.refresh()

    def abandon_op(self):
        if self.app.busy or not self.op:
            return
        if not self.app.ask(
            'ตรวจผลและยุติคำขอ',
            'ถ้ารายการสำเร็จแล้วจะแสดงผลเดิม\nถ้ายังไม่สำเร็จ จะยุติคำขอโดยไม่หักหรือคืนเงินเพิ่ม',
        ):
            return
        self.locked = True
        self.app.run(
            lambda: self.app.db.reject(self.op, self.request),
            lambda result: self.completed(result or dict(cancelled=True)), self.uncertain,
        )

    def cancel_order(self):
        if self.app.busy or self.locked or self.op or not self.o:
            return
        if self.o['state'] == 'OPEN':
            if self.app.ask('ยกเลิกออเดอร์', 'ยังไม่ได้หักเงิน • ยกเลิกออเดอร์นี้?'):
                self.app.run(lambda: self.app.db.cancel_open(self.oid),
                             lambda _: self.finish(), self.uncertain)
        elif self.o['state'] == 'PARTIAL':
            if self.app.ask(
                'ยกเลิกและคืนยอดที่ชำระแล้ว',
                'คืนยอดที่ชำระแล้วทั้งหมด '+baht(self.o['paid']-self.o['returned'])+' เข้าบัตรเดิม?',
            ):
                self.app.run(
                    lambda: self.app.db.plan(self.oid, {}, 'ยกเลิกออเดอร์ชำระบางส่วน', True),
                    self.start_refund, self.uncertain,
                )

    def start_refund(self, _):
        self.refund = True
        self.app.must_remove = False
        self.setWindowTitle('คืนยอดที่ชำระแล้ว')
        self.refresh()

    def edit_order(self):
        if self.app.busy or self.op or not self.o or self.o['state'] != 'OPEN':
            return

        # Cancel the unpaid snapshot before restoring independent cart lines.
        def done(order):
            self.app.cart = {line_key(i): i['qty'] for i in order['items']}
            self.app.cart_notes = {line_key(i): i.get('note', '') for i in order['items']}
            self.app.selected_cart_pid = None
            self.app.note.clear()
            self.finish()

        self.app.run(lambda: self.app.db.cancel_open(self.oid), done, self.uncertain)

    def finish(self):
        self.closing = True
        self.generation += 1
        self.app.render_sale_balance()
        super().accept()

    def reject(self):
        # Never silently park an order after a partial financial transaction.
        if self.closing:
            return
        if self.locked or self.app.busy or self.op:
            banner(self.notice, 'error', 'ตรวจผลรายการเดิมให้เรียบร้อยก่อนปิด')
            return
        if self.o and self.o['state'] == 'OPEN':
            self.cancel_order()
        elif self.o and self.o['state'] in ('PARTIAL', 'REFUND_PENDING'):
            banner(self.notice, 'warning', 'กรุณาชำระต่อให้ครบ หรือคืนยอดที่ชำระแล้วให้ครบก่อนปิด')
        elif self.o:
            self.finish()


# ---------- Main Stall POS application ----------

class StallPOSApp(QMainWindow):
    def active_orders(self):
        return [o for o in self.order_rows if o['state'] in ('OPEN', 'PARTIAL', 'REFUND_PENDING')]

    def fresh_card(self, uid):
        if getattr(self.worker, 'API_VERSION', 0) < 2:
            raise BusinessError('กรุณาใช้ nfc_worker.py ชุดล่าสุด')
        try:
            snapshot = self.worker.read_current_card(uid)
            if not snapshot[1] or not snapshot[2]:
                raise RuntimeError(snapshot[3])
            return snapshot
        except Exception as exc:
            self.last_error = str(exc)
            raise BusinessError(card_error(exc)) from exc

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Food Court Stall POS ['+STALL+']')
        self.setMinimumSize(1080, 680)
        self.db = Store()
        self.busy = False
        self.jobs = set()
        self.ready = False
        self.current = None
        self.reader_ready = False
        self.must_remove = False
        self.checkout = None
        self.card_generation = 0
        self.cart = {}
        self.cart_notes = {}
        self.selected_cart_pid = None
        self.sale_wallet = None
        self.recent_rows = []
        self.products = []
        self.order_rows = []
        self.menu_rows = []
        self.history_rows = []
        self.history_uid = None
        self.pending_rows = []
        self.queue_order_rows = []
        self.categories = []
        self.selected_category = 'All'
        self.category_buttons = []
        self.public = None
        self.saved_shop_name = STALL
        self.seen_uid = None
        self.last_error = ''
        self.creating_oid = None
        self.card_retry_at = 0
        self.image_cache = {}
        self.bridge = Bridge()
        self.bridge.tag.connect(self.tag)
        self.bridge.removed.connect(self.removed)
        self.build()
        self.worker = NFCWorker(
            on_tag_detected=self.bridge.tag.emit, on_tag_removed=self.bridge.removed.emit,
        )
        self.worker.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(800)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.auto_refresh)
        self.poll.start(15000)
        self.run(self.db.init, self.initialized, self.initialization_failed)

    def verify_physical_card(self, uid, token):
        if getattr(self.worker, 'API_VERSION', 0) < 2:
            raise BusinessError('กรุณาใช้ nfc_worker.py ชุดล่าสุด')
        try:
            return self.worker.verify_current_card(uid, token)
        except Exception as exc:
            self.last_error = str(exc)
            raise BusinessError(card_error(exc)) from exc

    def run(self, fn, done=None, failed=None):
        """Run blocking database and hardware work outside the GUI thread."""
        if self.busy:
            return False
        self.busy = True
        self.pages.setEnabled(False)
        for nav in self.nav:
            nav.setEnabled(False)
        job = Job(fn, self)
        self.jobs.add(job)

        def unlock():
            self.busy = False
            self.pages.setEnabled(True)
            for nav in self.nav:
                nav.setEnabled(True)

        def ok(result):
            unlock()
            if done:
                done(result)

        def error(message):
            unlock()
            if failed:
                failed(message)
            else:
                self.message(message)

        job.done.connect(ok)
        job.error.connect(error)
        job.finished.connect(lambda: self.jobs.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()
        return True

    def message(self, text):
        QMessageBox.information(self, 'Stall POS', text)

    def ask(self, title, text):
        return ConfirmDialog(title, text, self).exec() == QDialog.DialogCode.Accepted

    def build(self):
        root = QWidget()
        self.setCentralWidget(root)
        b = QVBoxLayout(root)
        b.setContentsMargins(18, 14, 18, 14)
        header, h = panel()
        row = QHBoxLayout()
        self.heading = lab('ร้านอาหาร • '+STALL, 'title')
        row.addWidget(self.heading, 1)
        self.reader = lab('Reader: Connecting…')
        self.db_status = lab('Database: Connecting…')
        for status_label in (self.reader, self.db_status):
            status_label.setMinimumWidth(205)
            status_label.setMinimumHeight(42)
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setWordWrap(False)
            status_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row.addWidget(self.reader)
        row.addWidget(self.db_status)
        self.terminal_label = lab(STALL)
        row.addWidget(self.terminal_label)
        row.addWidget(button('รายละเอียดทางเทคนิค', self.technical))
        h.addLayout(row)
        b.addWidget(header)

        row = QHBoxLayout()
        self.nav = []
        for index, name in enumerate(('ขายอาหาร', 'คิวอาหาร', 'ประวัติธุรกรรม', 'จัดการเมนู')):
            w = button(name, lambda _, i=index: self.navigate(i))
            w.setCheckable(True)
            row.addWidget(w)
            self.nav.append(w)
        row.addStretch()
        self.pending_button = button('รายการต้องตรวจสอบ', self.show_pending)
        self.pending_button.hide()
        row.addWidget(self.pending_button)
        b.addLayout(row)
        self.notice = lab('', 'noticeInfo')
        banner(self.notice, 'info', 'กำลังเชื่อมต่อฐานข้อมูล')
        b.addWidget(self.notice)
        self.pages = QStackedWidget()
        b.addWidget(self.pages, 1)
        self.sale_page()
        self.queue_page()
        self.history_page()
        self.menu_page()
        self.nav[0].setChecked(True)

    def sale_page(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)

        # Menu column: only the menu list scrolls.
        left, b = panel()
        b.addWidget(lab('เมนูอาหาร', 'title'))

        self.menu_search = QLineEdit()
        self.menu_search.setPlaceholderText('ค้นหาเมนู…')
        self.menu_search.setClearButtonEnabled(True)
        self.menu_search.textChanged.connect(self.render_menu)
        b.addWidget(self.menu_search)

        categories = QScrollArea()
        categories.setWidgetResizable(True)
        categories.setFixedHeight(64)
        categories.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        category_widget = QWidget()
        self.category_layout = QHBoxLayout(category_widget)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setSpacing(8)
        categories.setWidget(category_widget)
        b.addWidget(categories)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.menu_tiles = QWidget()
        self.grid = QGridLayout(self.menu_tiles)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.menu_tiles)
        b.addWidget(scroll, 1)

        # Cart column: the table shrinks while note controls remain visible.
        center, b = panel()
        b.addWidget(lab('ออเดอร์ปัจจุบัน', 'title'))

        self.cart_table = table(['ที่', 'อาหาร', 'จำนวน', 'ราคา', 'รวม', 'หมายเหตุ', 'ลบ'])
        self.cart_table.verticalHeader().setDefaultSectionSize(68)
        self.cart_table.setWordWrap(True)
        self.cart_table.setMinimumHeight(100)
        self.cart_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )

        for col, width in ((0, 36), (2, 128), (3, 85), (4, 90), (6, 46)):
            self.cart_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Fixed,
            )
            self.cart_table.setColumnWidth(col, width)

        self.cart_table.itemSelectionChanged.connect(self.select_cart_note)
        b.addWidget(self.cart_table, 1)

        self.note_for = lab('หมายเหตุอาหาร • เลือกรายการก่อน', 'instruction')
        b.addWidget(self.note_for)

        self.note = QLineEdit()
        self.note.setMaxLength(250)
        self.note.setPlaceholderText('เช่น ไม่เผ็ด ไม่ใส่น้ำแข็ง')
        b.addWidget(self.note)

        self.save_note = button(
            'บันทึกหมายเหตุให้รายการที่เลือก', self.save_cart_note, True,
        )
        b.addWidget(self.save_note)
        self.note.returnPressed.connect(self.save_cart_note)

        # Payment column: keep balance information and actions on screen.
        right, b = panel()
        b.setContentsMargins(12, 10, 12, 10)
        b.setSpacing(6)
        b.addWidget(lab('สรุปการชำระเงิน', 'title'))

        self.total = lab('฿0.00', 'money')
        self.count = lab('จำนวนรวม: 0')
        b.addWidget(self.count)
        b.addWidget(self.total)

        card, cb = panel()
        cb.setContentsMargins(10, 8, 10, 8)
        cb.setSpacing(6)
        card.setStyleSheet(
            'QFrame#panel{background:#edf5ff;'
            'border:1px solid #bdd3ff;border-radius:12px;}'
        )

        self.sale_card_info = lab('แตะบัตรเพื่อดูยอดก่อนชำระ')
        self.sale_card_info.setStyleSheet(
            'font-size:17px;font-weight:bold;color:#164ca1;'
        )

        self.sale_card_amount = lab('—', 'money')
        self.sale_card_amount.setStyleSheet(
            'font-size:28px;font-weight:bold;color:#215be8;'
        )

        self.sale_after = lab('ยังไม่หักเงิน • ต้องกดยืนยันก่อน')
        self.sale_after.setStyleSheet(
            'font-size:18px;font-weight:bold;padding:0;color:#164ca1;'
        )

        for label in (
            self.sale_card_info,
            self.sale_card_amount,
            self.sale_after,
        ):
            label.setMinimumHeight(28)
            label.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Minimum,
            )
            cb.addWidget(label)

        # Use the required content height without stretching the balance card.
        card.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        b.addWidget(card)

        self.proceed = button(
            'ตรวจสอบและชำระเงิน', self.begin_payment, True,
        )
        self.proceed.setEnabled(False)
        b.addWidget(self.proceed)
        b.addWidget(button('ล้างรายการอาหาร', self.clear_cart))

        b.addWidget(lab('รายการขายล่าสุด'))
        self.recent = table(['เวลา', 'คิว', 'ยอดรวม'])
        self.recent.setMinimumHeight(72)
        self.recent.verticalHeader().setDefaultSectionSize(32)
        self.recent.horizontalHeader().setStyleSheet('QHeaderView::section{padding:5px;}')
        self.recent.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent_key = None
        self.recent.setMaximumHeight(125)
        self.recent.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.recent.cellDoubleClicked.connect(
            lambda r, c: self.order_detail(self.recent_rows[r]['id'])
        )
        b.addWidget(self.recent, 1)
        b.addWidget(button('ดูออเดอร์และสลิป', self.show_orders))

        row.addWidget(left, 32)
        row.addWidget(center, 43)
        row.addWidget(right, 25)

        # Do not wrap the entire sales page in another scroll area.
        self.pages.addWidget(page)

    def queue_page(self):
        page, b = panel()
        row = QHBoxLayout()
        row.addWidget(lab('คิวอาหาร', 'title'), 1)
        row.addWidget(button('รีเฟรช', self.refresh_all))
        row.addWidget(button('จอคิวลูกค้า', self.show_public))
        b.addLayout(row)
        self.queue_board = QHBoxLayout()
        self.queue_boxes = {}
        for state, title in (('WAITING', 'รอทำ'), ('PREPARING', 'กำลังทำ'), ('READY', 'พร้อมรับ')):
            col, box = panel()
            col.setObjectName({
                'WAITING': 'queueWaiting', 'PREPARING': 'queuePreparing', 'READY': 'queueReady',
            }[state])
            box.addWidget(lab(title, 'title'))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            cards = QVBoxLayout(content)
            cards.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(content)
            box.addWidget(scroll, 1)
            self.queue_boxes[state] = cards
            self.queue_board.addWidget(col, 1)
        b.addLayout(self.queue_board, 1)
        self.pages.addWidget(page)

    def history_page(self):
        page, b = panel()
        row = QHBoxLayout()
        row.addWidget(lab('ประวัติธุรกรรม', 'title'), 1)
        row.addWidget(button('ดูรายการทั้งหมด', self.all_history))
        row.addWidget(button('รีเฟรช', self.refresh_history))
        b.addLayout(row)
        self.history_label = lab('รายการของ '+STALL+' รวมออเดอร์เดิมที่นำเข้าประวัติ', 'muted')
        b.addWidget(self.history_label)
        self.history_filter = lab('ยังไม่ได้กรอง Card ID', 'instruction')
        b.addWidget(self.history_filter)
        self.history_table = table([
            'วัน / เวลา', 'ออเดอร์', 'คิว', 'Card ID', 'ประเภท', 'จำนวนเงิน', 'ยอดหลังรายการ',
        ])
        self.history_table.cellDoubleClicked.connect(self.history_click)
        b.addWidget(self.history_table, 1)
        row = QHBoxLayout()
        row.addWidget(button('รายละเอียดออเดอร์', self.selected_history))
        b.addLayout(row)
        self.pages.addWidget(page)

    def menu_page(self):
        page, b = panel()
        row = QHBoxLayout()
        self.menu_heading = lab('จัดการเมนู • '+STALL, 'title')
        row.addWidget(self.menu_heading, 1)
        row.addWidget(button('เพิ่มเมนู', lambda: self.edit_menu(), True))
        row.addWidget(button('จัดการหมวด', self.manage_categories))
        b.addLayout(row)
        self.shop_name = QLineEdit()
        self.shop_name.setReadOnly(True)
        b.addWidget(self.shop_name)
        self.menu_table = table(['รูป', 'ชื่อ', 'หมวด', 'ราคา', 'สถานะ', 'รายละเอียด'])
        b.addWidget(self.menu_table, 1)
        row = QHBoxLayout()
        row.addWidget(button('แก้ไข', lambda: self.edit_menu(self.selected_menu())))
        row.addWidget(button('เปิด / ปิดขาย', self.toggle_menu))
        row.addWidget(button('ลบเมนู', self.delete_menu, danger=True))
        b.addLayout(row)
        self.pages.addWidget(page)

    def initialized(self, _):
        self.ready = True
        pill(self.db_status, 'ready', 'ฐานข้อมูล: เชื่อมต่อแล้ว')
        banner(self.notice, 'info', 'เลือกอาหารและตรวจรายการก่อนชำระเงิน')
        self.refresh_all()

    def initialization_failed(self, message):
        self.ready = False
        self.last_error = message
        pill(self.db_status, 'error', 'ฐานข้อมูล: ไม่พร้อม')
        banner(self.notice, 'error', 'ยังเชื่อมต่อฐานข้อมูลไม่ได้ • กดเชื่อมต่อใหม่ในรายละเอียดทางเทคนิค')
        self.proceed.setEnabled(False)

    def navigate(self, index):
        if self.busy:
            return
        self.pages.setCurrentIndex(index)
        for i, w in enumerate(self.nav):
            w.setChecked(i == index)
        notices = {
            0: ('info', 'เลือกอาหารและตรวจรายการก่อนชำระเงิน'),
            1: ('info', 'เลือกคิว แล้วอัปเดตสถานะอาหาร'),
            2: ('info', 'ดับเบิลคลิก Card ID เพื่อดูเฉพาะบัตรนี้'),
            3: ('info', 'เลือกเมนูที่ต้องการแก้ไข หรือกดเพิ่มเมนู'),
        }
        if self.ready:
            banner(self.notice, *notices[index])
        else:
            banner(self.notice, 'error', 'ยังเชื่อมต่อฐานข้อมูลไม่ได้ • ไม่สามารถโหลดข้อมูลหรือทำรายการ')
        if index == 2:
            self.refresh_history()
        else:
            self.refresh_all()

    def refresh_all(self):
        if not self.ready or self.busy:
            return

        def fetch():
            return (
                self.db.products(True), self.db.categories(), self.db.orders(),
                self.db.pending(), self.db.orders(True), self.db.stall_name(),
            )

        def done(data):
            (self.products, self.categories, self.order_rows, self.pending_rows,
             self.queue_order_rows, name) = data
            self.saved_shop_name = name
            self.heading.setText(name+' • '+STALL)
            self.terminal_label.setText(STALL)
            self.menu_heading.setText('จัดการเมนู • '+STALL)
            self.shop_name.setText(name+' • '+STALL)
            self.render_categories()
            self.render_menu()
            self.menu_rows = self.products
            fill(self.menu_table, [
                ('', p['product_name'], p['category'], baht(p['price']),
                 'เปิดขาย' if p['is_available'] else 'ปิดขาย', p['description'])
                for p in self.menu_rows
            ])
            self.menu_table.setColumnWidth(0, 100)
            self.menu_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            for r, p in enumerate(self.menu_rows):
                self.menu_table.setCellWidget(r, 0, picture(p.get('image_data'), 90, 65))
                self.menu_table.setRowHeight(r, 76)
                self.menu_table.item(r, 4).setForeground(
                    QColor('#15803d' if p['is_available'] else '#64748b')
                )
            recent = [o for o in self.order_rows if o['state'] == 'PAID'][:10]
            rows = [(str(o['created'])[11:19], f"Q{o['queue_no']:03}" if o['queue_no'] else '—', baht(o['total']-o['returned'])) for o in recent]
            key = [(o['id'], row) for o, row in zip(recent, rows)]
            if key != self.recent_key:
                scroll = self.recent.verticalScrollBar()
                position = scroll.value()
                self.recent_rows = recent
                self.recent_key = key
                fill(self.recent, rows)
                scroll.setValue(position)
            self.update_pending_button()
            self.render_queue()
            self.render_cart()
            if self.pending_rows or self.active_orders():
                banner(self.notice, 'warning', 'มีรายการเดิมที่ยังไม่จบ • เปิดรายการต้องตรวจสอบก่อนเริ่มขายใหม่')
            if self.public:
                self.update_public()

        def failed(message):
            self.last_error = message
            self.ready = False
            pill(self.db_status, 'error', 'ฐานข้อมูล: ไม่พร้อม')
            self.proceed.setEnabled(False)
            banner(self.notice, 'error', 'โหลดข้อมูลไม่สำเร็จ • กรุณาลองเชื่อมต่อใหม่')

        self.run(fetch, done, failed)

    def update_pending_button(self):
        count = len(self.pending_rows) or len(self.active_orders())
        self.pending_button.setVisible(bool(count))
        self.pending_button.setText('รายการต้องตรวจสอบ ('+str(count)+')')

    def save_shop_name(self):
        self.message('การแก้ชื่อร้านให้ดำเนินการผ่านผู้ดูแลระบบ')

    def render_categories(self):
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        preferred = ['Rice', 'Noodles', 'Drinks']
        names = (
            ['All']+[n for n in preferred if n in self.categories]
            +[n for n in self.categories if n not in preferred]
        )
        if self.selected_category not in names:
            self.selected_category = 'All'
        self.category_buttons = []
        for name in names:
            tab = button(name, lambda _, n=name: self.choose_category(n))
            tab.setObjectName('category')
            tab.setCheckable(True)
            tab.setChecked(name == self.selected_category)
            self.category_layout.addWidget(tab)
            self.category_buttons.append(tab)
        self.category_layout.addStretch()

    def choose_category(self, name):
        self.selected_category = name
        for tab in self.category_buttons:
            tab.setChecked(tab.text() == name)
        self.render_menu()

    def render_menu(self, *_):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.menu_search.text().strip().lower()
        products = [
            p for p in self.products if p['is_available']
            and (self.selected_category == 'All' or p['category'] == self.selected_category)
            and (not query or query in (
                p['product_name']+' '+p['category']+' '+p['description']
            ).lower())
        ]
        if not products:
            text = (
                'ยังโหลดเมนูไม่ได้ • กรุณาเชื่อมต่อฐานข้อมูล' if not self.ready
                else 'ไม่พบเมนูที่เปิดขายตามเงื่อนไขนี้'
            )
            self.grid.addWidget(lab(text, 'muted'), 0, 0, 1, 2)
            return
        for index, p in enumerate(products):
            frame, box = panel()
            box.setContentsMargins(10, 10, 10, 10)
            box.addWidget(picture(p.get('image_data'), 156, 100), 0, Qt.AlignmentFlag.AlignHCenter)
            title = lab(p['product_name'])
            title.setStyleSheet('font-size:19px;font-weight:bold;')
            box.addWidget(title)
            price = lab(baht(p['price']))
            price.setStyleSheet('font-size:26px;font-weight:bold;color:#215be8;')
            box.addWidget(price)
            add = button('เพิ่มอาหาร', lambda _, pid=p['product_id']: self.add_cart(pid), True)
            add.setEnabled(self.ready and not self.busy)
            box.addWidget(add)
            self.grid.addWidget(frame, index//2, index%2)

    # ---------- Independent cart lines and per-serving notes ----------

    def add_cart(self, pid):
        if self.busy or not self.cache_cart_note():
            return
        # Only combine plain lines; noted items never absorb a new plain item.
        key = next((
            k for k in self.cart if product_id(k) == pid
            and not self.cart_notes.get(k) and self.cart[k] < 999
        ), None)
        if key is None:
            key = str(pid)+':'+uuid.uuid4().hex
            self.cart[key] = 0
            self.cart_notes[key] = ''
        self.cart[key] += 1
        self.selected_cart_pid = key
        self.note.setText(self.cart_notes.get(key, ''))
        self.render_cart()

    def render_cart(self):
        # Periodic refreshes must not commit an unfinished note edit.
        lookup = {p['product_id']: p for p in self.products}
        for key in list(self.cart):
            pid = product_id(key)
            if pid not in lookup or not lookup[pid]['is_available']:
                self.cart.pop(key)
                self.cart_notes.pop(key, None)
                banner(self.notice, 'warning', 'เมนูในตะกร้าบางรายการปิดขายแล้ว กรุณาตรวจสอบใหม่')

        self.cart_table.blockSignals(True)
        self.cart_table.clearContents()
        self.cart_table.setRowCount(len(self.cart))
        total = Decimal(0)
        for r, (key, qty) in enumerate(self.cart.items()):
            p = lookup[product_id(key)]
            subtotal = dec(p['price'])*qty
            total += subtotal
            for col, value in (
                (0, str(r+1)), (1, p['product_name']), (3, baht(p['price'])),
                (4, baht(subtotal)), (5, self.cart_notes.get(key) or '—'),
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, key)
                if col == 0 or value == '—':
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif col in (3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.cart_table.setItem(r, col, item)
            controls = QuantityControl(qty, 999, minimum=1)
            controls.valueChanged.connect(lambda value, k=key: self.set_qty(k, value))
            self.cart_table.setCellWidget(r, 2, controls)
            delete = button('×', lambda _, k=key: self.remove_cart(k), danger=True)
            delete.setObjectName('quantity')
            self.cart_table.setCellWidget(r, 6, delete)
            if key == self.selected_cart_pid:
                self.cart_table.selectRow(r)
        self.cart_table.blockSignals(False)

        key = self.selected_cart_pid
        enabled = key in self.cart
        self.note.setEnabled(enabled)
        self.save_note.setEnabled(enabled)
        self.note_for.setText(
            'หมายเหตุสำหรับ: '+lookup[product_id(key)]['product_name']
            if enabled else 'หมายเหตุอาหาร • เลือกรายการก่อน'
        )
        if not enabled:
            self.selected_cart_pid = None
            self.note.clear()
        self.total.setText(baht(total))
        self.count.setText('จำนวนรวม: '+str(sum(self.cart.values()))+' หน่วย')
        self.proceed.setEnabled(
            self.ready and bool(self.cart) and total <= MAX
            and not self.pending_rows and not self.active_orders()
        )
        self.render_sale_balance()

    def cache_cart_note(self):
        key = self.selected_cart_pid
        if key not in self.cart:
            return True
        text = self.note.text().strip()
        if text == self.cart_notes.get(key, ''):
            return True
        qty = self.cart[key]
        if qty > 1:
            count, ok = QInputDialog.getInt(
                self, 'หมายเหตุสำหรับกี่จาน',
                'จำนวนจานที่ใช้หมายเหตุนี้ (แยกจากจานที่เหลือ)', 1, 1, qty,
            )
            if not ok:
                return False
            if count < qty:
                self.cart[key] -= count
                new_key = str(product_id(key))+':'+uuid.uuid4().hex
                self.cart[new_key] = count
                self.cart_notes[new_key] = text
                self.selected_cart_pid = new_key
                return True
        self.cart_notes[key] = text
        return True

    def select_cart_note(self):
        r = self.cart_table.currentRow()
        item = self.cart_table.item(r, 1) if r >= 0 else None
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if key == self.selected_cart_pid:
            return
        if not self.cache_cart_note():
            self.render_cart()
            return
        self.selected_cart_pid = key
        self.note.setText(self.cart_notes.get(key, ''))
        self.render_cart()

    def save_cart_note(self):
        if self.selected_cart_pid in self.cart and self.cache_cart_note():
            self.note.setText(self.cart_notes.get(self.selected_cart_pid, ''))
            self.render_cart()
            banner(self.notice, 'success', 'บันทึกหมายเหตุอาหารแล้ว')

    def set_qty(self, key, n):
        if key not in self.cart or self.busy:
            return
        self.cart[key] = max(1, min(999, n))
        QTimer.singleShot(0, self.render_cart)

    def change_qty(self, key, delta):
        if key in self.cart:
            self.set_qty(key, self.cart[key]+delta)

    def remove_cart(self, key):
        if not self.cache_cart_note():
            return
        self.cart.pop(key, None)
        self.cart_notes.pop(key, None)
        if self.selected_cart_pid == key:
            self.selected_cart_pid = None
            self.note.clear()
        self.render_cart()

    def clear_cart(self):
        if self.cart and not self.ask('ล้างตะกร้า', 'ล้างอาหารที่ยังไม่ได้สร้างออเดอร์?'):
            return
        self.cart.clear()
        self.cart_notes.clear()
        self.selected_cart_pid = None
        self.note.clear()
        self.render_cart()

    def begin_payment(self):
        if not self.ready or not self.cart or self.busy or self.pending_rows:
            return
        if self.active_orders():
            self.message('กรุณาจัดการออเดอร์เดิมให้เสร็จก่อนเริ่มออเดอร์ใหม่')
            return
        if not self.cache_cart_note():
            return

        # Reuse the same order ID after a lost create response.
        self.creating_oid = self.creating_oid or str(uuid.uuid4())
        oid, cart, notes = self.creating_oid, dict(self.cart), dict(self.cart_notes)

        def done(_):
            self.creating_oid = None
            self.cart.clear()
            self.cart_notes.clear()
            self.selected_cart_pid = None
            self.note.clear()
            self.render_cart()
            self.open_checkout(oid)

        self.run(lambda: self.db.create(oid, cart, '', notes), done)

    def open_checkout(self, oid, refund=False):
        if self.busy or self.pending_rows:
            self.message('ตรวจผลคำขอเดิมในรายการต้องตรวจสอบก่อน')
            return
        if self.active_orders() and not any(o['id'] == oid for o in self.active_orders()):
            self.message('กรุณาจัดการออเดอร์เดิมให้เสร็จก่อนเปิดรายการอื่น')
            return
        if oid == self.creating_oid:
            self.creating_oid = None
            self.cart.clear()
            self.cart_notes.clear()
            self.selected_cart_pid = None
            self.note.clear()
        self.checkout = Checkout(self, oid, refund)
        self.checkout.exec()
        self.checkout = None
        self.pages.setCurrentIndex(0)
        for i, w in enumerate(self.nav):
            w.setChecked(i == 0)
        self.refresh_all()

    # ---------- Card presence, balance inquiry and connection state ----------

    def tag(self, uid, valid, token, status):
        self.card_generation += 1
        if uid != self.seen_uid:
            self.must_remove = False
        self.seen_uid = uid
        self.sale_wallet = None
        self.current = (uid, token) if valid and token else None
        self.card_retry_at = 0
        self.render_sale_balance()
        if self.must_remove:
            banner(self.notice, 'warning', 'นำบัตรจากรายการก่อนออกก่อนเริ่มรายการใหม่')
            return
        if self.checkout:
            self.checkout.on_card()
        elif not self.busy:
            self.read_sale_card()

    def removed(self):
        self.card_generation += 1
        self.seen_uid = self.current = None
        self.sale_wallet = None
        self.must_remove = False
        if self.checkout:
            self.checkout.removed()
        self.render_sale_balance()

    def tick(self):
        import time
        connection = getattr(self.worker, '_serial_conn', None)
        ready = bool(
            self.worker.is_alive() and getattr(self.worker, '_pn532', None)
            and connection and connection.is_open
        )
        pill(self.reader, 'ready' if ready else 'error',
             'เครื่องอ่าน: พร้อม' if ready else 'เครื่องอ่าน: ไม่เชื่อมต่อ')
        if self.reader_ready and not ready:
            self.removed()
        self.reader_ready = ready
        if self.checkout:
            self.checkout.preview()
            if (ready and self.seen_uid and not self.must_remove and not self.busy
                    and self.checkout.o and not self.checkout.wallet
                    and not self.checkout.op and not self.checkout.locked
                    and time.monotonic() >= self.card_retry_at):
                self.card_retry_at = time.monotonic()+3
                self.checkout.read_card()
        elif (ready and self.seen_uid and not self.sale_wallet and not self.must_remove
              and not self.busy and self.ready and self.pages.currentIndex() == 0
              and not QApplication.activeModalWidget() and time.monotonic() >= self.card_retry_at):
            self.card_retry_at = time.monotonic()+3
            self.read_sale_card()
        if self.public:
            self.update_public()

    def auto_refresh(self):
        if not self.busy and not self.checkout and not QApplication.activeModalWidget():
            if self.pages.currentIndex() == 2:
                self.refresh_history()
            else:
                self.refresh_all()

    def technical(self):
        d = QDialog(self)
        d.setWindowTitle('รายละเอียดทางเทคนิค')
        d.resize(760, 460)
        b = QVBoxLayout(d)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            'Stall: '+STALL+'\nNFC port: '+self.worker.port+'\n'
            +self.reader.text()+'\n'+self.db_status.text()
            +'\nCard UID: '+str(self.seen_uid or '—')
            +'\nToken UUID: '+str(self.current[1] if self.current else '—')
            +'\nOperation ID: '+str(self.checkout.op if self.checkout and self.checkout.op else '—')
            +'\nLast error: '+str(self.last_error or self.worker.last_error or '—')
        )
        b.addWidget(text)

        def reconnect():
            d.accept()
            self.run(self.db.init, self.initialized, self.initialization_failed)

        b.addWidget(button('เชื่อมต่อฐานข้อมูลใหม่', reconnect))
        b.addWidget(button('ปิด', d.reject))
        d.exec()

    def read_sale_card(self):
        if (not self.ready or not self.seen_uid or self.busy
                or self.must_remove or self.pages.currentIndex() != 0):
            return
        uid, generation = self.seen_uid, self.card_generation

        def work():
            snapshot = self.fresh_card(uid)
            return snapshot, self.db.wallet(snapshot[2], uid)

        def done(data):
            if generation != self.card_generation or uid != self.seen_uid:
                return
            snapshot, self.sale_wallet = data
            self.current = (uid, snapshot[2])
            self.render_sale_balance()
            banner(self.notice, 'info', 'อ่านยอดเงินแล้ว • ยังไม่หักเงินจนกดยืนยัน')

        def failed(message):
            if generation == self.card_generation:
                self.sale_wallet = None
                self.current = None
                self.sale_card_info.setText(message)
                self.sale_card_amount.setText('—')
                self.sale_after.setText('ยังไม่ทำรายการ')
                banner(self.notice, 'error', message)

        self.run(work, done, failed)

    def render_sale_balance(self):
        if self.must_remove:
            self.sale_card_info.setText('รายการก่อนเสร็จแล้ว • กรุณานำบัตรออก')
            self.sale_card_amount.setText('—')
            self.sale_after.setText('รอบัตรสำหรับรายการถัดไป')
            return
        if not self.sale_wallet:
            self.sale_card_info.setText('กำลังอ่านยอด…' if self.seen_uid else 'วางบัตรเพื่อดูยอดเงิน')
            self.sale_card_amount.setText('—')
            self.sale_after.setText('ยังไม่หักเงิน • ต้องกดยืนยันก่อน')
            return
        wallet = self.sale_wallet
        self.sale_card_info.setText('ยอดเงินในบัตร • '+wallet['card_uid'])
        self.sale_card_amount.setText(baht(wallet['balance']))
        if wallet['status'] != 'ACTIVE':
            self.sale_after.setText('บัตรนี้ยังใช้ชำระไม่ได้ • ติดต่อจุดบริการบัตร')
            return
        lookup = {p['product_id']: p for p in self.products}
        total = sum((
            dec(lookup[product_id(key)]['price'])*qty
            for key, qty in self.cart.items() if product_id(key) in lookup
        ), Decimal(0))
        left = wallet['balance']-total
        self.sale_after.setText(
            'ยอดคาดว่าจะเหลือ: '+baht(left) if left >= 0
            else 'ยอดเงินไม่พอ • ขาดอีก '+baht(-left)
        )

    # ---------- Transaction history and recovery ----------

    def refresh_history(self):
        if not self.ready or self.busy:
            return
        uid = self.history_uid

        def done(rows):
            self.history_rows = rows
            self.history_label.setText(
                ('Card ID: '+uid+' • ' if uid else '')+'รายการของ '+STALL+' (ล่าสุดสูงสุด 300)'
            )
            self.history_filter.setText(
                'กำลังแสดง Card ID: '+uid if uid else 'ดับเบิลคลิก Card ID เพื่อดูเฉพาะบัตรนี้'
            )
            self.history_filter.setStyleSheet('color:#164ca1;font-size:17px;font-weight:bold;padding:8px;')
            fill(self.history_table, [
                (str(r['created'])[:19], r['order_id'][:8],
                 f"Q{r['queue_no']:03}" if r['queue_no'] else '—', r['uid'],
                 'ชำระอาหาร' if r['kind'] == 'PAY' else 'คืนค่าอาหาร',
                 ('−' if r['kind'] == 'PAY' else '+')+baht(r['amount']), baht(r['balance']))
                for r in rows
            ])
            for index, row in enumerate(rows):
                self.history_table.item(index, 3).setForeground(QColor('#2563eb'))
                color = QColor('#15803d' if row['kind'] != 'PAY' else '#215be8')
                self.history_table.item(index, 4).setForeground(color)
                self.history_table.item(index, 5).setForeground(color)

        self.run(lambda: self.db.history(uid), done)

    def all_history(self):
        self.history_uid = None
        self.refresh_history()

    def history_click(self, r, c):
        if c == 3:
            self.history_uid = self.history_rows[r]['uid']
            self.refresh_history()
        else:
            self.order_detail(self.history_rows[r]['order_id'])

    def selected_history(self):
        r = self.history_table.currentRow()
        if r >= 0:
            self.order_detail(self.history_rows[r]['order_id'])

    def show_orders(self):
        if self.busy:
            return

        def done(rows):
            # In-progress orders are handled by the recovery dialog.
            rows = [o for o in rows if o['state'] in ('PAID', 'CANCELLED')]
            d = QDialog(self)
            d.setWindowTitle('ออเดอร์ย้อนหลังและสลิป')
            d.resize(1000, 600)
            b = QVBoxLayout(d)
            if not rows:
                b.addWidget(lab('ยังไม่มีออเดอร์ย้อนหลัง', 'muted'))
            t = table(['วันเวลา', 'ออเดอร์', 'ยอดรวม', 'จ่ายแล้ว', 'คืนแล้ว', 'สถานะ'])
            fill(t, [
                (str(o['created'])[:19], o['id'][:8], baht(o['total']),
                 baht(o['paid']), baht(o['returned']), o['state']) for o in rows
            ])
            b.addWidget(t)

            def choose():
                r = t.currentRow()
                if r < 0:
                    return
                d.accept()
                self.order_detail(rows[r]['id'])

            details = button('รายละเอียดออเดอร์', choose, True)
            details.setEnabled(False)
            t.itemSelectionChanged.connect(lambda: details.setEnabled(t.currentRow() >= 0))
            b.addWidget(details)
            b.addWidget(button('ปิด', d.reject))
            d.exec()

        self.run(self.db.orders, done)

    def show_pending(self):
        if self.busy:
            return

        def fetch():
            return self.db.orders(), self.db.pending()

        def done(data):
            orders, rows = data
            self.pending_rows = rows
            d = QDialog(self)
            d.setWindowTitle('รายการค้าง / ตรวจผล')
            d.resize(1180, 700)
            b = QVBoxLayout(d)
            b.addWidget(lab('รายการค้าง / ตรวจผล', 'title'))
            warning = lab('', 'noticeError')
            banner(warning, 'error', 'ตรวจสอบผลคำขอเดิมก่อน ห้ามเริ่มรายการซ้ำ')
            b.addWidget(warning)
            body = QHBoxLayout()
            left, lb = panel()
            lb.addWidget(lab('ออเดอร์ที่ยังไม่เสร็จสมบูรณ์', 'title'))
            active = [o for o in orders if o['state'] in ('OPEN', 'PARTIAL', 'REFUND_PENDING')]
            ot = table(['ออเดอร์', 'ยอดรวม', 'ชำระแล้ว', 'คืนแล้ว', 'สถานะ'])
            fill(ot, [
                (o['id'][:8], baht(o['total']), baht(o['paid']), baht(o['returned']), o['state'])
                for o in active
            ])
            lb.addWidget(ot, 1)

            def open_order():
                r = ot.currentRow()
                if r < 0:
                    return
                o = active[r]
                d.accept()
                self.open_checkout(o['id'], o['state'] == 'REFUND_PENDING')

            lb.addWidget(button('เปิดทำต่อ', open_order, True))
            right, rb = panel()
            rb.addWidget(lab('คำขอที่รอตรวจผล', 'title'))
            pt = table(['Reference ID', 'ประเภท', 'Card ID', 'จำนวนเงิน', 'สถานะ'])
            fill(pt, [
                (p['id'][:12], p['request'].get('kind', '—'), p['request'].get('uid', '—'),
                 baht(p['request'].get('amount', 0)), 'PENDING') for p in rows
            ])
            rb.addWidget(pt, 1)
            rb.addWidget(lab('เลือกคำขอเดิมเพื่อดำเนินการด้วยเลขอ้างอิงเดิม', 'instruction'))

            def recover():
                r = pt.currentRow()
                if r < 0:
                    return
                p = rows[r]
                d.accept()
                self.checkout = Checkout(
                    self, p['request']['order'], p['request']['kind'] == 'REFUND',
                )
                self.checkout.op, self.checkout.request = p['id'], p['request']
                self.checkout.uncertain('คำขอนี้ต้องตรวจผลก่อนเริ่มคำขอใหม่')
                self.checkout.exec()
                self.checkout = None
                self.refresh_all()

            rb.addWidget(button('ตรวจสอบผล / ดำเนินรายการเดิม', recover, True))
            body.addWidget(left, 1)
            body.addWidget(right, 1)
            b.addLayout(body, 1)
            row = QHBoxLayout()
            row.addWidget(button('รายละเอียดทางเทคนิค', lambda: self.technical()))
            row.addStretch()
            row.addWidget(button('ปิด', d.reject))
            b.addLayout(row)
            d.exec()
            self.refresh_all()

        self.run(fetch, done)

    def order_detail(self, oid):
        if self.busy:
            return

        def done(o):
            dialog = ReceiptDialog(o, self, allow_refund=True)
            dialog.exec()
            if dialog.refund_requested:
                self.refund_dialog(oid)

        self.run(lambda: self.db.order(oid), done)

    # ---------- Select refundable lines and quantities ----------

    def refund_dialog(self, oid):
        if any(o['id'] != oid for o in self.active_orders()):
            self.message('จัดการออเดอร์เดิมให้เสร็จก่อนคืนเงินรายการอื่น')
            return
        if self.busy:
            return

        def done(o):
            if o['state'] == 'REFUND_PENDING':
                self.message('มีรายการคืนเงินค้างอยู่ กรุณาเปิดรายการต้องตรวจสอบเพื่อทำต่อ')
                return
            if o['state'] not in ('PAID', 'PARTIAL'):
                self.message('ออเดอร์นี้ไม่พร้อมคืนค่าอาหาร')
                return
            if o['state'] == 'PARTIAL':
                if self.ask('ยกเลิกชำระบางส่วน', 'คืนยอดที่จ่ายแล้วทั้งหมดเข้าบัตรเดิม?'):
                    self.run(
                        lambda: self.db.plan(oid, {}, 'ยกเลิกชำระบางส่วน', True),
                        lambda _: self.open_checkout(oid, True),
                    )
                return

            d = QDialog(self)
            d.setWindowTitle('เลือกอาหารที่จะคืน')
            d.setMinimumSize(1040, 580)
            fit_dialog(d, 1180, 760)
            b = QVBoxLayout(d)
            b.addWidget(lab('คืนค่าอาหาร • '+oid[:8], 'title'))
            b.addWidget(lab('เลือกรายการและจำนวนที่จะคืน พร้อมระบุเหตุผล', 'instruction'))
            body = QWidget()
            row = QHBoxLayout(body)
            left, lb = panel()
            lb.addWidget(lab('รายการสั่งซื้อเดิม', 'title'))
            foods = table(['เลือก', 'อาหาร', 'ราคา', 'ซื้อ', 'คืนแล้ว', 'จำนวนคืน', 'หมายเหตุ'])
            foods.setObjectName('refundItems')
            foods.setMinimumHeight(220)
            fill(foods, [
                ('', i['name'], baht(i['price']), i['qty'], i['returned'], '', i.get('note') or '—')
                for i in o['items']
            ])
            for col, width in ((0, 50), (2, 90), (3, 48), (4, 65), (5, 140)):
                foods.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                foods.setColumnWidth(col, width)
            lb.addWidget(foods, 1)
            reason = QLineEdit()
            reason.setObjectName('refundReason')
            reason.setMaxLength(500)
            reason.setPlaceholderText('ระบุเหตุผลในการคืนค่าอาหาร')
            reason.setMinimumHeight(44)
            lb.addWidget(lab('เหตุผลในการคืนค่าอาหาร'))
            lb.addWidget(reason)

            right, rb = panel()
            rb.addWidget(lab('คืนเงินเข้าบัตรเดิม', 'title'))
            refund_total = lab('฿0.00', 'money')
            rb.addWidget(refund_total)
            allocation_text = lab('เลือกรายการอาหารเพื่อคำนวณยอดคืน', 'instruction')
            allocation_text.setMinimumHeight(100)
            rb.addWidget(allocation_text)
            rb.addWidget(lab('นำบัตรที่แสดงมาแตะเพื่อรับเงินคืนเข้าบัตร', 'muted'))
            rb.addStretch()
            choices = {}

            def quantities():
                return {
                    key: control.value() if check.isChecked() else 0
                    for key, (check, control) in choices.items()
                }

            def preview_refund(*_):
                selected = quantities()
                amount = sum((
                    dec(i['price'])*selected.get(line_key(i), 0) for i in o['items']
                ), Decimal(0))
                refund_total.setText(baht(amount))
                remaining, lines = amount, []
                for payment in reversed(o['payments']):
                    take = min(remaining, payment['amount']-payment['returned'])
                    if take > 0:
                        lines.append(payment['uid']+' → '+baht(take))
                        remaining -= take
                allocation_text.setText(
                    '\n'.join(lines) if lines else 'เลือกรายการอาหารเพื่อคำนวณยอดคืน'
                )
                save_button.setEnabled(amount > 0 and bool(reason.text().strip()) and remaining == 0)

            # Explicit selection prevents refunding the whole order accidentally.
            # Selected rows start at the quantity that remains refundable.
            for r, item in enumerate(o['items']):
                remaining = item['qty']-item['returned']
                check = QCheckBox()
                check.setEnabled(remaining > 0)
                check_box = QWidget()
                cb = QHBoxLayout(check_box)
                cb.setContentsMargins(0, 0, 0, 0)
                cb.addWidget(check, 0, Qt.AlignmentFlag.AlignCenter)
                control = QuantityControl(remaining, remaining)
                control.setEnabled(False)
                foods.setCellWidget(r, 0, check_box)
                foods.setCellWidget(r, 5, control)
                foods.setRowHeight(r, 56)
                choices[line_key(item)] = check, control
                check.toggled.connect(control.setEnabled)
                check.toggled.connect(preview_refund)
                control.valueChanged.connect(preview_refund)

            row.addWidget(left, 65)
            row.addWidget(right, 35)
            b.addWidget(scroll_content(body, 390), 1)

            def save():
                selected = quantities()
                amount = sum((
                    dec(i['price'])*selected.get(line_key(i), 0) for i in o['items']
                ), Decimal(0))
                if amount <= 0 or not reason.text().strip():
                    self.message('เลือกอาหารที่จะคืนและระบุเหตุผล')
                    return
                if not self.ask(
                    'ยืนยันคืนค่าอาหาร',
                    'ยอดคืน '+baht(amount)+'\n'+allocation_text.text()
                    +'\nคืนเข้าบัตรเดิมตามยอดที่แสดง ใช่หรือไม่?',
                ):
                    return
                text = reason.text().strip()
                d.accept()
                self.run(lambda: self.db.plan(oid, selected, text),
                         lambda _: self.open_checkout(oid, True))

            actions = QHBoxLayout()
            actions.addWidget(button('ยกเลิก', d.reject))
            save_button = button('ตรวจสอบยอดคืน', save, True)
            save_button.setEnabled(False)
            actions.addWidget(save_button)
            b.addLayout(actions)
            reason.textChanged.connect(preview_refund)
            d.exec()

        self.run(lambda: self.db.order(oid), done)

    # ---------- Queue board and customer queue display ----------

    def live_queue_orders(self):
        return sorted((o for o in self.queue_order_rows if o['queue_no']
                       and o['queue_day'] and o['state'] == 'PAID'
                       and o['queue_state'] in ('WAITING', 'PREPARING', 'READY')
                       and any(i['qty'] > i['returned'] for i in o['items'])),
                      key=lambda o: (o['queue_day'], o['queue_no']))

    @staticmethod
    def queue_caption(o):
        number = f"Q{o['queue_no']:03}"
        day = o['queue_day']
        return f"{number} ({day:%d/%m})" if day != date.today() else number

    def render_queue(self, *_):
        rows = self.live_queue_orders()
        for state, box in self.queue_boxes.items():
            orders = [o for o in rows if o['queue_state'] == state]
            # Avoid rebuilding cards when a poll has not changed their contents.
            if getattr(box, 'rendered_orders', None) == orders:
                continue
            box.rendered_orders = orders
            while box.count():
                child = box.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            for o in orders:
                card, cb = panel()
                cb.setSpacing(6)
                card.setObjectName({'WAITING': 'queueCardWaiting', 'PREPARING': 'queueCardPreparing', 'READY': 'queueCardReady'}[state])
                cb.addWidget(lab(self.queue_caption(o), 'money'))
                cb.addWidget(lab(str(o['created'])[11:19], 'muted'))
                items = [i for i in o['items'] if i['qty'] > i['returned']]
                food = lab('\n'.join(f"{n}. {i['name']} × {i['qty']-i['returned']}"
                                     +(' • '+i['note'] if i.get('note') else '')
                                     for n, i in enumerate(items, 1)))
                food.setTextFormat(Qt.TextFormat.PlainText)
                cb.addWidget(food)
                if o['note']:
                    note = lab('หมายเหตุ: '+o['note'])
                    note.setTextFormat(Qt.TextFormat.PlainText)
                    cb.addWidget(note)
                actions = QHBoxLayout()
                actions.addWidget(button('รายละเอียด', lambda _, oid=o['id']: self.order_detail(oid)))
                if state == 'READY':
                    actions.addWidget(button('เรียกคิวซ้ำ', lambda _, obj=o: self.call_queue(obj)))
                action = {'WAITING': 'เริ่มทำ', 'PREPARING': 'พร้อมรับ', 'READY': 'รับแล้ว'}[state]
                advance = button(action, lambda _, obj=o: self.advance_specific(obj), True)
                advance.setObjectName('success' if state == 'READY' else 'warning' if state == 'WAITING' else 'primary')
                actions.addWidget(advance)
                cb.addLayout(actions)
                box.addWidget(card)
            if not orders:
                box.addWidget(lab('ไม่มีคิวในสถานะนี้', 'muted'))

    def advance_specific(self, o):
        # Ask for confirmation at every queue transition.
        target = {
            'WAITING': 'PREPARING', 'PREPARING': 'READY', 'READY': 'COLLECTED',
        }.get(o['queue_state'])
        if not target or self.busy:
            return
        labels = {
            'PREPARING': ('ยืนยันเริ่มทำอาหาร', 'เริ่มทำอาหาร'),
            'READY': ('ยืนยันอาหารพร้อมรับ', 'อาหารพร้อมให้ลูกค้ารับแล้ว'),
            'COLLECTED': ('ยืนยันรับอาหาร', 'ลูกค้ารับอาหารแล้ว'),
        }
        title, text = labels[target]
        if self.ask(title, f"คิว {self.queue_caption(o)} • {text} ใช่หรือไม่?"):
            self.run(
                lambda: self.db.queue(o['id'], o['queue_state'], target),
                lambda _: self.refresh_all(),
            )

    def call_queue(self, o):
        QApplication.beep()
        self.message(f"เรียกคิว {self.queue_caption(o)} • {STALL} • แจ้งเตือนแล้ว")

    def show_public(self):
        if self.public:
            self.public.raise_()
            return
        d = QDialog(self)
        d.setWindowTitle(STALL+' • คิวอาหาร')
        d.resize(1200, 760)
        b = QVBoxLayout(d)
        header = QHBoxLayout()
        title = lab(self.saved_shop_name+' • '+STALL, 'title')
        title.setStyleSheet('font-size:36px;font-weight:bold;')
        self.public_clock = lab('', 'title')
        self.public_clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(title, 1)
        header.addWidget(self.public_clock)
        b.addLayout(header)
        columns = QHBoxLayout()
        self.public_labels = {}
        for state, title, color, bg in (
            ('READY', 'พร้อมรับ', '#087a38', '#e5f8eb'),
            ('PREPARING', 'กำลังเตรียม', '#164ca1', '#eaf3ff'),
            ('WAITING', 'รอทำ', '#a85b00', '#fff4d6'),
        ):
            frame, box = panel()
            frame.setStyleSheet(
                f'QFrame#panel{{background:{bg};border:2px solid {color};border-radius:14px;}}'
            )
            heading = lab(title, 'title')
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet(f'font-size:32px;font-weight:bold;color:{color};')
            value = lab('—')
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setStyleSheet(f'font-size:58px;font-weight:bold;color:{color};')
            box.addWidget(heading)
            box.addWidget(value, 1)
            self.public_labels[state] = value
            columns.addWidget(frame, 1)
        b.addLayout(columns, 1)
        public_notice = lab('', 'noticeSuccess')
        banner(public_notice, 'success', 'กรุณารับอาหารเมื่อหมายเลขคิวแสดงในช่องพร้อมรับ')
        public_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b.addWidget(public_notice)
        self.public = d
        self.update_public()
        d.finished.connect(lambda _: setattr(self, 'public', None))
        d.show()

    def update_public(self):
        rows = self.live_queue_orders()
        for state, label in self.public_labels.items():
            label.setText('\n'.join(self.queue_caption(o) for o in rows if o['queue_state'] == state) or '—')
        self.public_clock.setText(datetime.now().strftime('%H:%M'))

    # ---------- Menu images, products and categories ----------

    def selected_menu(self):
        r = self.menu_table.currentRow()
        return self.menu_rows[r] if r >= 0 else None

    def edit_menu(self, p=None):
        if self.busy or not self.ready:
            return
        d = QDialog(self)
        d.setWindowTitle('แก้ไขเมนู' if p else 'เพิ่มเมนู')
        d.resize(650, 620)
        b = QVBoxLayout(d)
        b.addWidget(lab(d.windowTitle(), 'title'))
        form = QFormLayout()
        name = QLineEdit(p['product_name'] if p else '')
        name.setMaxLength(100)
        price = QDoubleSpinBox()
        price.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        price.setDecimals(2)
        price.setRange(.01, float(MAX))
        price.setValue(float(p['price']) if p else 50)
        category = QComboBox()
        category.setEditable(True)
        category.addItems(self.categories)
        category.setCurrentText(p['category'] if p else '')
        description = QLineEdit(p['description'] if p else '')
        description.setMaxLength(500)
        available = QCheckBox('เปิดขายเมนูนี้')
        available.setChecked(bool(p['is_available']) if p else True)
        for title, w in (
            ('ชื่ออาหาร', name), ('ราคา (บาท)', price), ('หมวดหมู่', category),
            ('รายละเอียด', description), ('สถานะเมนู', available),
        ):
            form.addRow(title, w)
        b.addLayout(form)
        image = [bytes(p['image_data']) if p and p.get('image_data') else None]
        changed = [False]
        preview = picture(image[0], 240, 150)
        b.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)

        def update(data):
            image[0], changed[0] = data, True
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data):
                preview.setText('')
                preview.setPixmap(pixmap.scaled(
                    240, 150, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            else:
                preview.clear()
                preview.setText('ยังไม่มีรูปอาหาร')

        def choose():
            try:
                data = choose_image(d)
                if data is not IMAGE_UNCHANGED:
                    update(data)
            except Exception as exc:
                QMessageBox.information(d, 'เลือกรูป', str(exc))

        row = QHBoxLayout()
        row.addWidget(button('เลือกรูปอาหาร', choose))
        row.addWidget(button('นำรูปออก', lambda: update(None)))
        b.addLayout(row)

        def save():
            if self.busy:
                QMessageBox.information(d, 'กรุณารอสักครู่', 'รอให้งานปัจจุบันเสร็จก่อนบันทึกเมนู')
                return
            if not name.text().strip() or not category.currentText().strip():
                QMessageBox.information(d, 'ตรวจสอบข้อมูล', 'กรอกชื่ออาหารและหมวดหมู่')
                return
            data = (
                p['product_id'] if p else None, name.text(), category.currentText(),
                price.value(), available.isChecked(), description.text(),
                image[0] if changed[0] or not p else IMAGE_UNCHANGED,
            )
            save_button.setEnabled(False)

            def done(_):
                d.accept()
                banner(self.notice, 'success', 'บันทึกเมนูแล้ว')
                self.refresh_all()

            def failed(message):
                save_button.setEnabled(True)
                QMessageBox.information(d, 'บันทึกไม่สำเร็จ', message)

            self.run(lambda: self.db.menu_save(*data), done, failed)

        save_button = button('บันทึกเมนู', save, True)
        b.addWidget(save_button)
        b.addWidget(button('ยกเลิก', d.reject))
        d.exec()

    def toggle_menu(self):
        p = self.selected_menu()
        if p and not self.busy:
            self.run(
                lambda: self.db.menu_save(
                    p['product_id'], p['product_name'], p['category'], p['price'],
                    not p['is_available'], p['description'],
                ),
                lambda _: self.refresh_all(),
            )

    def delete_menu(self):
        p = self.selected_menu()
        if p and not self.busy and self.ask(
            'ลบเมนู', p['product_name']+'\nซ่อนจากหน้าขาย แต่คงข้อมูลและประวัติเดิมไว้',
        ):
            self.run(lambda: self.db.menu_delete(p['product_id']), lambda _: self.refresh_all())

    def manage_categories(self):
        if self.busy:
            return
        options = ['เพิ่มหมวด', 'เปลี่ยนชื่อหมวด', 'ลบหมวด']
        action, ok = QInputDialog.getItem(self, 'จัดการหมวด', 'การทำงาน', options, 0, False)
        if not ok:
            return
        old = None
        if action != 'เพิ่มหมวด':
            if not self.categories:
                return
            old, ok = QInputDialog.getItem(self, 'หมวดเดิม', 'เลือกหมวด', self.categories, 0, False)
            if not ok:
                return
        new = None
        if action != 'ลบหมวด':
            new, ok = QInputDialog.getText(self, 'ชื่อหมวด', 'ชื่อใหม่')
            new = new.strip()[:100]
            if not ok or not new:
                return
        if self.ask('ยืนยันจัดการหมวด', action+'\n'+str(old or '')+' → '+str(new or 'ลบ')):
            self.run(
                lambda: self.db.category(old, new), lambda _: self.refresh_all(),
                lambda message: self.message('จัดการหมวดไม่สำเร็จ\n'+message),
            )

    def closeEvent(self, event):
        if self.busy or any(job.isRunning() for job in self.jobs):
            self.message('รอให้คำขอทำงานเสร็จก่อนปิดโปรแกรม')
            event.ignore()
            return
        self.timer.stop()
        self.poll.stop()
        self.worker.stop()
        event.accept()


if __name__ == '__main__':
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = StallPOSApp()
    window.showMaximized()
    sys.exit(app.exec())
