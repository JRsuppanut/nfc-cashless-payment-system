"""Blue Stall POS — replace nfc-desktop/stall_pos_app.py with this entire file.

Requires the project's PostgreSQL database.py, nfc_worker.py and token_security.py.
This development version does not require an administrator PIN.
Wallet/ledger data stay shared. New split-order, refund and queue tables use the
stall_ui_ prefix; web order reports must explicitly support these tables.
"""
import os
import sys
import json
import uuid
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager

import database
from psycopg2.extras import RealDictCursor, Json
from nfc_worker import NFCWorker, DEFAULT_PORT
from token_security import TokenSecurity
from PyQt6.QtCore import Qt, QObject, QThread, QTimer, QLocale, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextDocument
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QFrame, QLabel,
    QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout,
    QStackedWidget, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QInputDialog, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QFormLayout, QPlainTextEdit, QTabWidget,
    QSizePolicy,
)

STALL = os.getenv('STALL_ID', 'STALL-01')
MAX = Decimal('99999999.99')
STYLE = '''
QWidget {font-family:Tahoma; font-size:15px; color:#12294a;}
QMainWindow, QDialog {background:#f5f8fe;}
QFrame#panel {background:white; border:1px solid #d5e2f6; border-radius:12px;}
QLabel#title {font-size:24px; font-weight:bold;}
QLabel#money {font-size:36px; font-weight:bold; color:#215be8;}
QLabel#muted {color:#728298; font-size:13px;}
QLabel#notice, QLabel#noticeInfo {background:#eaf3ff; color:#164ca1; border:1px solid #b9d3ff;
 border-left:7px solid #2563eb; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;}
QLabel#noticeWarning {background:#fff4d6; color:#a85b00; border:1px solid #f3cd72;
 border-left:7px solid #f59e0b; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;}
QLabel#noticeSuccess {background:#e5f8eb; color:#087a38; border:1px solid #a9dfb9;
 border-left:7px solid #16a34a; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;}
QLabel#noticeError {background:#ffebeb; color:#bd2020; border:1px solid #f1b0b0;
 border-left:7px solid #dc2626; border-radius:9px; padding:15px 18px;
 font-size:20px; font-weight:bold; min-height:28px;}
QLabel#instruction {background:#edf5ff; color:#164ca1; border-radius:7px;
 padding:10px 12px; font-size:18px; font-weight:bold;}
QPushButton {background:white; border:1px solid #bbcff0; border-radius:8px;
 padding:9px 13px; font-weight:bold;}
QPushButton:hover {background:#eef5ff;}
QPushButton#primary, QPushButton:checked {background:#2563eb; color:white; border-color:#2563eb;}
QPushButton#danger {color:#be3030; border-color:#edb4b4;}
QPushButton#success {background:#16a34a;color:white;border-color:#16a34a;}
QPushButton#warning {background:#f59e0b;color:white;border-color:#f59e0b;}
QPushButton:disabled {background:#e4ebf5; color:#93a3ba; border-color:#e4ebf5;}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {background:white;
 border:1px solid #bbcff0; border-radius:7px; padding:7px;}
QTableWidget {background:white; alternate-background-color:#f5f9ff;
 border:1px solid #d5e2f6; gridline-color:#edf2fb; selection-background-color:#dfebff;
 selection-color:#12294a;}
QHeaderView::section {background:#edf4fc; padding:9px; border:0; font-weight:bold;}
QScrollArea {border:0; background:transparent;}
QScrollArea > QWidget > QWidget {background:transparent;}
QPushButton#quantity {padding:0; font-size:20px; border-radius:6px;}
QPushButton#category {padding:8px 12px; min-height:22px;}
QLabel#quantityNumber {font-size:17px; font-weight:bold;}
QLabel#statusReady {background:#e5f8eb;color:#087a38;border:1px solid #a9dfb9;
 border-radius:12px;padding:7px 12px;font-weight:bold;font-size:13px;}
QLabel#statusWarning {background:#fff4d6;color:#a85b00;border:1px solid #f3cd72;
 border-radius:12px;padding:7px 12px;font-weight:bold;font-size:13px;}
QLabel#statusError {background:#ffebeb;color:#bd2020;border:1px solid #f1b0b0;
 border-radius:12px;padding:7px 12px;font-weight:bold;font-size:13px;}
QFrame#queueWaiting {background:#fffaf0;border:1px solid #f3cd72;border-radius:12px;}
QFrame#queuePreparing {background:#f3f8ff;border:1px solid #b9d3ff;border-radius:12px;}
QFrame#queueReady {background:#effbf3;border:1px solid #a9dfb9;border-radius:12px;}
QFrame#queueCardWaiting {background:#fffaf0;border:1px solid #f0c45c;border-radius:10px;}
QFrame#queueCardPreparing {background:#f6f9ff;border:1px solid #a7c7ff;border-radius:10px;}
QFrame#queueCardReady {background:#f3fff6;border:1px solid #8dd7a4;border-radius:10px;}
'''


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
            t.setItem(r, c, QTableWidgetItem(str(value)))


def banner(widget, kind, text):
    names = {'info':'noticeInfo','warning':'noticeWarning','success':'noticeSuccess','error':'noticeError'}
    widget.setObjectName(names.get(kind,'noticeInfo'))
    widget.setText(('● ' if not str(text).lstrip().startswith('●') else '')+str(text))
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def pill(widget, kind, text):
    names = {'ready':'statusReady','warning':'statusWarning','error':'statusError'}
    widget.setObjectName(names.get(kind,'statusWarning'))
    widget.setText(text)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class BusinessError(Exception):
    pass


