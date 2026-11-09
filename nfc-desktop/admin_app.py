"""Manage food court terminals and view daily sales."""

import os
import secrets
import sys
from html import escape

import psycopg2
from PyQt6.QtCore import QDate, QLocale, Qt
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QFormLayout, QHeaderView, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTextBrowser,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

import database
import terminal_registry as registry


def table_item(text, bold=False):
    """Create a table cell with optional emphasis."""
    item = QTableWidgetItem(text)
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    return item


def baht(amount):
    """Format signed baht amounts for the report."""
    sign = "−" if amount < 0 else ""
    return f"{sign}฿{abs(amount):,.2f}"


class TerminalDialog(QDialog):
    """Collect terminal details for creation or editing."""

    def __init__(self, parent, row=None):
        super().__init__(parent)
        self.setWindowTitle("แก้ไขข้อมูล" if row else "เพิ่มจุดหรือร้าน")
        self.role = QComboBox()
        self.role.addItem("Cashier", "cashier")
        self.role.addItem("Stall", "stall")
        self.station_id = QLineEdit()
        self.station_id.setPlaceholderText("CASHIER-02 หรือ STALL-02")
        self.name = QLineEdit()
        self.active = QCheckBox("เปิดใช้งาน")
        self.active.setChecked(True)
        if row:
            # Keep existing terminal IDs and roles stable when editing.
            role, station_id, name, active = row
            self.role.setCurrentIndex(self.role.findData(role))
            self.role.setEnabled(False)
            self.station_id.setText(station_id)
            self.station_id.setReadOnly(True)
            self.name.setText(name)
            self.active.setChecked(active)

        form = QFormLayout(self)
        for label, field in (
            ("ประเภท", self.role), ("รหัส", self.station_id),
            ("ชื่อ", self.name), ("สถานะ", self.active),
        ):
            form.addRow(label, field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return (
            self.role.currentData(), self.station_id.text().strip().upper(),
            self.name.text().strip(), self.active.isChecked(),
        )


class SalesSummaryPage(QWidget):
    """Display the food court totals and a breakdown by stall."""

    def __init__(self):
        super().__init__()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.setCalendarPopup(True)
        
        # Use Arabic digits while keeping the calendar in Thai.
        self.day.setLocale(QLocale("th_TH"))
        
        self.report = QTextBrowser()
        self.report.setStyleSheet("QTextBrowser { background: #f5f8f7; border: 0; }")

        controls = QHBoxLayout()
        title = QLabel("สรุปยอดขาย")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        controls.addWidget(title, 1)
        controls.addWidget(QLabel("วันที่ทำรายการ"))
        controls.addWidget(self.day)
        controls.addWidget(QPushButton("รีเฟรช", clicked=self.refresh))
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.report, 1)

        # Reload totals whenever the selected transaction date changes.
        self.day.dateChanged.connect(self.refresh)

    def refresh(self):
        # Admin and Stall use the same PostgreSQL totals.
        try:
            rows = database.daily_sales(self.day.date().toPyDate())
        except psycopg2.Error:
            # Replace stale figures with an error message if the query fails.
            self.report.setPlainText("โหลดสรุปยอดขายไม่ได้ กรุณากดรีเฟรช")
            return

        # Sum each metric across all stalls for the three headline figures.
        metrics = []
        for key, label in (
            ("paid", "ยอดชำระค่าอาหาร"), ("refunded", "ยอดคืนค่าอาหาร"), ("net", "ยอดขายสุทธิ"),
        ):
            total = baht(sum(row[key] for row in rows))
            color = "#e6f4ef" if key == "net" else "#ffffff"
            metrics.append(f"""
                <td width="33%" bgcolor="{color}">{label}<br>
                <span style="font-size: 19pt; font-weight: bold;">{total}</span></td>
            """)

        details = []
        chart = []
        scale = max((abs(row["net"]) for row in rows), default=0) or 1
        for row in rows:
            # Escape user-entered stall names before rendering the report.
            name = escape(row["stall_name"])
            stall_id = escape(row["stall_id"])
            net = baht(row["net"])
            paid = baht(row["paid"])
            refunded = baht(row["refunded"])
            details.append(f"""
                <tr><td><b>{name}</b><br><small>{stall_id}</small></td>
                <td align="right">{paid}</td><td align="right">{refunded}</td>
                <td align="right"><b>{net}</b></td></tr>
            """)
            chart.append(f"<p>{stall_id} &nbsp; <b>{net}</b></p>")
            chart.append(self.bar(row["net"], scale))

        # Render the chart and table together in one Qt document.
        footer = (
            "หน่วยเงินบาท" if any(row["paid"] or row["refunded"] for row in rows)
            else "ไม่มีรายการชำระหรือคืนค่าอาหารในวันที่เลือก"
        )
        self.report.setHtml(f"""
            <body style="font-size: 11pt; color: #182b2a">
            <table width="100%" cellspacing="8" cellpadding="12">
                <tr>{''.join(metrics)}</tr>
            </table>
            <table width="100%" cellspacing="8" cellpadding="12">
                <tr>
                    <td width="44%" valign="top" bgcolor="#ffffff">
                        <b>เปรียบเทียบยอดขายสุทธิ</b>{''.join(chart)}
                    </td>
                    <td width="56%" valign="top" bgcolor="#ffffff">
                        <b>ยอดขายรายร้าน</b>
                        <table width="100%" cellpadding="5">
                            <tr bgcolor="#e6f4ef"><th>ร้าน</th><th>ชำระ</th>
                            <th>คืนค่าอาหาร</th><th>สุทธิ</th></tr>{''.join(details)}
                        </table>
                    </td>
                </tr>
            </table>
            <small>{footer}</small>
            </body>
        """)
        self.report.moveCursor(QTextCursor.MoveOperation.Start)

    @staticmethod
    def bar(net, scale):
        # Use one scale for all stalls and label the actual signed amount above.
        width = round(abs(net) * 100 / scale)
        color = "#b76032" if net < 0 else "#008469"
        cells = ""
        if width:
            cells = f'<td width="{width}%" bgcolor="{color}">&nbsp;</td>'
        if width < 100:
            cells += f'<td width="{100 - width}%" bgcolor="#e3eee9">&nbsp;</td>'
        return f'<table width="100%" cellspacing="0" cellpadding="0"><tr>{cells}</tr></table>'


