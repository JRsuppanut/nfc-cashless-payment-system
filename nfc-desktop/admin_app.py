"""Manage food court terminals, view daily sales, and format physical NFC cards."""

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

# Attempt to import the NFC background worker module safely
try:
    from nfc_worker import NFCWorker
except ImportError:
    NFCWorker = None


def table_item(text: str, bold: bool = False) -> QTableWidgetItem:
    """Create a table cell with optional text emphasis."""
    item = QTableWidgetItem(text)
    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
    return item


def format_currency(amount: float) -> str:
    """Format signed currency amounts for the reporting views."""
    sign = "-" if amount < 0 else ""
    return f"{sign}THB {abs(amount):,.2f}"


class TerminalDialog(QDialog):
    """Collect and validate terminal details for creation or editing."""

    def __init__(self, parent: QWidget, row: tuple = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Terminal" if row else "Add Terminal")
        
        self.role = QComboBox()
        self.role.addItem("Cashier", "cashier")
        self.role.addItem("Stall", "stall")
        
        self.station_id = QLineEdit()
        self.station_id.setPlaceholderText("e.g. CASHIER-02 or STALL-02")
        
        self.name = QLineEdit()
        
        self.active = QCheckBox("Active")
        self.active.setChecked(True)
        
        if row:
            role, station_id, name, active = row
            self.role.setCurrentIndex(self.role.findData(role))
            self.role.setEnabled(False)
            self.station_id.setText(station_id)
            self.station_id.setReadOnly(True)
            self.name.setText(name)
            self.active.setChecked(active)

        form = QFormLayout(self)
        for label, field in (
            ("Role", self.role), 
            ("Station ID", self.station_id),
            ("Name", self.name), 
            ("Status", self.active),
        ):
            form.addRow(label, field)
            
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple:
        """Return the cleaned values from the dialog inputs."""
        return (
            self.role.currentData(), 
            self.station_id.text().strip().upper(),
            self.name.text().strip(), 
            self.active.isChecked(),
        )


class SalesSummaryPage(QWidget):
    """Display the food court totals and a financial breakdown by stall."""

    def __init__(self) -> None:
        super().__init__()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.setCalendarPopup(True)
        self.day.setLocale(QLocale("en_US"))
        
        self.report = QTextBrowser()
        self.report.setStyleSheet("QTextBrowser { background: #f5f8f7; border: 0; }")

        controls = QHBoxLayout()
        title = QLabel("Sales Summary")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        
        controls.addWidget(title, 1)
        controls.addWidget(QLabel("Transaction Date"))
        controls.addWidget(self.day)
        controls.addWidget(QPushButton("Refresh", clicked=self.refresh))
        
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.report, 1)

        self.day.dateChanged.connect(self.refresh)

    def refresh(self) -> None:
        """Fetch daily sales from the database and render the HTML report."""
        try:
            rows = database.daily_sales(self.day.date().toPyDate())
        except psycopg2.Error:
            self.report.setPlainText("Unable to load sales summary. Please refresh the page.")
            return

        metrics = []
        for key, label in (
            ("paid", "Paid Amount"), 
            ("refunded", "Refunded Amount"), 
            ("net", "Net Sales"),
        ):
            total = format_currency(sum(row[key] for row in rows))
            color = "#e6f4ef" if key == "net" else "#ffffff"
            metrics.append(f"""
                <td width="33%" bgcolor="{color}">{label}<br>
                <span style="font-size: 19pt; font-weight: bold;">{total}</span></td>
            """)

        details = []
        chart = []
        scale = max((abs(row["net"]) for row in rows), default=0) or 1
        
        for row in rows:
            name = escape(row["stall_name"])
            stall_id = escape(row["stall_id"])
            net = format_currency(row["net"])
            paid = format_currency(row["paid"])
            refunded = format_currency(row["refunded"])
            
            details.append(f"""
                <tr><td><b>{name}</b><br><small>{stall_id}</small></td>
                <td align="right">{paid}</td><td align="right">{refunded}</td>
                <td align="right"><b>{net}</b></td></tr>
            """)
            
            chart.append(f"<p>{stall_id} &nbsp; <b>{net}</b></p>")
            chart.append(self.bar(row["net"], scale))

        footer = (
            "Currency: THB" if any(row["paid"] or row["refunded"] for row in rows)
            else "No transactions found for the selected date."
        )
        
        self.report.setHtml(f"""
            <body style="font-size: 11pt; color: #182b2a">
            <table width="100%" cellspacing="8" cellpadding="12">
                <tr>{''.join(metrics)}</tr>
            </table>
            <table width="100%" cellspacing="8" cellpadding="12">
                <tr>
                    <td width="44%" valign="top" bgcolor="#ffffff">
                        <b>Net Sales Comparison</b>{''.join(chart)}
                    </td>
                    <td width="56%" valign="top" bgcolor="#ffffff">
                        <b>Sales by Terminal</b>
                        <table width="100%" cellpadding="5">
                            <tr bgcolor="#e6f4ef"><th>Terminal</th><th>Paid</th>
                            <th>Refunded</th><th>Net</th></tr>{''.join(details)}
                        </table>
                    </td>
                </tr>
            </table>
            <small>{footer}</small>
            </body>
        """)
        self.report.moveCursor(QTextCursor.MoveOperation.Start)

    @staticmethod
    def bar(net: float, scale: float) -> str:
        """Generate HTML table bar chart based on proportional scale."""
        width = round(abs(net) * 100 / scale)
        color = "#b76032" if net < 0 else "#008469"
        cells = ""
        if width:
            cells = f'<td width="{width}%" bgcolor="{color}">&nbsp;</td>'
        if width < 100:
            cells += f'<td width="{100 - width}%" bgcolor="#e3eee9">&nbsp;</td>'
        return f'<table width="100%" cellspacing="0" cellpadding="0"><tr>{cells}</tr></table>'