class Store:
    @contextmanager
    def tx(self):
        conn = database.get_connection()
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
        with self.tx() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS stall_ui_menu (
                product_id INTEGER PRIMARY KEY REFERENCES products(product_id),
                description TEXT NOT NULL DEFAULT '', deleted BOOLEAN NOT NULL DEFAULT FALSE)''')
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
            # Copy historical orders without rewriting the original tables.
            c.execute('''SELECT o.*,jsonb_agg(jsonb_build_object(
                'pid','legacy-item:'||i.order_item_id::text,'name',i.product_name,'qty',i.quantity,
                'price',i.unit_price::text,'returned',0,'note',i.item_note)) AS items
                FROM orders o JOIN order_items i USING(order_id)
                WHERE o.stall_id=%s AND o.payment_status='PAID'
                GROUP BY o.order_id''', (STALL,))
            legacy = list(c.fetchall())
            for old in legacy:
                oid = 'legacy:'+str(old['order_id'])
                c.execute('''INSERT INTO stall_ui_orders(id,stall_id,items,total,paid,state,created)
                    VALUES(%s,%s,%s,%s,%s,'PAID',%s) ON CONFLICT DO NOTHING RETURNING id''',
                    (oid,STALL,Json(old['items']),old['total_amount'],old['total_amount'],old['created_at']))
                if c.fetchone():
                    c.execute('''INSERT INTO stall_ui_payments(order_id,token,uid,amount,balance,created)
                        VALUES(%s,%s,%s,%s,%s,%s)''', (oid,old['token_uuid'],old['card_uid'],old['total_amount'],old['balance_after'],old['created_at']))
                    c.execute('''INSERT INTO stall_ui_events(order_id,uid,kind,amount,balance,created)
                        VALUES(%s,%s,'PAY',%s,%s,%s)''', (oid,old['card_uid'],old['total_amount'],old['balance_after'],old['created_at']))
                else:
                    c.execute('SELECT items FROM stall_ui_orders WHERE id=%s FOR UPDATE',(oid,))
                    items = c.fetchone()['items']
                    notes = {i['pid']:i.get('note') or '' for i in old['items']}
                    changed = False
                    for item in items:
                        if 'note' not in item:
                            item['note'] = notes.get(item['pid'],'')
                            changed = True
                    if changed:
                        c.execute('UPDATE stall_ui_orders SET items=%s WHERE id=%s',(Json(items),oid))
            c.execute('SELECT stall_name FROM stalls WHERE stall_id=%s AND is_active=1', (STALL,))
            if not c.fetchone():
                raise BusinessError('ไม่พบร้านที่เปิดใช้งาน ตรวจสอบ STALL_ID')

    def products(self, all_items=False):
        with self.tx() as c:
            c.execute('''SELECT p.*, COALESCE(m.description,'') AS description
                FROM products p LEFT JOIN stall_ui_menu m USING(product_id)
                WHERE p.stall_id=%s AND NOT COALESCE(m.deleted,FALSE)
                AND (%s OR p.is_available=1) ORDER BY p.product_id''', (STALL, all_items))
            return [dict(x) for x in c.fetchall()]

    def categories(self):
        with self.tx() as c:
            c.execute('SELECT name FROM stall_ui_categories WHERE stall_id=%s ORDER BY name', (STALL,))
            return [r['name'] for r in c.fetchall()]

    def menu_save(self, pid, name, category, price, available, description):
        clean_name = name.strip()
        clean_category = category.strip()
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
                VALUES(%s,%s) ON CONFLICT(stall_id,name) DO NOTHING''',
                (STALL, clean_category))
            if pid:
                c.execute('''UPDATE products SET product_name=%s,category=%s,price=%s,
                    is_available=%s,updated_at=CURRENT_TIMESTAMP WHERE product_id=%s AND stall_id=%s
                    RETURNING product_id''', (clean_name,clean_category,dec(price),int(available),pid,STALL))
            elif existing:
                # เมนูที่เคยลบยังคงอยู่เพื่อรักษาประวัติ จึงนำแถวเดิมกลับมาใช้
                c.execute('''UPDATE products SET product_name=%s,category=%s,price=%s,
                    is_available=%s,updated_at=CURRENT_TIMESTAMP
                    WHERE product_id=%s AND stall_id=%s RETURNING product_id''',
                    (clean_name,clean_category,dec(price),int(available),existing['product_id'],STALL))
            else:
                c.execute('''INSERT INTO products(stall_id,product_name,category,price,is_available,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP) RETURNING product_id''',
                    (STALL,clean_name,clean_category,dec(price),int(available)))
            row = c.fetchone()
            if not row:
                raise BusinessError('ไม่พบเมนูของร้านนี้')
            c.execute('''INSERT INTO stall_ui_menu(product_id,description,deleted)
                VALUES(%s,%s,FALSE)
                ON CONFLICT(product_id) DO UPDATE SET description=EXCLUDED.description,deleted=FALSE''',
                (row['product_id'],description))

    def menu_delete(self, pid):
        with self.tx() as c:
            c.execute('UPDATE products SET is_available=0,updated_at=CURRENT_TIMESTAMP WHERE product_id=%s AND stall_id=%s RETURNING product_id', (pid,STALL))
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
                    WHERE stall_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1''',
                    (STALL,new))
                existing = c.fetchone()
                if existing:
                    if not old:
                        raise BusinessError('มีหมวด “'+existing['name']+'” อยู่แล้ว ไม่ต้องเพิ่มซ้ำ')
                    if existing['name'] != old:
                        raise BusinessError('มีหมวด “'+existing['name']+'” อยู่แล้ว กรุณาใช้ชื่ออื่น')
                    return
                c.execute('''INSERT INTO stall_ui_categories(stall_id,name)
                    VALUES(%s,%s)''', (STALL,new))
                if old:
                    c.execute('UPDATE products SET category=%s,updated_at=CURRENT_TIMESTAMP WHERE stall_id=%s AND category=%s', (new,STALL,old))
            else:
                c.execute('SELECT 1 FROM products WHERE stall_id=%s AND category=%s LIMIT 1', (STALL,old))
                if c.fetchone():
                    raise BusinessError('หมวดนี้ยังมีเมนู รวมเมนูที่ปิดขาย ต้องย้ายหมวดก่อน')
            if old:
                c.execute('DELETE FROM stall_ui_categories WHERE stall_id=%s AND name=%s', (STALL,old))

    def create(self, oid, cart, note, item_notes=None):
        with self.tx() as c:
            c.execute('SELECT id FROM stall_ui_orders WHERE id=%s AND stall_id=%s', (oid,STALL))
            if c.fetchone():
                return oid
            items = []
            for pid, qty in cart.items():
                if not isinstance(qty,int) or not 1 <= qty <= 999:
                    raise BusinessError('จำนวนอาหารไม่ถูกต้อง')
                c.execute('''SELECT p.* FROM products p LEFT JOIN stall_ui_menu m USING(product_id)
                    WHERE p.product_id=%s AND p.stall_id=%s AND p.is_available=1
                    AND NOT COALESCE(m.deleted,FALSE) FOR SHARE OF p''', (pid,STALL))
                p = c.fetchone()
                if not p:
                    raise BusinessError('เมนูบางรายการปิดขายแล้ว ตรวจสอบตะกร้าใหม่')
                items.append(dict(pid=pid,name=p['product_name'],qty=qty,price=str(p['price']),returned=0,note=str((item_notes or {}).get(pid,''))[:250]))
            total = dec(sum((dec(i['price'])*i['qty'] for i in items), Decimal(0)))
            if not items or total <= 0:
                raise BusinessError('ไม่มีอาหารในออเดอร์')
            c.execute('INSERT INTO stall_ui_orders(id,stall_id,items,note,total) VALUES(%s,%s,%s,%s,%s)', (oid,STALL,Json(items),note,total))
            return oid

    def order(self, oid):
        with self.tx() as c:
            c.execute('SELECT o.*,s.stall_name FROM stall_ui_orders o JOIN stalls s USING(stall_id) WHERE o.id=%s AND o.stall_id=%s', (oid,STALL))
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
                    AND (queue_state IN ('WAITING','PREPARING','READY')
                    OR (queue_state='COLLECTED' AND queue_day=CURRENT_DATE))
                    ORDER BY queue_day,queue_no''', (STALL,))
                return [dict(x) for x in c.fetchall()]
            c.execute('''SELECT * FROM stall_ui_orders WHERE stall_id=%s
                AND state IN ('OPEN','PARTIAL','REFUND_PENDING')
                UNION SELECT * FROM (SELECT * FROM stall_ui_orders WHERE stall_id=%s
                ORDER BY created DESC LIMIT 300) recent ORDER BY created DESC''', (STALL,STALL))
            return [dict(x) for x in c.fetchall()]

    def stall_name(self):
        with self.tx() as c:
            c.execute('SELECT stall_name FROM stalls WHERE stall_id=%s',(STALL,))
            row = c.fetchone()
            return row['stall_name'] if row else STALL

    def rename_stall(self,name):
        if not name.strip():
            raise BusinessError('กรอกชื่อร้าน')
        with self.tx() as c:
            # Some existing installations have the original stalls table
            # without updated_at.  Renaming needs only the stall_name column.
            c.execute(
                'UPDATE stalls SET stall_name=%s WHERE stall_id=%s',
                (name.strip()[:100], STALL),
            )
            if c.rowcount != 1:
                raise BusinessError('ไม่พบร้าน '+STALL+' ในฐานข้อมูล')

    def wallet(self, token, uid):
        with self.tx() as c:
            c.execute('SELECT * FROM wallets WHERE token_uuid=%s AND card_uid=%s', (token,uid))
            r = c.fetchone()
            if not r:
                raise BusinessError('ไม่พบกระเป๋าเงินของบัตรนี้')
            return dict(r)

    def intent(self, op, request):
        with self.tx() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('operation:'+STALL,))
            c.execute("SELECT id FROM stall_ui_operations WHERE stall_id=%s AND state='PENDING' AND id<>%s LIMIT 1", (STALL,op))
            if c.fetchone():
                raise BusinessError('มีคำขอเดิมรอตรวจผล ต้องตรวจคำขอนั้นก่อน')
            c.execute('INSERT INTO stall_ui_operations(id,stall_id,request) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (op,STALL,Json(request)))
            c.execute('SELECT request,stall_id FROM stall_ui_operations WHERE id=%s', (op,))
            r = c.fetchone()
            if r['request'] != request or r['stall_id'] != STALL:
                raise BusinessError('ข้อมูลรายการตรวจสอบไม่ตรงกัน')

    def pending(self):
        with self.tx() as c:
            c.execute("SELECT * FROM stall_ui_operations WHERE stall_id=%s AND state='PENDING' ORDER BY created", (STALL,))
            return [dict(x) for x in c.fetchall()]

    def execute(self, op):
        with self.tx() as c:
            c.execute('SELECT * FROM stall_ui_operations WHERE id=%s AND stall_id=%s FOR UPDATE', (op,STALL))
            operation = c.fetchone()
            if not operation:
                raise BusinessError('ไม่พบเลขอ้างอิงการทำรายการ')
            if operation['state'] == 'DONE':
                return operation['result']
            if operation['state'] != 'PENDING':
                raise BusinessError('คำขอนี้ถูกยุติแล้ว ไม่ดำเนินรายการซ้ำ')
            req = operation['request']
            c.execute('SELECT * FROM stall_ui_orders WHERE id=%s AND stall_id=%s FOR UPDATE', (req['order'],STALL))
            o = c.fetchone()
            if not o:
                raise BusinessError('ไม่พบออเดอร์')
            # All financial writes and the operation result commit together.
            c.execute('SELECT * FROM wallets WHERE token_uuid=%s FOR UPDATE', (req['token'],))
            w = c.fetchone()
            if not w or w['card_uid'] != req['uid'] or w['status'] != 'ACTIVE':
                raise BusinessError('บัตรไม่พร้อมใช้งาน หรือรอบการออกบัตรเปลี่ยนแล้ว')
            amount = dec(req['amount'])
            if amount <= 0:
                raise BusinessError('ยอดต้องมากกว่า 0')
            if req['kind'] == 'PAY':
                if o['state'] not in ('OPEN','PARTIAL') or amount > o['total']-o['paid']:
                    raise BusinessError('ออเดอร์นี้ไม่อยู่ในสถานะที่ชำระยอดนี้ได้')
                if w['balance'] < amount:
                    raise BusinessError('ยอดเงินไม่พอ ไม่ได้ทำรายการนี้')
                balance = w['balance']-amount
                paid = o['paid']+amount
                c.execute('INSERT INTO stall_ui_payments(order_id,token,uid,amount,balance) VALUES(%s,%s,%s,%s,%s)', (o['id'],req['token'],req['uid'],amount,balance))
                c.execute('UPDATE stall_ui_orders SET paid=%s,state=%s WHERE id=%s', (paid,'PAID' if paid==o['total'] else 'PARTIAL',o['id']))
                if paid == o['total']:
                    # Serialize daily numbering across all terminals of this stall.
                    c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('queue:'+STALL,))
                    c.execute('SELECT COALESCE(MAX(queue_no),0)+1 AS n FROM stall_ui_orders WHERE stall_id=%s AND queue_day=CURRENT_DATE', (STALL,))
                    n = c.fetchone()['n']
                    c.execute("UPDATE stall_ui_orders SET queue_no=%s,queue_day=CURRENT_DATE,queue_state='WAITING' WHERE id=%s", (n,o['id']))
                kind = 'PAY'
            elif req['kind'] == 'REFUND':
                if o['state'] != 'REFUND_PENDING':
                    raise BusinessError('ออเดอร์นี้ไม่มีแผนคืนที่รอดำเนินการ')
                c.execute('''SELECT p.*,r.order_id FROM stall_ui_refund_parts p JOIN stall_ui_refunds r ON r.id=p.refund_id
                    WHERE p.id=%s FOR UPDATE OF p,r''', (req['part'],))
                p = c.fetchone()
                if not p or p['order_id'] != o['id'] or p['token'] != req['token'] or p['uid'] != req['uid'] or p['amount'] != amount or p['done']:
                    raise BusinessError('แผนคืนไม่ตรง หรือคืนรายการนี้แล้ว')
                balance = dec(w['balance']+amount)
                c.execute('UPDATE stall_ui_payments SET returned=returned+%s WHERE id=%s AND returned+%s<=amount RETURNING id', (amount,p['payment_id'],amount))
                if not c.fetchone():
                    raise BusinessError('ยอดคืนเกินยอดที่บัตรนี้จ่าย')
                c.execute('UPDATE stall_ui_refund_parts SET done=TRUE WHERE id=%s', (p['id'],))
                c.execute('UPDATE stall_ui_orders SET returned=returned+%s WHERE id=%s', (amount,o['id']))
                c.execute('SELECT 1 FROM stall_ui_refund_parts WHERE refund_id=%s AND NOT done', (p['refund_id'],))
                if not c.fetchone():
                    c.execute('UPDATE stall_ui_refunds SET done=TRUE WHERE id=%s RETURNING items', (p['refund_id'],))
                    quantities = c.fetchone()['items']
                    items = o['items']
                    for i in items:
                        i['returned'] += int(quantities.get(str(i['pid']),0))
                    full = o['returned']+amount == o['paid']
                    cancelled = full and (o['paid'] < o['total'] or all(i['returned']==i['qty'] for i in items))
                    c.execute('UPDATE stall_ui_orders SET items=%s,state=%s,queue_state=CASE WHEN %s THEN %s ELSE queue_state END WHERE id=%s',
                        (Json(items),'CANCELLED' if cancelled else 'PAID',cancelled,'CANCELLED',o['id']))
                kind = 'REFUND_MEAL'
            else:
                raise BusinessError('ประเภทการทำรายการไม่ถูกต้อง')
            c.execute('UPDATE wallets SET balance=%s,updated_at=CURRENT_TIMESTAMP WHERE token_uuid=%s', (balance,req['token']))
            c.execute('''INSERT INTO transaction_ledger(token_uuid,card_uid,terminal_type,action_type,amount,balance_after,timestamp)
                VALUES(%s,%s,'STALL_POS',%s,%s,%s,CURRENT_TIMESTAMP)''', (req['token'],req['uid'],kind,amount,balance))
            c.execute('INSERT INTO stall_ui_events(order_id,uid,kind,amount,balance) VALUES(%s,%s,%s,%s,%s)', (o['id'],req['uid'],kind,amount,balance))
            result = dict(kind=kind,amount=str(amount),balance=str(balance),order=o['id'])
            c.execute("UPDATE stall_ui_operations SET state='DONE',result=%s WHERE id=%s", (Json(result),op))
            return result

    def reject(self, op):
        # Obtain the operation lock: an in-flight transaction finishes first.
        with self.tx() as c:
            c.execute('SELECT state,result FROM stall_ui_operations WHERE id=%s AND stall_id=%s FOR UPDATE', (op,STALL))
            r = c.fetchone()
            if r and r['state']=='DONE':
                return r['result']
            c.execute("UPDATE stall_ui_operations SET state='CANCELLED' WHERE id=%s AND state='PENDING'", (op,))
            return None

    def plan(self, oid, quantities, reason, cancel_partial=False):
        with self.tx() as c:
            c.execute('SELECT * FROM stall_ui_orders WHERE id=%s AND stall_id=%s FOR UPDATE', (oid,STALL))
            o = c.fetchone()
            if not o or o['state'] not in ('PAID','PARTIAL'):
                raise BusinessError('ออเดอร์นี้ไม่พร้อมสร้างแผนคืน')
            if cancel_partial:
                if o['state'] != 'PARTIAL':
                    raise BusinessError('ไม่ใช่ออเดอร์ที่ชำระบางส่วน')
                amount = o['paid']-o['returned']
                quantities = {str(i['pid']):i['qty']-i['returned'] for i in o['items']}
            else:
                amount = Decimal(0)
                valid_ids = {str(i['pid']) for i in o['items']}
                if set(quantities)-valid_ids:
                    raise BusinessError('รายการอาหารไม่ตรงกับออเดอร์')
                for i in o['items']:
                    q = quantities.get(str(i['pid']),0)
                    if not isinstance(q,int) or q<0 or q>i['qty']-i['returned']:
                        raise BusinessError('จำนวนคืนไม่ถูกต้อง')
                    amount += dec(i['price'])*q
            if amount <= 0 or amount > o['paid']-o['returned'] or not reason.strip():
                raise BusinessError('เลือกอาหารที่จะคืนและระบุเหตุผล')
            rid = str(uuid.uuid4())
            c.execute('INSERT INTO stall_ui_refunds(id,order_id,items,reason,amount) VALUES(%s,%s,%s,%s,%s)', (rid,oid,Json(quantities),reason,amount))
            c.execute('SELECT * FROM stall_ui_payments WHERE order_id=%s ORDER BY id DESC FOR UPDATE', (oid,))
            left = amount
            for p in c.fetchall():
                take = min(left,p['amount']-p['returned'])
                if take > 0:
                    c.execute('INSERT INTO stall_ui_refund_parts(refund_id,payment_id,token,uid,amount) VALUES(%s,%s,%s,%s,%s)', (rid,p['id'],p['token'],p['uid'],take))
                    left -= take
            if left:
                raise BusinessError('ยอดชำระเดิมไม่ตรง ตรวจสอบก่อนคืน')
            c.execute("UPDATE stall_ui_orders SET state='REFUND_PENDING' WHERE id=%s", (oid,))
            return rid

    def queue(self, oid, expected, target):
        transitions = {'WAITING':'PREPARING','PREPARING':'READY','READY':'COLLECTED'}
        if transitions.get(expected) != target:
            raise BusinessError('ลำดับคิวไม่ถูกต้อง')
        with self.tx() as c:
            c.execute('UPDATE stall_ui_orders SET queue_state=%s WHERE id=%s AND stall_id=%s AND queue_state=%s AND state=%s RETURNING id', (target,oid,STALL,expected,'PAID'))
            if not c.fetchone():
                raise BusinessError('คิวเปลี่ยนแล้ว หรือมีการคืนเงินค้างอยู่ กรุณารีเฟรช')

    def history(self, uid=None):
        with self.tx() as c:
            c.execute('''SELECT e.*,o.queue_no,o.state FROM stall_ui_events e JOIN stall_ui_orders o ON o.id=e.order_id
                WHERE o.stall_id=%s AND (%s IS NULL OR e.uid=%s) ORDER BY e.id DESC LIMIT 300''', (STALL,uid,uid))
            return [dict(x) for x in c.fetchall()]