class AdminWindow(QWidget):
    """Show the terminal registry and sales report in separate tabs."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Food Court Admin")
        self.resize(980, 570)
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabBar::tab { padding: 9px 14px; }
            QTabBar::tab:selected { color: #086751; border-bottom: 2px solid #086751; }
        """)
        QVBoxLayout(self).addWidget(tabs)

        stations = QWidget()
        layout = QVBoxLayout(stations)
        layout.addWidget(QLabel("จัดการจุดบริการและร้านอาหาร"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ประเภท", "รหัส", "ชื่อ", "สถานะ"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addWidget(QPushButton("เพิ่ม", clicked=lambda: self.edit(create=True)))
        actions.addWidget(QPushButton("แก้ไข", clicked=lambda: self.edit()))
        actions.addWidget(QPushButton("รีเฟรช", clicked=self.refresh))
        layout.addLayout(actions)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.rows = []
        self.refresh()

        self.sales = SalesSummaryPage()
        tabs.addTab(stations, "จุดบริการและร้านค้า")
        tabs.addTab(self.sales, "สรุปยอดขาย")

        # Load sales when the report tab is opened.
        tabs.currentChanged.connect(lambda index: self.sales.refresh() if index == 1 else None)

    def refresh(self):
        try:
            self.rows = registry.list_terminals()
        except psycopg2.Error:
            self.status.setText("เชื่อมฐานข้อมูลไม่ได้ กรุณาลองใหม่")
            return
        self.table.setRowCount(len(self.rows))
        for index, (role, station_id, name, active) in enumerate(self.rows):
            status = "เปิดใช้งาน" if active else "ปิดใช้งาน"
            for column, value in enumerate((role.title(), station_id, name, status)):
                item = table_item(value, bold=column == 2)
                if column == 3:
                    # Pair the status color with text so both states are clear.
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QColor("#086751" if active else "#9a4122"))
                    item.setBackground(QColor("#e6f4ef" if active else "#fbeee8"))
                self.table.setItem(index, column, item)
        
        cashier_count = sum(role == "cashier" for role, *_ in self.rows)
        stall_count = sum(role == "stall" for role, *_ in self.rows)
        self.status.setText(f"แคชเชียร์ {cashier_count} จุด • ร้านอาหาร {stall_count} ร้าน")

    def edit(self, create=False):
        index = self.table.currentRow()
        if not create and index < 0:
            self.status.setText("เลือกจุดหรือร้านจากตารางก่อน")
            return
        row = None if create else self.rows[index]
        dialog = TerminalDialog(self, row)

        # Keep the form available after a validation or save error.
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                registry.save_terminal(*dialog.values(), create=create)
            except psycopg2.errors.UniqueViolation:
                QMessageBox.warning(self, "รหัสซ้ำ", "รหัสนี้มีอยู่แล้ว")
            except ValueError as error:
                QMessageBox.warning(self, "ตรวจสอบข้อมูล", str(error))
            except psycopg2.Error:
                QMessageBox.warning(self, "ฐานข้อมูล", "บันทึกไม่ได้ กรุณาลองใหม่")
            else:
                self.refresh()
                return


def main():
    app = QApplication(sys.argv)

    # Read the administrator password from the launch environment.
    password = os.getenv("FOODCOURT_ADMIN_PASSWORD", "")
    if not password:
        QMessageBox.warning(None, "Food Court Admin", "ตั้ง FOODCOURT_ADMIN_PASSWORD ก่อนเปิด Admin")
        return 1

    entered, accepted = QInputDialog.getText(
        None, "Food Court Admin", "รหัสผ่านผู้ดูแล", QLineEdit.EchoMode.Password
    )
    if not accepted:
        return 0
    if not secrets.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
        QMessageBox.warning(None, "Food Court Admin", "รหัสผ่านไม่ถูกต้อง")
        return 1

    # Initialize the registry after administrator sign-in succeeds.
    try:
        registry.initialize()
    except psycopg2.Error:
        QMessageBox.warning(None, "Food Court Admin", "เชื่อมฐานข้อมูลไม่ได้ กรุณาตรวจการตั้งค่า PostgreSQL")
        return 1

    window = AdminWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())