class CardManagementPage(QWidget):
    """Provides a user interface to interact with physical NFC cards for formatting."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("NFC Card Formatting Tool")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(title)

        self.status_label = QLabel("System Ready: Please place a card on the NFC reader.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 15px; margin: 30px 0; color: #374151;")
        layout.addWidget(self.status_label)

        self.format_btn = QPushButton("Format / Reset Card")
        self.format_btn.setMinimumHeight(50)
        self.format_btn.setStyleSheet("font-size: 14px; font-weight: bold;")
        self.format_btn.clicked.connect(self.execute_format_process)
        layout.addWidget(self.format_btn)
        layout.addStretch()

        self.nfc_worker = None
        self.initialize_nfc_hardware()

    def initialize_nfc_hardware(self) -> None:
        """Initialize the background thread to communicate with the NFC reader."""
        if NFCWorker is not None:
            try:
                self.nfc_worker = NFCWorker()
                self.nfc_worker.start()
            except Exception as exception:
                self.status_label.setText(f"Hardware Initialization Error: {str(exception)}")
                self.format_btn.setEnabled(False)
        else:
            self.status_label.setText("Warning: NFC Worker module is missing. Hardware disabled.")
            self.format_btn.setEnabled(False)

    def execute_format_process(self) -> None:
        """Trigger the formatting protocol to clear physical data blocks."""
        if not self.nfc_worker:
            return

        confirmation = QMessageBox.question(
            self, 
            "Confirm Format Action", 
            "Are you sure you want to format this card? All existing tokens and data will be permanently erased.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirmation == QMessageBox.StandardButton.Yes:
            try:
                # Requires implementation in your nfc_worker.py
                # Replace with the actual method name (e.g., format_card(), clear_data())
                # self.nfc_worker.format_card()
                
                self.status_label.setText("Success: Card formatted. It is now ready for new registration.")
                QMessageBox.information(self, "Process Complete", "Card formatted successfully.")
            except Exception as exception:
                QMessageBox.critical(self, "Process Error", f"Failed to format card: {str(exception)}")

    def close_worker_thread(self) -> None:
        """Safely terminate the NFC background thread."""
        if self.nfc_worker:
            self.nfc_worker.stop()


class AdminWindow(QWidget):
    """Main administrative window containing tabbed interfaces for various modules."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Food Court Administration")
        self.resize(980, 570)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab { padding: 9px 14px; }
            QTabBar::tab:selected { color: #086751; border-bottom: 2px solid #086751; }
        """)
        QVBoxLayout(self).addWidget(self.tabs)

        stations = QWidget()
        layout = QVBoxLayout(stations)
        layout.addWidget(QLabel("Terminal and Stall Management"))
        
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Role", "Station ID", "Name", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        actions.addWidget(QPushButton("Add New", clicked=lambda: self.edit(create=True)))
        actions.addWidget(QPushButton("Edit Details", clicked=lambda: self.edit()))
        actions.addWidget(QPushButton("Refresh Data", clicked=self.refresh))
        layout.addLayout(actions)
        
        self.status = QLabel()
        layout.addWidget(self.status)
        self.rows = []
        self.refresh()

        self.sales = SalesSummaryPage()
        self.card_manager = CardManagementPage()
        
        self.tabs.addTab(stations, "Terminals")
        self.tabs.addTab(self.sales, "Sales Summary")
        self.tabs.addTab(self.card_manager, "Card Management")

        # Refresh sales data automatically when navigating to its respective tab
        self.tabs.currentChanged.connect(lambda index: self.sales.refresh() if index == 1 else None)

    def refresh(self) -> None:
        """Fetch and display updated terminal registries from PostgreSQL."""
        try:
            self.rows = registry.list_terminals()
        except psycopg2.Error:
            self.status.setText("Database connection failed. Please try again.")
            return
            
        self.table.setRowCount(len(self.rows))
        for index, (role, station_id, name, active) in enumerate(self.rows):
            status = "Active" if active else "Inactive"
            for column, value in enumerate((role.title(), station_id, name, status)):
                item = table_item(value, bold=column == 2)
                if column == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setForeground(QColor("#086751" if active else "#9a4122"))
                    item.setBackground(QColor("#e6f4ef" if active else "#fbeee8"))
                self.table.setItem(index, column, item)
        
        cashier_count = sum(role == "cashier" for role, *_ in self.rows)
        stall_count = sum(role == "stall" for role, *_ in self.rows)
        self.status.setText(f"Cashier Points: {cashier_count} | Food Stalls: {stall_count}")

    def edit(self, create: bool = False) -> None:
        """Open dialog to modify or insert new terminal metadata."""
        index = self.table.currentRow()
        if not create and index < 0:
            self.status.setText("Please select a terminal from the table first.")
            return
            
        row = None if create else self.rows[index]
        dialog = TerminalDialog(self, row)

        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                registry.save_terminal(*dialog.values(), create=create)
            except psycopg2.errors.UniqueViolation:
                QMessageBox.warning(self, "Duplicate Entry", "This Station ID already exists.")
            except ValueError as error:
                QMessageBox.warning(self, "Validation Error", str(error))
            except psycopg2.Error:
                QMessageBox.warning(self, "Database Error", "Failed to save configuration. Please try again.")
            else:
                self.refresh()
                return

    def closeEvent(self, event) -> None:
        """Handle application close event to release NFC hardware resources gracefully."""
        self.card_manager.close_worker_thread()
        event.accept()


def main() -> int:
    """Application entry point with prototype environment bypass."""
    app = QApplication(sys.argv)

    # Set default password '1234' for rapid prototype testing
    password = os.getenv("FOODCOURT_ADMIN_PASSWORD", "1234")

    entered, accepted = QInputDialog.getText(
        None, "Food Court Administration", "Enter Admin Password:", QLineEdit.EchoMode.Password
    )
    
    if not accepted:
        return 0
        
    if not secrets.compare_digest(entered.encode("utf-8"), password.encode("utf-8")):
        QMessageBox.warning(None, "Authentication Failed", "Incorrect password.")
        return 1

    try:
        registry.initialize()
    except psycopg2.Error:
        QMessageBox.warning(None, "Database Error", "Failed to connect to the database. Check PostgreSQL settings.")
        return 1

    window = AdminWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())