class Bridge(QObject):
    tag = pyqtSignal(str,bool,object,str)
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
        except BusinessError as e:
            self.error.emit(str(e))
        except Exception:
            self.error.emit('ติดต่อฐานข้อมูลไม่ได้ หรือข้อมูลไม่ตรง กรุณาตรวจสอบ PostgreSQL')


class ReceiptDialog(QDialog):
    def __init__(self,o,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Order Slip / Payment Receipt')
        self.setMinimumSize(980,620)
        screen = parent.screen() if parent and hasattr(parent,'screen') else QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        self.resize(min(1180,max(980,area.width()-80)) if area else 1120,
                    min(760,max(620,area.height()-90)) if area else 720)
        b = QVBoxLayout(self)
        b.setContentsMargins(18,16,18,16)
        b.setSpacing(12)
        queue = f"Q{o['queue_no']:03}" if o['queue_no'] else 'ยังไม่ออกคิว'
        title = QHBoxLayout()
        heading = lab('รายละเอียดใบสั่งซื้อ  •  '+queue,'title')
        heading.setStyleSheet('font-size:28px;font-weight:800;color:#12294d;')
        title.addWidget(heading,1)
        payment_state = lab('ชำระครบ' if o['state']=='PAID' else o['state'])
        pill(payment_state,'ready' if o['state']=='PAID' else 'warning',payment_state.text())
        food_state = lab({'WAITING':'รอทำ','PREPARING':'กำลังทำ','READY':'พร้อมรับ','COLLECTED':'รับแล้ว'}.get(o['queue_state'],o['queue_state']))
        pill(food_state,'ready' if o['queue_state'] in ('READY','COLLECTED') else 'warning',food_state.text())
        title.addWidget(payment_state)
        title.addWidget(food_state)
        b.addLayout(title)

        content = QHBoxLayout()
        content.setSpacing(14)
        detail_box,left = panel()
        left.addWidget(lab('รายการอาหาร','title'))
        foods_table = table(['#','รายการอาหาร','จำนวน','คืน','ราคา','รวม','หมายเหตุ'])
        food_rows = []
        for n,i in enumerate(o['items'],1):
            food_rows.append((n,i['name'],i['qty'],i['returned'],baht(i['price']),
                              baht(dec(i['price'])*i['qty']),i.get('note') or '—'))
        fill(foods_table,food_rows)
        foods_table.setMinimumHeight(220)
        foods_table.setStyleSheet('QTableWidget{font-size:14px;} QHeaderView::section{font-size:14px;padding:7px 4px;}')
        for col in (0,2,3,4,5):
            foods_table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.ResizeToContents)
        foods_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        foods_table.horizontalHeader().setSectionResizeMode(6,QHeaderView.ResizeMode.Stretch)
        left.addWidget(foods_table,1)
        total = lab('รวมทั้งหมด '+str(sum(i['qty'] for i in o['items']))+' รายการ     '+baht(o['total']),'money')
        total.setAlignment(Qt.AlignmentFlag.AlignRight)
        left.addWidget(total)
        left.addWidget(lab('ข้อมูลการชำระเงิน','title'))
        payments_table = table(['No.','Card ID','จำนวนที่จ่าย','จำนวนที่คืน','ยอดหลังจ่าย'])
        fill(payments_table,[(n,p['uid'],baht(p['amount']),baht(p['returned']),baht(p['balance']))
                             for n,p in enumerate(o['payments'],1)])
        payments_table.setMinimumHeight(120)
        left.addWidget(payments_table)
        snapshot = lab('')
        banner(snapshot,'info','ยอดหลังจ่ายเป็นข้อมูล ณ เวลาธุรกรรม ไม่ใช่ยอดปัจจุบัน')
        left.addWidget(snapshot)

        receipt_box,right = panel()
        right.addWidget(lab('สลิป','title'))
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet('QTabBar::tab{font-size:17px;font-weight:700;padding:10px 18px;}')
        self.documents = []
        common = [o.get('stall_name',STALL)+' ['+STALL+']',
                  'Order: '+o['id'],'Queue: '+queue,
                  'Date: '+str(o['created'])[:19],'Status: '+o['state'],'-'*40]
        foods = []
        for n,i in enumerate(o['items'],1):
            foods.append(f"{n}. {i['name']} × {i['qty']}  @ {baht(i['price'])}  = {baht(dec(i['price'])*i['qty'])}")
            if i.get('note'):
                foods.append('    หมายเหตุ: '+i['note'])
            if i['returned']:
                foods.append('    คืนแล้ว: '+str(i['returned']))
        if o['note']:
            foods.append('หมายเหตุทั้งออเดอร์: '+o['note'])
        order = ['ORDER SLIP']+common+foods+['-'*40,'ยอดอาหาร: '+baht(o['total']),
            'คืนแล้ว: '+baht(o['returned']),
            'ออเดอร์นี้ส่งเข้าคิวเมื่อชำระครบเท่านั้น']
        payment = ['PAYMENT RECEIPT']+common+foods+['-'*40,
            'ยอดอาหาร: '+baht(o['total']),'จ่ายแล้ว: '+baht(o['paid']),
            'คืนแล้ว: '+baht(o['returned']),
            'ยอดชำระสุทธิ: '+baht(o['paid']-o['returned']),
            'ยังค้างชำระ: '+baht(0 if o['state']=='CANCELLED' else o['total']-o['paid']),'-'*40]
        for n,p in enumerate(o['payments'],1):
            payment.extend([f"Payment {n} • Card ID: {p['uid']}",
                'จ่าย: '+baht(p['amount'])+' • คืนแล้ว: '+baht(p['returned']),
                'ยอดบัตรหลังจ่ายครั้งนี้: '+baht(p['balance'])])
        payment += ['-'*40,'ยอดบัตรเป็นข้อมูล ณ เวลาที่จ่าย ไม่ใช่ยอดปัจจุบัน',
                    'ไม่รวมยอดคงเหลือหลายบัตรเป็นยอดเดียว','ขอบคุณค่ะ']
        for title,lines in [('Order Slip',order),('Payment Receipt',payment)]:
            editor = QPlainTextEdit('\n'.join(lines))
            editor.setReadOnly(True)
            editor.setFont(QFont('Tahoma',12))
            editor.setStyleSheet('QPlainTextEdit{background:#ffffff;border:1px solid #bdd3fa;border-radius:10px;padding:12px;color:#12294d;}')
            self.documents.append(editor)
            self.tabs.addTab(editor,title)
        right.addWidget(self.tabs,1)
        content.addWidget(detail_box,64)
        content.addWidget(receipt_box,36)
        b.addLayout(content,1)
        row = QHBoxLayout()
        row.addWidget(button('พิมพ์สลิปที่เลือก',self.print_current,True))
        row.addWidget(button('ปิด',self.accept))
        b.addLayout(row)

    def print_current(self):
        try:
            from PyQt6.QtPrintSupport import QPrinter,QPrintDialog
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dialog = QPrintDialog(printer,self)
            if dialog.exec()==QDialog.DialogCode.Accepted:
                document = QTextDocument()
                document.setDefaultFont(QFont('Tahoma',12))
                document.setPlainText(self.documents[self.tabs.currentIndex()].toPlainText())
                document.print(printer)
        except Exception:
            QMessageBox.information(self,'พิมพ์สลิป','พิมพ์ไม่ได้ ตรวจสอบเครื่องพิมพ์และไดรเวอร์')


class Checkout(QDialog):
    def __init__(self, app, oid, refund=False):
        super().__init__(app)
        self.app, self.oid, self.refund = app, oid, refund
        self.wallet = None
        self.split = False
        self.locked = False
        self.op = None
        self.request = None
        self.o = None
        self.part = None
        self.generation = 0
        self.receipt_shown = False
        self.setWindowTitle('คืนค่าอาหาร' if refund else 'ชำระค่าอาหาร')
        self.setMinimumSize(900,560)
        screen = app.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        self.resize(min(1040,max(900,area.width()-60)) if area else 1040,
                    min(720,max(560,area.height()-80)) if area else 680)
        b = QVBoxLayout(self)
        b.setContentsMargins(18,16,18,16)
        b.setSpacing(12)
        b.addWidget(lab(self.windowTitle(),'title'))
        content = QHBoxLayout()
        content.setSpacing(14)
        order_panel,left = panel()
        left.addWidget(lab('Current Order • รายการอาหาร','title'))
        self.order_items = table(['No.','อาหาร','จำนวน','รวม','Order Note'])
        self.order_items.setStyleSheet('QTableWidget {font-size:17px;} QHeaderView::section {font-size:15px;padding:8px;}')
        self.order_items.verticalHeader().setDefaultSectionSize(64)
        for col,width in ((0,42),(2,64),(3,100)):
            self.order_items.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Fixed)
            self.order_items.setColumnWidth(col,width)
        left.addWidget(self.order_items,1)
        self.order_note = lab('','muted')
        left.addWidget(self.order_note)
        self.summary = lab('', 'money')
        self.summary.setStyleSheet('font-size:22px;font-weight:bold;color:#215be8;')
        left.addWidget(self.summary)
        self.contribution_title = lab('บัตรที่ชำระแล้ว','muted')
        left.addWidget(self.contribution_title)
        self.contributions = table(['บัตรเดิม','ชำระ','คืนแล้ว'])
        left.addWidget(self.contributions)
        card_panel,right = panel()
        right.addWidget(lab('ตรวจสอบก่อนยืนยัน','title'))
        self.card = lab('แตะบัตรเพื่อตรวจสอบยอดเงิน','notice')
        right.addWidget(self.card)
        self.balance = lab('ยอดคงเหลือก่อนทำรายการ: —','money')
        self.balance.setStyleSheet('font-size:24px;font-weight:bold;color:#215be8;')
        right.addWidget(self.balance)
        self.amount = QDoubleSpinBox()
        self.amount.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.amount.setLocale(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
        self.amount.setDecimals(2)
        self.amount.setRange(.01,float(MAX))
        self.amount.setPrefix('จ่ายจากบัตรนี้: ฿')
        self.amount.setStyleSheet('font-size:20px;padding:10px;')
        self.amount.valueChanged.connect(self.preview)
        right.addWidget(self.amount)
        self.after = lab('ยอดหลังทำรายการ: —')
        self.after.setStyleSheet('font-size:18px;font-weight:bold;')
        right.addWidget(self.after)
        right.addStretch()
        right.addWidget(lab('การอ่านยอดยังไม่หักเงิน\nวางบัตรไว้จนยืนยันรายการสำเร็จ','muted'))
        content.addWidget(order_panel,58)
        content.addWidget(card_panel,42)
        b.addLayout(content,1)
        self.notice = lab('ยังไม่หักเงินจนกดยืนยัน','notice')
        banner(self.notice,'info','ยังไม่หักเงินจนกดยืนยัน')
        b.addWidget(self.notice)
        row = QHBoxLayout()
        self.change = button('ใช้บัตรใบอื่น',self.change_card)
        self.split_btn = button('แบ่งจ่ายหลายบัตร',self.enable_split)
        self.confirm = button('ยืนยัน',self.pay,True)
        row.addWidget(self.change)
        row.addWidget(self.split_btn)
        row.addWidget(self.confirm)
        b.addLayout(row)
        row = QHBoxLayout()
        self.pause = button('พักรายการ / ปิด',self.reject)
        self.cancel = button('ยกเลิกและคืนยอดที่จ่าย',self.cancel_paid,danger=True)
        self.check = button('ตรวจสอบผล / ดำเนินรายการเดิม',self.recover)
        self.abandon = button('ยุติคำขอที่ยังไม่สำเร็จ',self.abandon_op)
        row.addWidget(self.pause)
        row.addWidget(self.cancel)
        b.addLayout(row)
        b.addWidget(self.check)
        b.addWidget(self.abandon)
        self.check.hide()
        self.abandon.hide()
        self.confirm.setEnabled(False)
        self.refresh()

    def refresh(self):
        if not self.app.run(lambda:self.app.db.order(self.oid),self.loaded):
            QTimer.singleShot(150,self.refresh)

    def loaded(self,o):
        self.o = o
        fill(self.order_items,[(n,i['name'],i['qty']-i['returned'],baht(dec(i['price'])*(i['qty']-i['returned'])),i.get('note') or '—') for n,i in enumerate(o['items'],1)])
        self.order_items.resizeRowsToContents()
        for row in range(self.order_items.rowCount()):
            self.order_items.setRowHeight(row,max(64,self.order_items.rowHeight(row)))
            for col in range(self.order_items.columnCount()):
                item = self.order_items.item(row,col)
                item.setToolTip(item.text())
        self.order_note.setText('หมายเหตุทั้งออเดอร์: '+o['note'] if o['note'] else '')
        self.order_note.setVisible(bool(o['note']))
        fill(self.contributions,[(p['uid'],baht(p['amount']),baht(p['returned'])) for p in o['payments']])
        self.contributions.setVisible(bool(o['payments']))
        self.contribution_title.setVisible(bool(o['payments']))
        self.contributions.setFixedHeight(38+42*min(2,max(1,len(o['payments']))))
        self.split = self.split or o['paid']>0
        self.cancel.setVisible(not self.refund and o['state']=='PARTIAL')
        self.split_btn.setVisible(not self.refund and o['paid']==0)
        if self.refund:
            pending = [p for p in o['refunds'] if not p['done']]
            if not pending:
                self.part = None
                self.wallet = None
                self.remaining = Decimal(0)
                self.amount.setEnabled(False)
                banner(self.notice,'success','คืนเงินครบแล้ว นำบัตรออกได้')
                self.confirm.setEnabled(False)
                self.app.refresh_all()
                return
            self.part = pending[0]
            self.remaining = self.part['amount']
            self.summary.setText('ยังต้องคืน '+baht(sum((p['amount'] for p in pending),Decimal(0))))
            self.card.setText('แตะบัตรเดิม: '+self.part['uid'])
            self.amount.setPrefix('คืนเข้าบัตร: ฿')
        else:
            self.remaining = o['total']-o['paid']
            self.summary.setText(f"รวม {baht(o['total'])} • จ่ายแล้ว {baht(o['paid'])}\nยังต้องจ่าย {baht(self.remaining)}")
            if o['state'] not in ('OPEN','PARTIAL'):
                self.confirm.setEnabled(False)
                banner(self.notice,'success','ชำระครบแล้ว • เลขคิว '+(f"Q{o['queue_no']:03}" if o['queue_no'] else '—'))
                if o['state']=='PAID' and not self.receipt_shown:
                    self.receipt_shown = True
                    self.app.sale_wallet = None
                    self.app.render_sale_balance()
                    ReceiptDialog(o,self).exec()
                self.app.refresh_all()
                return
        self.amount.setValue(float(self.remaining))
        self.amount.setEnabled(self.split and not self.refund and not self.op)
        if self.app.current and not self.app.must_remove:
            self.on_card(self.app.current)

    def on_card(self,current):
        if self.locked or self.op or not self.o:
            return
        uid,token = current
        self.generation += 1
        gen = self.generation
        self.wallet = None
        self.confirm.setEnabled(False)
        self.card.setText('Card ID: '+uid+' • กำลังอ่านยอด')
        def done(w):
            if gen != self.generation or self.app.current != current or self.app.must_remove:
                return
            self.wallet = w
            self.card.setText('Card ID: '+uid)
            self.balance.setText('ยอดคงเหลือก่อนทำรายการ: '+baht(w['balance']))
            if self.split and not self.refund:
                self.amount.setValue(float(min(self.remaining,w['balance'])))
            self.preview()
        def failed(message):
            if gen==self.generation:
                self.app.must_remove = True
                banner(self.notice,'error',message+' • นำบัตรออกแล้วตรวจสอบใหม่')
        self.app.run(lambda:self.app.db.wallet(token,uid),done,failed)

    def removed(self):
        self.generation += 1
        self.wallet = None
        self.confirm.setEnabled(False)
        self.balance.setText('ยอดคงเหลือก่อนทำรายการ: —')
        self.after.setText('ยอดหลังทำรายการ: —')
        if not self.locked and not self.op:
            self.card.setText('แตะบัตรเพื่อตรวจสอบยอดเงิน')

    def preview(self):
        self.confirm.setEnabled(False)
        if self.locked or self.op or not self.wallet or not self.o or self.app.must_remove:
            return
        w = self.wallet
        n = dec(self.amount.value())
        valid = self.app.current == (w['card_uid'],w['token_uuid']) and w['status']=='ACTIVE' and 0<n<=self.remaining
        if self.refund:
            valid = valid and self.o['state']=='REFUND_PENDING' and self.part and not self.part['done'] and w['token_uuid']==self.part['token'] and w['card_uid']==self.part['uid'] and n==self.part['amount'] and w['balance']+n<=MAX
            self.after.setText('ยอดหลังคืน: '+baht(w['balance']+n))
            banner(self.notice,'warning','คืนเข้าบัตรที่จ่ายเดิม • วางบัตรไว้จนสำเร็จ')
        else:
            valid = valid and self.o['state'] in ('OPEN','PARTIAL') and w['balance']>=n and (self.split or n==self.remaining)
            self.after.setText('ยอดหลังชำระ: '+(baht(w['balance']-n) if w['balance']>=n else '—'))
            banner(self.notice,'warning','ยังไม่หักเงิน • วางบัตรไว้จนยืนยันสำเร็จ' if w['balance']>=n else 'เงินไม่พอ ขาดอีก '+baht(n-w['balance'])+' • ใช้บัตรใบอื่น หรือเลือกแบ่งจ่าย')
        if w['status']!='ACTIVE':
            banner(self.notice,'error','บัตรไม่พร้อมใช้งาน')
        elif self.refund and not valid:
            banner(self.notice,'error','ต้องใช้บัตรเดิมและ Token รอบเดิมตามแผนคืน')
        self.confirm.setText(('ยืนยันคืน ' if self.refund else 'ยืนยันจ่าย ')+baht(n))
        self.confirm.setEnabled(bool(valid) and self.app.reader_ready and not self.app.busy)

    def change_card(self):
        self.app.must_remove = bool(self.app.current)
        self.removed()
        banner(self.notice,'info','นำบัตรเดิมออก แล้วแตะบัตรใบใหม่ • ไม่ได้หักเงินจากการอ่านยอด')

    def enable_split(self):
        self.split = True
        self.amount.setEnabled(True)
        if self.wallet:
            self.amount.setValue(float(min(self.remaining,self.wallet['balance'])))
        self.preview()

    def pay(self):
        if self.app.busy or not self.confirm.isEnabled() or not self.wallet or self.op:
            return
        current = self.app.current
        n = str(dec(self.amount.value()))
        if not self.app.ask('ยืนยันรายการ',self.confirm.text()+'\nCard ID: '+current[0]+'\nวางบัตรไว้จนรายการสำเร็จ'):
            return
        if self.app.current != current or not self.confirm.isEnabled():
            banner(self.notice,'error','บัตรเปลี่ยนแล้ว กรุณาตรวจสอบใหม่')
            return
        self.op = str(uuid.uuid4())
        self.request = dict(kind='REFUND' if self.refund else 'PAY',order=self.oid,uid=current[0],token=current[1],amount=n)
        if self.refund:
            self.request['part'] = self.part['id']
        self.submit()

    def submit(self):
        if self.app.busy:
            banner(self.notice,'warning','กำลังตรวจข้อมูล กรุณารอสักครู่แล้วดำเนินคำขอเดิม')
            return
        self.locked = True
        self.confirm.setEnabled(False)
        self.change.setEnabled(False)
        self.split_btn.setEnabled(False)
        self.amount.setEnabled(False)
        self.pause.setEnabled(False)
        self.cancel.setEnabled(False)
        self.check.setEnabled(False)
        self.abandon.setEnabled(False)
        banner(self.notice,'warning','กำลังทำรายการ • ห้ามนำบัตรออกหรือปิดโปรแกรม')
        op,req = self.op,self.request
        def work():
            self.app.verify_physical_card(req['uid'],req['token'])
            self.app.db.intent(op,req)
            return self.app.db.execute(op)
        self.app.run(work,self.completed,self.uncertain)

    def completed(self,result):
        self.op = self.request = None
        self.locked = False
        self.app.must_remove = bool(self.app.current)
        self.removed()
        banner(self.notice,'success','รายการสำเร็จ '+baht(result['amount'])+' • ยอดคงเหลือ '+baht(result['balance'])+' • นำบัตรออกก่อนรายการถัดไป')
        self.pause.setEnabled(True)
        self.change.setEnabled(True)
        self.split_btn.setEnabled(True)
        self.cancel.setEnabled(True)
        self.check.hide()
        self.abandon.hide()
        self.refresh()

    def uncertain(self,message):
        self.locked = False
        banner(self.notice,'error',message+'\nผลรายการยังต้องตรวจสอบ • อย่าจ่ายหรือคืนซ้ำด้วยคำขอใหม่')
        self.check.show()
        self.abandon.show()
        self.check.setEnabled(True)
        self.abandon.setEnabled(True)
        self.pause.setEnabled(True)
        self.app.refresh_pending()

    def recover(self):
        if self.op:
            # Same idempotency key: committed results are returned, never charged twice.
            # Re-execution of an uncommitted request requires its original card.
            current = self.app.current
            if current != (self.request['uid'],self.request['token']) or not self.app.reader_ready:
                banner(self.notice,'warning','แตะบัตรเดิมเพื่อดำเนินคำขอเดิม • หรือยุติคำขอเพื่อตรวจผลโดยไม่หักเพิ่ม')
                return
            self.submit()

    def abandon_op(self):
        if self.app.busy or not self.op or not self.app.ask('ตรวจสอบและยุติคำขอ','จะล็อกตรวจสอบผลก่อน หากสำเร็จแล้วจะแสดงผลเดิม ถ้ายังไม่สำเร็จจะยุติคำขอนี้'):
            return
        self.locked = True
        def done(result):
            if result:
                self.completed(result)
            else:
                self.op = self.request = None
                self.locked = False
                self.change.setEnabled(True)
                self.split_btn.setEnabled(True)
                self.cancel.setEnabled(True)
                self.pause.setEnabled(True)
                self.check.hide()
                self.abandon.hide()
                banner(self.notice,'success','ยุติคำขอที่ยังไม่สำเร็จแล้ว • ตรวจออเดอร์ใหม่')
                self.refresh()
                self.app.refresh_pending()
        self.app.run(lambda:self.app.db.reject(self.op),done,self.uncertain)

    def cancel_paid(self):
        if not self.app.busy and self.o and self.o['state']=='PARTIAL':
            if self.app.ask('คืนยอดที่ชำระแล้ว','สร้างแผนคืนยอดที่จ่ายแล้วทั้งหมดเข้าบัตรเดิม? ออเดอร์นี้จะไม่เข้าคิว'):
                self.app.run(lambda:self.app.db.plan(self.oid,{},'ยกเลิกออเดอร์ชำระบางส่วน',True),self.start_refund)

    def start_refund(self,_):
        self.refund = True
        self.setWindowTitle('คืนยอดชำระบางส่วน')
        self.refresh()

    def reject(self):
        if self.locked or self.app.busy:
            return
        # Closing does not delete any order, payment, refund plan or operation.
        super().reject()


class StallPOSApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Food Court Stall POS ['+STALL+']')
        self.setMinimumSize(1100,680)
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
        self.queue_rows = []
        self.queue_order_rows = []
        self.categories = []
        self.selected_category = 'All'
        self.category_buttons = []
        self.public = None
        self.saved_shop_name = STALL
        self.bridge = Bridge()
        self.bridge.tag.connect(self.tag)
        self.bridge.removed.connect(self.removed)
        self.build()
        self.worker = NFCWorker(on_tag_detected=self.bridge.tag.emit,on_tag_removed=self.bridge.removed.emit)
        self.worker.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(800)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.auto_refresh)
        self.poll.start(15000)
        self.run(self.db.init,self.initialized,self.initialization_failed)

    def verify_physical_card(self,uid,token):
        with self.worker._lock:
            device = self.worker._pn532
            if not device:
                raise BusinessError('เครื่องอ่านไม่พร้อม')
            raw = device.read_passive_target(timeout=.2)
            if raw is None or ':'.join(f'{b:02X}' for b in raw)!=uid:
                raise BusinessError('ไม่มีบัตรเดิมบนเครื่องอ่าน ยังไม่ส่งรายการใหม่')
            payload = self.worker._read_card_pages()
            if payload is None:
                raise BusinessError('อ่านบัตรไม่สำเร็จ')
            valid,actual,_ = TokenSecurity.verify_token_payload(bytes(raw),payload)
            if not valid or actual!=token:
                raise BusinessError('บัตรหรือ Token เปลี่ยนแล้ว กรุณาตรวจสอบใหม่')

    def run(self,fn,done=None,failed=None):
        if self.busy:
            return False
        self.busy = True
        self.pages.setEnabled(False)
        for n in self.nav:
            n.setEnabled(False)
        j = Job(fn,self)
        self.jobs.add(j)
        def unlock():
            self.busy = False
            self.pages.setEnabled(True)
            for n in self.nav:
                n.setEnabled(True)
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
        j.done.connect(ok)
        j.error.connect(error)
        j.finished.connect(lambda:self.jobs.discard(j))
        j.finished.connect(j.deleteLater)
        j.start()
        return True

    def message(self,text):
        QMessageBox.information(self,'Stall POS',text)

    def ask(self,title,text):
        m = QMessageBox(self)
        m.setWindowTitle(title)
        m.setText(text)
        yes = m.addButton('ยืนยัน',QMessageBox.ButtonRole.AcceptRole)
        no = m.addButton('กลับ',QMessageBox.ButtonRole.RejectRole)
        m.setDefaultButton(no)
        m.exec()
        return m.clickedButton()==yes

    def build(self):
        root = QWidget()
        self.setCentralWidget(root)
        b = QVBoxLayout(root)
        b.setContentsMargins(18,14,18,14)
        header,h = panel()
        row = QHBoxLayout()
        row.addWidget(lab('Food Court Stall POS','title'),1)
        self.reader = lab('Reader: Connecting…')
        self.db_status = lab('Database: Connecting…')
        for status_label, minimum_width in (
            (self.reader, 205),
            (self.db_status, 205),
        ):
            status_label.setMinimumWidth(minimum_width)
            status_label.setMinimumHeight(42)
            status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_label.setWordWrap(False)
            status_label.setSizePolicy(
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Fixed,
            )
        row.addWidget(self.reader)
        row.addWidget(self.db_status)
        row.addWidget(lab(STALL))
        row.addWidget(button('รายละเอียดทางเทคนิค',self.technical))
        h.addLayout(row)
        b.addWidget(header)
        row = QHBoxLayout()
        self.nav = []
        for index,name in enumerate(('ขายอาหาร','คิวอาหาร','ประวัติธุรกรรม','จัดการเมนู')):
            w = button(name,lambda _,i=index:self.navigate(i))
            w.setCheckable(True)
            row.addWidget(w)
            self.nav.append(w)
        row.addStretch()
        self.pending_button = button('รายการค้าง / ตรวจผล',self.show_pending)
        self.pending_button.hide()
        row.addWidget(self.pending_button)
        b.addLayout(row)
        self.notice = lab('','noticeInfo')
        banner(self.notice,'info','กำลังเชื่อมต่อฐานข้อมูล')
        b.addWidget(self.notice)
        self.pages = QStackedWidget()
        b.addWidget(self.pages,1)
        self.sale_page()
        self.queue_page()
        self.history_page()
        self.menu_page()
        self.nav[0].setChecked(True)

    def sale_page(self):
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0,0,0,0)
        left,b = panel()
        b.addWidget(lab('Menu','title'))
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
        self.category_layout.setContentsMargins(0,0,0,0)
        self.category_layout.setSpacing(8)
        categories.setWidget(category_widget)
        b.addWidget(categories)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.menu_tiles = QWidget()
        self.grid = QGridLayout(self.menu_tiles)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.menu_tiles)
        b.addWidget(scroll,1)
        center,b = panel()
        b.addWidget(lab('Current Order','title'))
        self.cart_table = table(['No.','Product','Quantity','Price','Total','Order Note','ลบ'])
        self.cart_table.verticalHeader().setDefaultSectionSize(58)
        for col,width in ((0,42),(2,110),(3,72),(4,76),(6,42)):
            self.cart_table.horizontalHeader().setSectionResizeMode(col,QHeaderView.ResizeMode.Fixed)
            self.cart_table.setColumnWidth(col,width)
        self.cart_table.itemSelectionChanged.connect(self.select_cart_note)
        b.addWidget(self.cart_table,1)
        self.note_for = lab('Order Note • เลือกอาหารในตารางก่อน','instruction')
        b.addWidget(self.note_for)
        self.note = QLineEdit()
        self.note.setMaxLength(250)
        self.note.setPlaceholderText('เช่น ไม่เผ็ด ไม่ใส่น้ำแข็ง')
        b.addWidget(self.note)
        self.save_note = button('Save Note to Selected Item',self.save_cart_note,True)
        b.addWidget(self.save_note)
        self.note.returnPressed.connect(self.save_cart_note)
        right,b = panel()
        b.addWidget(lab('Payment Summary','title'))
        self.total = lab('฿0.00','money')
        self.count = lab('Items: 0')
        b.addWidget(self.count)
        b.addWidget(self.total)
        card,cb = panel()
        cb.setContentsMargins(12,10,12,10)
        cb.setSpacing(6)
        card.setStyleSheet('QFrame#panel {background:#edf5ff;border:1px solid #bdd3ff;border-radius:12px;}')
        self.sale_card_info = lab('แตะบัตรเพื่อดูยอดก่อนชำระ','instruction')
        self.sale_card_amount = lab('—','money')
        self.sale_card_amount.setStyleSheet('font-size:28px;font-weight:bold;color:#215be8;')
        self.sale_after = lab('ยังไม่หักเงิน • ต้องกดยืนยันก่อน','instruction')
        self.sale_after.setStyleSheet('font-size:18px;font-weight:bold;padding:0;color:#164ca1;')
        cb.addWidget(self.sale_card_info)
        cb.addWidget(self.sale_card_amount)
        cb.addWidget(self.sale_after)
        b.addWidget(card)
        self.proceed = button('Proceed to Card Payment',self.begin_payment,True)
        self.proceed.setEnabled(False)
        b.addWidget(self.proceed)
        b.addWidget(button('Clear Order',self.clear_cart))
        b.addWidget(lab('Recent Sales'))
        self.recent = table(['เวลา','ออเดอร์','ยอดรวม'])
        self.recent.cellDoubleClicked.connect(lambda r,c:self.order_detail(self.recent_rows[r]['id']))
        b.addWidget(self.recent,1)
        b.addWidget(button('ออเดอร์ / สลิปย้อนหลัง',self.show_orders))
        row.addWidget(left,29)
        row.addWidget(center,45)
        row.addWidget(right,26)
        self.pages.addWidget(page)

    def queue_page(self):
        page,b = panel()
        row = QHBoxLayout()
        row.addWidget(lab('คิวอาหาร','title'),1)
        self.queue_filter = QComboBox()
        self.queue_filter.addItems(['วันนี้','ทั้งหมด','รับแล้ววันนี้'])
        self.queue_filter.currentTextChanged.connect(self.render_queue)
        row.addWidget(self.queue_filter)
        row.addWidget(button('รีเฟรช',self.refresh_all))
        row.addWidget(button('จอคิวลูกค้า',self.show_public))
        b.addLayout(row)
        self.queue_board = QHBoxLayout()
        self.queue_boxes = {}
        for state,title in (('WAITING','รอทำ'),('PREPARING','กำลังทำ'),('READY','พร้อมรับ')):
            col,box = panel()
            col.setObjectName({'WAITING':'queueWaiting','PREPARING':'queuePreparing','READY':'queueReady'}[state])
            box.addWidget(lab(title,'title'))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            cards = QVBoxLayout(content)
            cards.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(content)
            box.addWidget(scroll,1)
            self.queue_boxes[state] = cards
            self.queue_board.addWidget(col,1)
        b.addLayout(self.queue_board,1)
        self.queue_table = table(['วันที่ / คิว','ออเดอร์','รายการอาหาร','เวลา','ชำระเงิน','สถานะอาหาร'])
        self.queue_table.setMaximumHeight(145)
        self.queue_table.cellDoubleClicked.connect(lambda r,c:self.order_detail(self.queue_rows[r]['id']))
        b.addWidget(self.queue_table)
        row = QHBoxLayout()
        row.addWidget(button('รายละเอียดคิว',self.selected_queue_detail))
        row.addWidget(button('เริ่มทำ / พร้อมรับ / รับแล้ว',self.advance_queue,True))
        row.addWidget(button('เรียกคิวซ้ำ',self.call_queue))
        b.addLayout(row)
        self.pages.addWidget(page)

    def history_page(self):
        page,b = panel()
        row = QHBoxLayout()
        row.addWidget(lab('ประวัติธุรกรรม','title'),1)
        row.addWidget(button('ดูรายการทั้งหมด',self.all_history))
        row.addWidget(button('รีเฟรช',self.refresh_history))
        b.addLayout(row)
        self.history_label = lab('รายการของ '+STALL+' รวมออเดอร์เดิมที่นำเข้าประวัติ','muted')
        b.addWidget(self.history_label)
        self.history_filter = lab('ยังไม่ได้กรอง Card ID','instruction')
        b.addWidget(self.history_filter)
        self.history_table = table(['วัน / เวลา','ออเดอร์','คิว','Card ID','ประเภท','จำนวนเงิน','ยอดหลังรายการ'])
        self.history_table.cellDoubleClicked.connect(self.history_click)
        b.addWidget(self.history_table,1)
        row = QHBoxLayout()
        row.addWidget(button('รายละเอียดออเดอร์',self.selected_history))
        row.addWidget(button('ดูสลิป',self.selected_receipt))
        row.addWidget(button('คืนค่าอาหาร',self.selected_refund,danger=True))
        row.addWidget(button('ออเดอร์ / แผนคืนค้าง',self.show_orders))
        b.addLayout(row)
        self.pages.addWidget(page)

    def menu_page(self):
        page,b = panel()
        row = QHBoxLayout()
        row.addWidget(lab('จัดการเมนู • '+STALL,'title'),1)
        row.addWidget(button('เพิ่มเมนู',lambda:self.edit_menu(),True))
        row.addWidget(button('จัดการหมวด',self.manage_categories))
        b.addLayout(row)
        shop = QHBoxLayout()
        shop.addWidget(lab('ชื่อร้าน'))
        self.shop_name = QLineEdit()
        self.shop_name.setMaxLength(100)
        shop.addWidget(self.shop_name,1)
        shop.addWidget(button('บันทึกชื่อร้าน',self.save_shop_name))
        b.addLayout(shop)
        self.menu_table = table(['ชื่อ','หมวด','ราคา','สถานะ','รายละเอียด'])
        b.addWidget(self.menu_table,1)
        row = QHBoxLayout()
        row.addWidget(button('แก้ไข',lambda:self.edit_menu(self.selected_menu())))
        row.addWidget(button('เปิด / ปิดขาย',self.toggle_menu))
        row.addWidget(button('ลบเมนู',self.delete_menu,danger=True))
        b.addLayout(row)
        self.pages.addWidget(page)

    def initialized(self,_):
        self.ready = True
        pill(self.db_status,'ready','Database: Connected')
        banner(self.notice,'info','เลือกรายการอาหาร แล้วใส่ Order Note')
        self.refresh_all()

    def initialization_failed(self,message):
        self.ready = False
        pill(self.db_status,'error','Database: Unavailable')
        banner(self.notice,'error','เชื่อมต่อฐานข้อมูลไม่ได้ ตรวจสอบ database.py แล้วกดเชื่อมต่อใหม่')
        self.message(message)

    def navigate(self,index):
        if self.busy or not self.ready:
            return
        self.pages.setCurrentIndex(index)
        for i,w in enumerate(self.nav):
            w.setChecked(i==index)
        page_notices = {
            0:('info','เลือกรายการอาหาร แล้วใส่ Order Note'),
            1:('info','เลือกคิว แล้วอัปเดตสถานะอาหาร'),
            2:('info','ดับเบิลคลิก Card ID เพื่อดูเฉพาะบัตรนี้'),
            3:('info','เลือกเมนูที่ต้องการแก้ไข หรือกดเพิ่มเมนู'),
        }
        banner(self.notice,*page_notices[index])
        if index==2:
            self.refresh_history()
        else:
            self.refresh_all()

    def refresh_all(self):
        if not self.ready or self.busy:
            return
        def fetch():
            return self.db.products(True),self.db.categories(),self.db.orders(),self.db.pending(),self.db.orders(True),self.db.stall_name()
        def done(data):
            self.products,categories,self.order_rows,self.pending_rows,self.queue_order_rows,shop_name = data
            self.saved_shop_name = shop_name
            if not self.shop_name.hasFocus():
                self.shop_name.setText(shop_name)
            self.categories = categories
            self.render_categories()
            self.render_menu()
            self.menu_rows = self.products
            fill(self.menu_table,[(p['product_name'],p['category'],baht(p['price']),'เปิดขาย' if p['is_available'] else 'ปิดขาย',p['description']) for p in self.menu_rows])
            for r,p in enumerate(self.menu_rows):
                self.menu_table.item(r,3).setForeground(QColor('#15803d' if p['is_available'] else '#64748b'))
            self.recent_rows = [o for o in self.order_rows if o['state']=='PAID'][:15]
            fill(self.recent,[(str(o['created'])[11:19],o['id'][:8],baht(o['total']-o['returned'])) for o in self.recent_rows])
            self.update_pending_button()
            self.render_queue()
            self.render_cart()
            if self.pending_rows:
                banner(self.notice,'error','มีรายการรอตรวจผล เปิด “รายการค้าง / ตรวจผล” ก่อนทำรายการเดิมซ้ำ')
            if self.public:
                self.update_public()
        self.run(fetch,done)

    def refresh_pending(self):
        def done(rows):
            self.pending_rows = rows
            self.update_pending_button()
        self.run(self.db.pending,done)

    def update_pending_button(self):
        active = sum(o['state'] in ('OPEN','PARTIAL','REFUND_PENDING') for o in self.order_rows)
        self.pending_button.setVisible(bool(self.pending_rows or active))
        self.pending_button.setText('รอตรวจผล ('+str(len(self.pending_rows))+')' if self.pending_rows else 'ออเดอร์ค้าง ('+str(active)+')')

    def save_shop_name(self):
        value = self.shop_name.text().strip()
        if not value:
            self.shop_name.setText(self.saved_shop_name)
            self.message('กรุณากรอกชื่อร้านก่อนกดบันทึก')
            return
        if self.busy or value == self.saved_shop_name:
            return

        def saved(_):
            self.saved_shop_name = value
            self.shop_name.clearFocus()
            banner(self.notice,'success','บันทึกชื่อร้านแล้ว')
            self.refresh_all()

        def failed(message):
            self.shop_name.setText(self.saved_shop_name)
            self.message('บันทึกชื่อร้านไม่สำเร็จ ชื่อเดิมยังคงอยู่\n'+message)

        self.run(lambda:self.db.rename_stall(value),saved,failed)

    def render_categories(self):
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        preferred = ['Rice','Noodles','Drinks']
        names = ['All']+[n for n in preferred if n in self.categories]+[n for n in self.categories if n not in preferred]
        if self.selected_category not in names:
            self.selected_category = 'All'
        self.category_buttons = []
        for name in names:
            tab = button(name,lambda _,n=name:self.choose_category(n))
            tab.setObjectName('category')
            tab.setCheckable(True)
            tab.setChecked(name==self.selected_category)
            self.category_layout.addWidget(tab)
            self.category_buttons.append(tab)
        self.category_layout.addStretch()

    def choose_category(self,name):
        self.selected_category = name
        for tab in self.category_buttons:
            tab.setChecked(tab.text()==name)
        self.render_menu()

    def render_menu(self,*_):
        while self.grid.count():
            x = self.grid.takeAt(0)
            if x.widget():
                x.widget().deleteLater()
        cat = self.selected_category
        query = self.menu_search.text().strip().lower() if hasattr(self,'menu_search') else ''
        products = [p for p in self.products if p['is_available'] and (cat=='All' or p['category']==cat)
                    and (not query or query in p['product_name'].lower() or query in p['category'].lower() or query in p['description'].lower())]
        if not products:
            empty = lab('ไม่พบเมนูที่ตรงกับการค้นหา','muted')
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(120)
            self.grid.addWidget(empty,0,0,1,2)
            return
        for index,p in enumerate(products):
            w,b = panel()
            title = lab(p['product_name'])
            title.setStyleSheet('font-size:18px;font-weight:bold;')
            b.addWidget(title)
            price = lab(baht(p['price']),'money')
            price.setStyleSheet('font-size:28px;font-weight:bold;color:#215be8;')
            b.addWidget(price)
            if p['description']:
                b.addWidget(lab(p['description'],'muted'))
            b.addWidget(button('+ Add',lambda _,pid=p['product_id']:self.add_cart(pid),True))
            self.grid.addWidget(w,index//2,index%2)

    def add_cart(self,pid):
        self.cache_cart_note()
        self.cart[pid] = min(999,self.cart.get(pid,0)+1)
        self.selected_cart_pid = pid
        self.note.setText(self.cart_notes.get(pid,''))
        self.render_cart()

    def render_cart(self):
        self.cache_cart_note()
        lookup = {p['product_id']:p for p in self.products}
        for pid in list(self.cart):
            if pid not in lookup:
                self.cart.pop(pid)
                self.cart_notes.pop(pid,None)
                banner(self.notice,'warning','เมนูในตะกร้าบางรายการถูกลบ กรุณาตรวจสอบออเดอร์ใหม่')
        self.cart_table.blockSignals(True)
        self.cart_table.setRowCount(len(self.cart))
        total = Decimal(0)
        for r,(pid,qty) in enumerate(self.cart.items()):
            p = lookup.get(pid)
            if not p:
                continue
            subtotal = dec(p['price'])*qty
            total += subtotal
            for c,v in ((0,str(r+1)),(1,p['product_name']),(3,baht(p['price'])),(4,baht(subtotal)),(5,self.cart_notes.get(pid,''))):
                item = QTableWidgetItem(v)
                item.setToolTip(v)
                item.setData(Qt.ItemDataRole.UserRole,pid)
                self.cart_table.setItem(r,c,item)
            controls = QWidget()
            controls.setStyleSheet('background:transparent;')
            row = QHBoxLayout(controls)
            row.setContentsMargins(2,4,2,4)
            row.setSpacing(3)
            minus = button('−',lambda _,i=pid:self.change_qty(i,-1))
            plus = button('+',lambda _,i=pid:self.change_qty(i,1))
            for control in (minus,plus):
                control.setObjectName('quantity')
                control.setFixedSize(30,36)
            minus.setEnabled(qty>1)
            plus.setEnabled(qty<999)
            number = lab(str(qty),'quantityNumber')
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addStretch()
            row.addWidget(minus)
            row.addWidget(number)
            row.addWidget(plus)
            row.addStretch()
            self.cart_table.setCellWidget(r,2,controls)
            delete = button('×',lambda _,i=pid:self.remove_cart(i),danger=True)
            delete.setObjectName('quantity')
            self.cart_table.setCellWidget(r,6,delete)
            if pid==self.selected_cart_pid:
                self.cart_table.selectRow(r)
        self.cart_table.blockSignals(False)
        self.select_cart_note()
        self.total.setText(baht(total))
        self.count.setText('Items: '+str(sum(self.cart.values())))
        self.proceed.setEnabled(self.ready and bool(self.cart) and total<=MAX and not self.pending_rows)
        self.render_sale_balance()

    def cache_cart_note(self):
        if self.selected_cart_pid in self.cart:
            self.cart_notes[self.selected_cart_pid] = self.note.text().strip()

    def select_cart_note(self):
        self.cache_cart_note()
        r = self.cart_table.currentRow()
        item = self.cart_table.item(r,1) if r>=0 else None
        self.selected_cart_pid = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.note.setText(self.cart_notes.get(self.selected_cart_pid,''))
        self.note.setEnabled(self.selected_cart_pid in self.cart)
        self.save_note.setEnabled(self.selected_cart_pid in self.cart)
        self.note_for.setText('Order Note for: '+item.text() if item else 'Order Note • เลือกอาหารในตารางก่อน')

    def save_cart_note(self):
        if self.selected_cart_pid in self.cart:
            self.cache_cart_note()
            self.render_cart()
            banner(self.notice,'success','บันทึก Order Note ให้รายการที่เลือกแล้ว')

    def set_qty(self,pid,n):
        if pid not in self.cart:
            return
        self.cart[pid] = max(1,min(999,n))
        QTimer.singleShot(0,self.render_cart)

    def change_qty(self,pid,delta):
        if pid in self.cart and not self.busy:
            self.set_qty(pid,self.cart[pid]+delta)

    def remove_cart(self,pid):
        self.cache_cart_note()
        self.cart.pop(pid,None)
        self.cart_notes.pop(pid,None)
        if self.selected_cart_pid==pid:
            self.selected_cart_pid = None
        self.render_cart()

    def clear_cart(self):
        if self.cart and not self.ask('ล้างตะกร้า','ล้างอาหารที่ยังไม่ได้สร้างออเดอร์?'):
            return
        self.cart.clear()
        self.cart_notes.clear()
        self.selected_cart_pid = None
        self.note.clear()
        self.render_cart()

    def begin_payment(self):
        if not self.cart or self.busy or self.pending_rows:
            return
        oid = str(uuid.uuid4())
        self.cache_cart_note()
        cart,notes = dict(self.cart),dict(self.cart_notes)
        def done(_):
            self.cart.clear()
            self.cart_notes.clear()
            self.selected_cart_pid = None
            self.note.clear()
            self.render_cart()
            self.open_checkout(oid)
        # Freeze order prices at creation. Unpaid orders can be paused safely.
        self.run(lambda:self.db.create(oid,cart,'',notes),done)

    def open_checkout(self,oid,refund=False):
        if self.pending_rows:
            self.message('มีคำขอรอตรวจผล เปิด “รายการค้าง / ตรวจผล” เพื่อทำคำขอเดิมให้เสร็จก่อน')
            return
        self.checkout = Checkout(self,oid,refund)
        self.checkout.exec()
        self.checkout = None
        self.refresh_all()

    def tag(self,uid,valid,token,status):
        self.card_generation += 1
        self.current = (uid,token) if valid and token else None
        self.sale_wallet = None
        self.render_sale_balance()
        if not valid or not token:
            if self.checkout:
                self.checkout.removed()
                self.checkout.notice.setText('บัตรอ่านไม่ผ่านหรือไม่พร้อมใช้งาน • ยังไม่เริ่มคำขอชำระใหม่')
            banner(self.notice,'error','อ่านบัตรไม่ผ่าน นำออกแล้วลองใหม่ หรือใช้บัตรใบอื่น')
            return
        if self.must_remove:
            return
        if self.checkout and not self.busy:
            self.checkout.on_card(self.current)
        elif not self.busy:
            self.read_sale_card()

    def removed(self):
        self.card_generation += 1
        self.current = None
        self.must_remove = False
        if self.checkout:
            self.checkout.removed()
        self.render_sale_balance()

    def tick(self):
        connection = getattr(self.worker,'_serial_conn',None)
        ready = bool(self.worker.is_alive() and getattr(self.worker,'_pn532',None) and connection and connection.is_open)
        pill(self.reader,'ready' if ready else 'error','Reader: Ready' if ready else 'Reader: Disconnected')
        if self.reader_ready and not ready:
            self.removed()
        self.reader_ready = ready
        if self.checkout:
            self.checkout.preview()
            if ready and self.current and not self.must_remove and not self.busy and self.checkout.o and not self.checkout.wallet and not self.checkout.op and not self.checkout.locked:
                self.checkout.on_card(self.current)
        elif ready and self.current and not self.sale_wallet and not self.must_remove and not self.busy and self.ready and self.pages.currentIndex()==0:
            self.read_sale_card()
        if self.public:
            self.update_public()

    def auto_refresh(self):
        if not self.busy and not self.checkout:
            if self.pages.currentIndex()==2:
                self.refresh_history()
            else:
                self.refresh_all()

    def technical(self):
        d = QDialog(self)
        d.setWindowTitle('รายละเอียดทางเทคนิค')
        b = QVBoxLayout(d)
        b.addWidget(lab(self.reader.text()+'\n'+self.db_status.text()+'\nNFC port: '+DEFAULT_PORT+'\nCard ID: '+(self.current[0] if self.current else '—')+'\nToken UUID: '+(str(self.current[1]) if self.current else '—')))
        def reconnect():
            d.accept()
            self.run(self.db.init,self.initialized,self.initialization_failed)
        b.addWidget(button('เชื่อมต่อ Database ใหม่',reconnect))
        b.addWidget(button('ปิด',d.reject))
        d.exec()

    def read_sale_card(self):
        if not self.ready or not self.current or self.busy or self.must_remove or self.pages.currentIndex()!=0:
            return
        current,gen = self.current,self.card_generation
        def done(wallet):
            if gen==self.card_generation and self.current==current:
                self.sale_wallet = wallet
                self.render_sale_balance()
        def failed(message):
            if gen==self.card_generation:
                self.must_remove = True
                self.sale_card_info.setText(message+' • นำบัตรออกแล้วลองใหม่')
        self.run(lambda:self.db.wallet(current[1],current[0]),done,failed)

    def render_sale_balance(self):
        if not self.sale_wallet:
            self.sale_card_info.setStyleSheet('font-size:18px;font-weight:bold;padding:0;color:#164ca1;')
            self.sale_card_info.setText('กำลังอ่านยอด…' if self.current else 'แตะบัตรเพื่อดูยอดก่อนชำระ')
            self.sale_card_amount.setText('—')
            self.sale_after.setText('ยังไม่หักเงิน • ต้องกดยืนยันก่อน')
            return
        wallet = self.sale_wallet
        self.sale_card_info.setStyleSheet('font-size:15px;font-weight:normal;padding:0;color:#164ca1;')
        self.sale_card_info.setText('Card ID: '+wallet['card_uid']+'\n'+('ยอดก่อนชำระ / บัตรอยู่บนเครื่องอ่าน' if self.current else 'ยอดเมื่ออ่านล่าสุด / นำบัตรออกแล้ว')+('\nสถานะ: '+wallet['status'] if wallet['status']!='ACTIVE' else ''))
        self.sale_card_amount.setText(baht(wallet['balance']))
        lookup = {p['product_id']:p for p in self.products}
        total = sum((dec(lookup[pid]['price'])*qty for pid,qty in self.cart.items() if pid in lookup),Decimal(0))
        left = dec(wallet['balance'])-total
        self.sale_after.setText('ยอดหลังชำระ: '+baht(left) if left>=0 else 'เงินไม่พอ • ขาด '+baht(-left)+'\nเปลี่ยนบัตร หรือแบ่งจ่ายหลายใบได้')
        self.sale_after.setStyleSheet('color:'+('#b45309' if left<0 else '#164ca1')+';font-size:18px;font-weight:bold;padding:0;')

    def refresh_history(self):
        if self.ready and not self.busy:
            uid = self.history_uid
            def done(rows):
                self.history_rows = rows
                self.history_label.setText(('Card ID: '+uid+' • ' if uid else '')+'รายการของ '+STALL+' (ล่าสุดสูงสุด 300)')
                self.history_filter.setText('กำลังแสดง Card ID: '+uid if uid else 'ดับเบิลคลิก Card ID เพื่อดูเฉพาะบัตรนี้')
                self.history_filter.setStyleSheet('color:#164ca1;font-size:17px;font-weight:bold;padding:8px;')
                fill(self.history_table,[(str(r['created'])[:19],r['order_id'][:8],f"Q{r['queue_no']:03}" if r['queue_no'] else '—',r['uid'],'ชำระอาหาร' if r['kind']=='PAY' else 'คืนค่าอาหาร',('−' if r['kind']=='PAY' else '+')+baht(r['amount']),baht(r['balance'])) for r in rows])
                for i in range(len(rows)):
                    self.history_table.item(i,3).setForeground(QColor('#2563eb'))
                    color = QColor('#15803d') if rows[i]['kind']!='PAY' else QColor('#215be8')
                    self.history_table.item(i,4).setForeground(color)
                    self.history_table.item(i,5).setForeground(color)
            self.run(lambda:self.db.history(uid),done)

    def all_history(self):
        self.history_uid = None
        self.refresh_history()

    def history_click(self,r,c):
        if c==3:
            self.history_uid = self.history_rows[r]['uid']
            self.refresh_history()
        else:
            self.order_detail(self.history_rows[r]['order_id'])

    def selected_history(self):
        r = self.history_table.currentRow()
        if r>=0:
            self.order_detail(self.history_rows[r]['order_id'])

    def selected_refund(self):
        r = self.history_table.currentRow()
        if r>=0:
            self.refund_dialog(self.history_rows[r]['order_id'])

    def selected_receipt(self):
        r = self.history_table.currentRow()
        if r>=0 and not self.busy:
            self.run(lambda:self.db.order(self.history_rows[r]['order_id']),lambda o:ReceiptDialog(o,self).exec())

    def show_orders(self):
        if self.busy:
            return
        def done(rows):
            d = QDialog(self)
            d.setWindowTitle('ออเดอร์ / รายการค้าง')
            d.resize(1000,600)
            b = QVBoxLayout(d)
            t = table(['วันเวลา','ออเดอร์','ยอดรวม','จ่ายแล้ว','คืนแล้ว','สถานะ'])
            fill(t,[(str(o['created'])[:19],o['id'][:8],baht(o['total']),baht(o['paid']),baht(o['returned']),o['state']) for o in rows])
            b.addWidget(t)
            def choose():
                r = t.currentRow()
                if r<0:
                    return
                oid,state = rows[r]['id'],rows[r]['state']
                d.accept()
                if state in ('OPEN','PARTIAL','REFUND_PENDING'):
                    self.open_checkout(oid,state=='REFUND_PENDING')
                else:
                    self.order_detail(oid)
            b.addWidget(button('เปิดรายละเอียด / ชำระต่อ / คืนต่อ',choose,True))
            b.addWidget(button('ปิด',d.reject))
            d.exec()
        self.run(self.db.orders,done)

    def show_pending(self):
        if self.busy:
            return
        def fetch():
            return self.db.orders(),self.db.pending()
        def done(data):
            orders,rows = data
            self.pending_rows = rows
            d = QDialog(self)
            d.setWindowTitle('รายการค้าง / ตรวจผล')
            d.resize(1180,700)
            b = QVBoxLayout(d)
            b.addWidget(lab('รายการค้าง / ตรวจผล','title'))
            warning = lab('','noticeError')
            banner(warning,'error','ตรวจสอบผลคำขอเดิมก่อน ห้ามเริ่มรายการซ้ำ')
            b.addWidget(warning)
            body = QHBoxLayout()
            left,lb = panel()
            lb.addWidget(lab('ออเดอร์ที่ยังไม่เสร็จสมบูรณ์','title'))
            active = [o for o in orders if o['state'] in ('OPEN','PARTIAL','REFUND_PENDING')]
            ot = table(['ออเดอร์','ยอดรวม','ชำระแล้ว','คืนแล้ว','สถานะ'])
            fill(ot,[(o['id'][:8],baht(o['total']),baht(o['paid']),baht(o['returned']),o['state']) for o in active])
            lb.addWidget(ot,1)
            def open_order():
                r = ot.currentRow()
                if r<0:
                    return
                o = active[r]
                d.accept()
                self.open_checkout(o['id'],o['state']=='REFUND_PENDING')
            lb.addWidget(button('เปิดทำต่อ',open_order,True))
            right,rb = panel()
            rb.addWidget(lab('คำขอที่รอตรวจผล','title'))
            pt = table(['Reference ID','ประเภท','Card ID','จำนวนเงิน','สถานะ'])
            fill(pt,[(p['id'][:12],p['request'].get('kind','—'),p['request'].get('uid','—'),baht(p['request'].get('amount',0)),'PENDING') for p in rows])
            rb.addWidget(pt,1)
            detail = lab('เลือกคำขอเดิมเพื่อดำเนินการด้วยเลขอ้างอิงเดิม','instruction')
            rb.addWidget(detail)
            def recover():
                r = pt.currentRow()
                if r<0:
                    return
                p = rows[r]
                d.accept()
                self.checkout = Checkout(self,p['request']['order'],p['request']['kind']=='REFUND')
                self.checkout.op,self.checkout.request = p['id'],p['request']
                self.checkout.uncertain('คำขอนี้ต้องตรวจผลก่อนเริ่มคำขอใหม่')
                self.checkout.exec()
                self.checkout = None
                self.refresh_all()
            rb.addWidget(button('ตรวจสอบผล / ดำเนินรายการเดิม',recover,True))
            body.addWidget(left,1)
            body.addWidget(right,1)
            b.addLayout(body,1)
            row = QHBoxLayout()
            row.addWidget(button('รายละเอียดทางเทคนิค',lambda:self.technical()))
            row.addStretch()
            row.addWidget(button('ปิด',d.reject))
            b.addLayout(row)
            d.exec()
            self.refresh_all()
        self.run(fetch,done)

    def order_detail(self,oid):
        def done(o):
            d = QDialog(self)
            d.setWindowTitle('รายละเอียดออเดอร์')
            d.resize(1050,700)
            b = QVBoxLayout(d)
            b.addWidget(lab('ออเดอร์ '+o['id'][:8]+' • '+(f"Q{o['queue_no']:03}" if o['queue_no'] else 'ยังไม่ออกคิว'),'title'))
            status_row = QHBoxLayout()
            payment_status = lab('● '+{'PAID':'ชำระครบ','PARTIAL':'ชำระบางส่วน','OPEN':'ยังไม่ชำระ','REFUND_PENDING':'รอคืนเงิน','CANCELLED':'ยกเลิก'}.get(o['state'],o['state']))
            pill(payment_status,'ready' if o['state']=='PAID' else 'error' if o['state']=='CANCELLED' else 'warning',payment_status.text())
            food_status = lab('อาหาร: '+{'WAITING':'รอทำ','PREPARING':'กำลังทำ','READY':'พร้อมรับ','COLLECTED':'รับแล้ว','NONE':'ยังไม่เข้าคิว','CANCELLED':'ยกเลิก'}.get(o['queue_state'],o['queue_state']))
            pill(food_status,'ready' if o['queue_state'] in ('READY','COLLECTED') else 'warning',food_status.text())
            status_row.addWidget(payment_status)
            status_row.addWidget(food_status)
            status_row.addStretch()
            b.addLayout(status_row)
            b.addWidget(lab(f"วันที่ {o['created']} • หมายเหตุทั้งออเดอร์: {o['note'] or '—'}"))
            t = table(['No.','อาหาร','จำนวน','คืนแล้ว','ราคา','Order Note'])
            fill(t,[(n,i['name'],i['qty'],i['returned'],baht(i['price']),i.get('note','')) for n,i in enumerate(o['items'],1)])
            b.addWidget(t)
            t = table(['Card ID','จ่าย','คืนแล้ว','ยอดหลังจ่าย'])
            fill(t,[(p['uid'],baht(p['amount']),baht(p['returned']),baht(p['balance'])) for p in o['payments']])
            b.addWidget(t)
            info = lab('','noticeInfo')
            banner(info,'info','ยอดหลังจ่ายเป็นข้อมูล ณ เวลาธุรกรรม ไม่ใช่ยอดปัจจุบัน')
            b.addWidget(info)
            b.addWidget(button('ดู Order Slip / Payment Receipt',lambda:ReceiptDialog(o,d).exec(),True))
            def refund():
                d.accept()
                self.refund_dialog(oid)
            b.addWidget(button('คืนค่าอาหาร / คืนต่อ',refund,danger=True))
            b.addWidget(button('ปิด',d.reject))
            d.exec()
        self.run(lambda:self.db.order(oid),done)

    def refund_dialog(self,oid):
        if self.busy:
            return
        def done(o):
            if o['state']=='REFUND_PENDING':
                self.open_checkout(oid,True)
                return
            if o['state'] not in ('PAID','PARTIAL'):
                self.message('ออเดอร์นี้ไม่พร้อมคืนค่าอาหาร')
                return
            if o['state']=='PARTIAL':
                if self.ask('ยกเลิกชำระบางส่วน','คืนยอดที่จ่ายแล้วทั้งหมดเข้าบัตรเดิม?'):
                    self.run(lambda:self.db.plan(oid,{},'ยกเลิกชำระบางส่วน',True),lambda _:self.open_checkout(oid,True))
                return
            d = QDialog(self)
            d.setWindowTitle('เลือกอาหารที่จะคืน')
            d.resize(1050,650)
            b = QVBoxLayout(d)
            b.addWidget(lab('คืนค่าอาหาร • '+oid[:8],'title'))
            warning = lab('','noticeWarning')
            banner(warning,'warning','ตรวจสอบรายการและแตะบัตรเดิมตามแผนคืน')
            b.addWidget(warning)
            body = QHBoxLayout()
            left_panel,left_box = panel()
            left_box.addWidget(lab('รายการสั่งซื้อเดิม','title'))
            grid = QGridLayout()
            for c,text in enumerate(('No.','รายการ','ราคา','คืนแล้ว','จำนวนคืน','Order Note')):
                head = lab(text)
                head.setStyleSheet('font-weight:bold;')
                grid.addWidget(head,0,c)
            spins = {}
            for row,i in enumerate(o['items'],1):
                s = QSpinBox()
                s.setLocale(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
                s.setRange(0,i['qty']-i['returned'])
                grid.addWidget(lab(str(row)),row,0)
                grid.addWidget(lab(i['name']),row,1)
                grid.addWidget(lab(baht(i['price'])),row,2)
                grid.addWidget(lab(str(i['returned'])),row,3)
                grid.addWidget(s,row,4)
                grid.addWidget(lab(i.get('note') or '—','muted'),row,5)
                spins[str(i['pid'])] = s
            left_box.addLayout(grid)
            reason = QLineEdit()
            reason.setMaxLength(500)
            reason.setPlaceholderText('ระบุเหตุผลในการคืนค่าอาหาร')
            left_box.addWidget(lab('เหตุผลในการคืนค่าอาหาร'))
            left_box.addWidget(reason)
            right_panel,right_box = panel()
            right_box.addWidget(lab('แผนคืนเงิน • คืนเข้าบัตรเดิมเท่านั้น','title'))
            allocation_text = lab('เลือกรายการอาหารเพื่อคำนวณแผนคืน','instruction')
            right_box.addWidget(allocation_text)
            refund_total = lab('฿0.00','money')
            right_box.addWidget(refund_total)
            right_box.addWidget(lab('ระบบจัดสรรคืนจากบัตรที่จ่ายล่าสุดก่อน และไม่เกินยอดที่บัตรแต่ละใบจ่าย\nไม่มีการคืนเป็นเงินสด','muted'))
            right_box.addStretch()
            def preview_refund():
                quantities = {pid:s.value() for pid,s in spins.items()}
                amount = sum((dec(i['price'])*quantities[str(i['pid'])] for i in o['items']),Decimal(0))
                refund_total.setText(baht(amount))
                remaining = amount
                lines = []
                for p in reversed(o['payments']):
                    n = min(remaining,p['amount']-p['returned'])
                    if n>0:
                        lines.append('● Card ID '+p['uid']+'  →  '+baht(n))
                        remaining -= n
                allocation_text.setText('\n'.join(lines) if lines else 'เลือกรายการอาหารเพื่อคำนวณแผนคืน')
            for s in spins.values():
                s.valueChanged.connect(preview_refund)
            body.addWidget(left_panel,58)
            body.addWidget(right_panel,42)
            b.addLayout(body,1)
            def save():
                quantities = {pid:s.value() for pid,s in spins.items()}
                amount = sum((dec(i['price'])*quantities[str(i['pid'])] for i in o['items']),Decimal(0))
                if amount<=0 or not reason.text().strip():
                    self.message('เลือกจำนวนอาหารและระบุเหตุผล')
                    return
                left = amount
                allocation = []
                for p in reversed(o['payments']):
                    n = min(left,p['amount']-p['returned'])
                    if n>0:
                        allocation.append(p['uid']+' → '+baht(n))
                        left -= n
                if not self.ask('ยืนยันสร้างแผนคืน','ยอดคืน '+baht(amount)+'\n'+'\n'.join(allocation)+'\nต้องแตะบัตรเดิมตามแผน ไม่มีการคืนเงินสด'):
                    return
                text = reason.text().strip()
                d.accept()
                self.run(lambda:self.db.plan(oid,quantities,text),lambda _:self.open_checkout(oid,True))
            actions = QHBoxLayout()
            actions.addWidget(button('ยกเลิก',d.reject))
            actions.addWidget(button('ตรวจสอบและสร้างแผนคืน',save,True))
            b.addLayout(actions)
            d.exec()
        self.run(lambda:self.db.order(oid),done)

    def render_queue(self,*_):
        from datetime import date
        mode = self.queue_filter.currentText()
        rows = [o for o in self.queue_order_rows if o['queue_no'] and o['queue_state'] in ('WAITING','PREPARING','READY','COLLECTED')]
        if mode=='วันนี้':
            rows = [o for o in rows if o['queue_day']==date.today() and o['queue_state']!='COLLECTED']
        elif mode=='รับแล้ววันนี้':
            rows = [o for o in rows if o['queue_state']=='COLLECTED']
        self.queue_rows = sorted(rows,key=lambda o:(str(o['queue_day']),o['queue_no']))
        for state,box in self.queue_boxes.items():
            while box.count():
                child = box.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            for o in self.queue_rows:
                if o['queue_state']!=state:
                    continue
                card,cb = panel()
                card.setObjectName({'WAITING':'queueCardWaiting','PREPARING':'queueCardPreparing','READY':'queueCardReady'}[state])
                cb.addWidget(lab(f"Q{o['queue_no']:03}",'money'))
                cb.addWidget(lab(str(o['queue_day'])+' • '+str(o['created'])[11:19],'muted'))
                cb.addWidget(lab('\n'.join(f"{n}. {i['name']} × {i['qty']-i['returned']}"+(' • '+i.get('note','') if i.get('note') else '') for n,i in enumerate(o['items'],1) if i['qty']>i['returned'])))
                if o['note']:
                    cb.addWidget(lab('หมายเหตุ: '+o['note']))
                payment_state = lab('● ชำระเงินแล้ว' if o['state']=='PAID' else '● พักคิว • คืนเงินค้างอยู่')
                payment_state.setStyleSheet('color:'+('#15803d' if o['state']=='PAID' else '#b45309')+';font-weight:bold;')
                cb.addWidget(payment_state)
                cb.addWidget(button('รายละเอียด',lambda _,oid=o['id']:self.order_detail(oid)))
                action = {'WAITING':'เริ่มทำ','PREPARING':'พร้อมรับ','READY':'รับแล้ว'}[state]
                advance = button(action,lambda _,obj=o:self.advance_specific(obj),True)
                advance.setObjectName('success' if state=='READY' else 'warning' if state=='WAITING' else 'primary')
                advance.setEnabled(o['state']=='PAID')
                cb.addWidget(advance)
                box.addWidget(card)
        names = {'WAITING':'รอทำ','PREPARING':'กำลังทำ','READY':'พร้อมรับ','COLLECTED':'รับแล้ว'}
        fill(self.queue_table,[(str(o['queue_day'])+f" / Q{o['queue_no']:03}",o['id'][:8],', '.join(f"{i['name']} × {i['qty']-i['returned']}" for i in o['items'] if i['qty']>i['returned']),str(o['created'])[11:19],o['state'],names[o['queue_state']]) for o in self.queue_rows])

    def selected_queue_detail(self):
        r = self.queue_table.currentRow()
        if r>=0:
            self.order_detail(self.queue_rows[r]['id'])

    def advance_queue(self):
        r = self.queue_table.currentRow()
        if r<0:
            return
        o = self.queue_rows[r]
        self.advance_specific(o)

    def advance_specific(self,o):
        target = {'WAITING':'PREPARING','PREPARING':'READY','READY':'COLLECTED'}.get(o['queue_state'])
        if target and self.ask('เปลี่ยนสถานะคิว',f"Q{o['queue_no']:03} → "+{'PREPARING':'กำลังทำ','READY':'พร้อมรับ','COLLECTED':'รับแล้ว'}[target]):
            self.run(lambda:self.db.queue(o['id'],o['queue_state'],target),lambda _:self.refresh_all())

    def call_queue(self):
        r = self.queue_table.currentRow()
        if r>=0:
            o = self.queue_rows[r]
            QApplication.beep()
            self.message(f"เรียกคิว Q{o['queue_no']:03} • "+STALL+'\nเสียงแจ้งเตือนเท่านั้น ไม่ใช่ระบบประกาศเสียงพูด')

    def show_public(self):
        if self.public:
            self.public.raise_()
            return
        d = QDialog(self)
        d.setWindowTitle(STALL+' • คิวอาหาร')
        d.resize(1200,760)
        b = QVBoxLayout(d)
        header = QHBoxLayout()
        title = lab('Food Court  '+STALL,'title')
        title.setStyleSheet('font-size:36px;font-weight:bold;')
        self.public_clock = lab('','title')
        self.public_clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(title,1)
        header.addWidget(self.public_clock)
        b.addLayout(header)
        columns = QHBoxLayout()
        self.public_labels = {}
        for state,title,color,bg in (
            ('READY','พร้อมรับ','#087a38','#e5f8eb'),
            ('PREPARING','กำลังเตรียม','#164ca1','#eaf3ff'),
            ('WAITING','รอทำ','#a85b00','#fff4d6')):
            frame,box = panel()
            frame.setStyleSheet(f'QFrame#panel{{background:{bg};border:2px solid {color};border-radius:14px;}}')
            heading = lab(title,'title')
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.setStyleSheet(f'font-size:32px;font-weight:bold;color:{color};')
            value = lab('—')
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setStyleSheet(f'font-size:58px;font-weight:bold;color:{color};')
            box.addWidget(heading)
            box.addWidget(value,1)
            self.public_labels[state] = value
            columns.addWidget(frame,1)
        b.addLayout(columns,1)
        public_notice = lab('','noticeSuccess')
        banner(public_notice,'success','กรุณารับอาหารเมื่อหมายเลขคิวแสดงในช่องพร้อมรับ')
        public_notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b.addWidget(public_notice)
        self.public = d
        self.update_public()
        d.finished.connect(lambda _:setattr(self,'public',None))
        d.show()

    def update_public(self):
        from datetime import date,datetime
        rows = [o for o in self.queue_order_rows if o['queue_day']==date.today() and o['state']=='PAID']
        for state,label in self.public_labels.items():
            label.setText('\n'.join(f"Q{o['queue_no']:03}" for o in rows if o['queue_state']==state) or '—')
        self.public_clock.setText(datetime.now().strftime('%H:%M'))

    def selected_menu(self):
        r = self.menu_table.currentRow()
        return self.menu_rows[r] if r>=0 else None

    def edit_menu(self,p=None):
        if self.busy:
            return
        d = QDialog(self)
        d.setWindowTitle('แก้ไขเมนู' if p else 'เพิ่มเมนู')
        d.resize(520,400)
        b = QVBoxLayout(d)
        b.addWidget(lab(d.windowTitle(),'title'))
        f = QFormLayout()
        name = QLineEdit(p['product_name'] if p else '')
        name.setMaxLength(100)
        price = QDoubleSpinBox()
        price.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        price.setLocale(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
        price.setRange(.01,float(MAX))
        price.setDecimals(2)
        price.setValue(float(p['price']) if p else 50)
        category = QComboBox()
        category.setEditable(True)
        category.addItems(self.categories)
        if p:
            category.setCurrentText(p['category'])
        description = QLineEdit(p['description'] if p else '')
        description.setMaxLength(500)
        available = QCheckBox('เปิดขาย')
        available.setChecked(bool(p['is_available']) if p else True)
        for caption,w in (('ชื่อ',name),('ราคา (บาท)',price),('หมวด',category),('รายละเอียด',description),('สถานะ',available)):
            f.addRow(caption,w)
        b.addLayout(f)
        b.addWidget(lab('ชื่อและราคาของออเดอร์เดิมจะไม่เปลี่ยนตามการแก้เมนู','muted'))
        def save():
            data = (p['product_id'] if p else None,name.text(),category.currentText(),price.value(),available.isChecked(),description.text())
            if not data[1].strip() or not data[2].strip():
                self.message('กรอกชื่อและหมวด')
                return
            d.accept()
            self.run(
                lambda:self.db.menu_save(*data),
                lambda _:self.refresh_all(),
                lambda message:self.message('บันทึกเมนูไม่สำเร็จ\n'+message),
            )
        b.addWidget(button('บันทึก',save,True))
        b.addWidget(button('ยกเลิก',d.reject))
        d.exec()

    def toggle_menu(self):
        p = self.selected_menu()
        if p and not self.busy:
            self.run(lambda:self.db.menu_save(p['product_id'],p['product_name'],p['category'],p['price'],not p['is_available'],p['description']),lambda _:self.refresh_all())

    def delete_menu(self):
        p = self.selected_menu()
        if p and not self.busy and self.ask('ลบเมนู',p['product_name']+'\nซ่อนจากหน้าขาย แต่คงข้อมูลและประวัติเดิมไว้'):
            self.run(lambda:self.db.menu_delete(p['product_id']),lambda _:self.refresh_all())

    def manage_categories(self):
        if self.busy:
            return
        options = ['เพิ่มหมวด','เปลี่ยนชื่อหมวด','ลบหมวด']
        action,ok = QInputDialog.getItem(self,'จัดการหมวด','การทำงาน',options,0,False)
        if not ok:
            return
        old = None
        if action!='เพิ่มหมวด':
            cats = self.categories
            if not cats:
                return
            old,ok = QInputDialog.getItem(self,'หมวดเดิม','เลือกหมวด',cats,0,False)
            if not ok:
                return
        new = None
        if action!='ลบหมวด':
            new,ok = QInputDialog.getText(self,'ชื่อหมวด','ชื่อใหม่')
            new = new.strip()[:100]
            if not ok or not new:
                return
        if self.ask('ยืนยันจัดการหมวด',action+'\n'+str(old or '')+' → '+str(new or 'ลบ')):
            self.run(
                lambda:self.db.category(old,new),
                lambda _:self.refresh_all(),
                lambda message:self.message('จัดการหมวดไม่สำเร็จ\n'+message),
            )

    def closeEvent(self,event):
        if self.busy or any(j.isRunning() for j in self.jobs):
            self.message('รอให้คำขอทำงานเสร็จก่อนปิดโปรแกรม')
            event.ignore()
            return
        self.timer.stop()
        self.poll.stop()
        self.worker.stop()
        event.accept()


if __name__=='__main__':
    QLocale.setDefault(QLocale(QLocale.Language.English,QLocale.Country.UnitedStates))
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = StallPOSApp()
    window.showMaximized()
    sys.exit(app.exec())
