import sys
from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QGroupBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter
)
import database
from nfc_worker import NFCWorker

DEFAULT_PORT = "COM4"

CASHIER_STYLE_SHEET = """
QMainWindow {
    background-color: #0F172A;
}

QWidget {
    color: #F8FAFC;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 24px;
    font-weight: bold;
    font-size: 13px;
    color: #94A3B8;
    padding-top: 16px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}

QRadioButton {
    spacing: 8px;
    font-weight: 500;
    color: #E2E8F0;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #64748B;
    background-color: transparent;
}

QRadioButton::indicator:checked {
    border: 2px solid #10B981;
    background-color: #10B981;
}

QLineEdit {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 8px 12px;
    color: #FFFFFF;
    font-size: 16px;
    font-weight: bold;
}

QLineEdit:focus {
    border: 1px solid #10B981;
}

QPushButton#presetBtn {
    background-color: #1E293B;
    border: 1px solid #475569;
    color: #34D399;
    font-size: 14px;
    font-weight: bold;
    min-height: 34px;
    border-radius: 6px;
}

QPushButton#presetBtn:hover {
    background-color: #059669;
    color: #FFFFFF;
    border-color: #059669;
}

QPushButton#presetBtn:pressed {
    background-color: #047857;
}

QTableWidget {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #334155;
    selection-background-color: #334155;
    selection-color: #FFFFFF;
}

QHeaderView::section {
    background-color: #0F172A;
    color: #94A3B8;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #334155;
    font-weight: 600;
}
"""


class NFCBridge(QObject):
    """Signal bridge between NFC background worker thread and Qt GUI thread."""
    tag_detected = pyqtSignal(str)

    def emit_tag(self, uid: str) -> None:
        self.tag_detected.emit(uid)


class CashierApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cashier Terminal - Food Court Cashless System")
        self.resize(1020, 660)
        self.setMinimumSize(880, 580)

        database.initialize_database()

        self.nfc_bridge = NFCBridge()
        self.nfc_bridge.tag_detected.connect(self._handle_card_transaction)

        self._init_ui()
        self._refresh_ledger()

        self.nfc_worker = NFCWorker(
            port=DEFAULT_PORT,
            on_tag_detected=self.nfc_bridge.emit_tag
        )
        self.nfc_worker.start()

    def _init_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Header Bar
        header_layout = QHBoxLayout()
        title_label = QLabel("CASHIER DESK TERMINAL")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #F8FAFC; letter-spacing: 1px;")

        self.badge_role = QLabel("ROLE: CASHIER / ISSUANCE")
        self.badge_role.setStyleSheet(
            "background-color: #065F46; color: #34D399; font-weight: bold; "
            "padding: 5px 12px; border-radius: 4px; font-size: 11px;"
        )

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.badge_role)
        main_layout.addLayout(header_layout)

        # Splitter Layout
        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)

        # Left Panel: Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)

        # Mode Selection
        mode_group = QGroupBox("CASHIER OPERATION MODE")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setSpacing(10)

        self.mode_group = QButtonGroup(self)
        self.radio_topup = QRadioButton("Top-Up Balance")
        self.radio_check = QRadioButton("Check Balance / Register Card")

        self.radio_topup.setChecked(True)
        self.mode_group.addButton(self.radio_topup, 1)
        self.mode_group.addButton(self.radio_check, 2)

        mode_layout.addWidget(self.radio_topup)
        mode_layout.addWidget(self.radio_check)
        left_layout.addWidget(mode_group)

        # Top-Up Parameter Input
        param_group = QGroupBox("DEPOSIT PARAMETERS")
        param_layout = QVBoxLayout(param_group)
        param_layout.setSpacing(10)

        input_layout = QHBoxLayout()
        amt_label = QLabel("Deposit Amount (THB):")
        amt_label.setStyleSheet("font-weight: 600; color: #CBD5E1;")
        self.amount_input = QLineEdit("100")
        self.amount_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        input_layout.addWidget(amt_label)
        input_layout.addWidget(self.amount_input)
        param_layout.addLayout(input_layout)

        # Quick Cash Buttons
        presets_layout = QGridLayout()
        presets_layout.setSpacing(8)
        preset_values = ["50", "100", "200", "300", "500", "1000"]
        for idx, val in enumerate(preset_values):
            btn = QPushButton(f"+{val}")
            btn.setObjectName("presetBtn")
            btn.clicked.connect(lambda checked, v=val: self.amount_input.setText(v))
            presets_layout.addWidget(btn, idx // 3, idx % 3)
        param_layout.addLayout(presets_layout)
        left_layout.addWidget(param_group)

        # Card Status Container
        status_group = QGroupBox("CARD READOUT")
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(8)

        uid_container = QHBoxLayout()
        uid_title = QLabel("UID:")
        uid_title.setStyleSheet("color: #64748B; font-weight: bold;")
        self.uid_display = QLabel("--:--:--:--:--:--:--")
        self.uid_display.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.uid_display.setStyleSheet("color: #34D399;")
        uid_container.addWidget(uid_title)
        uid_container.addWidget(self.uid_display)
        uid_container.addStretch()
        status_layout.addLayout(uid_container)

        self.status_box = QLabel("Tap customer card to process...")
        self.status_box.setWordWrap(True)
        self.status_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_box.setMinimumHeight(64)
        self.status_box.setStyleSheet(
            "background-color: #1E293B; border: 1px dashed #475569; "
            "border-radius: 6px; padding: 8px; color: #94A3B8;"
        )
        status_layout.addWidget(self.status_box)
        left_layout.addWidget(status_group)
        left_layout.addStretch()

        # Right Panel: Audit Ledger
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(10)

        ledger_label = QLabel("CASHIER TRANSACTION LEDGER")
        ledger_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        ledger_label.setStyleSheet("color: #94A3B8;")
        right_layout.addWidget(ledger_label)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Card UID", "Action", "Amount", "Balance", "Timestamp"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        right_layout.addWidget(self.table)

        body_splitter.addWidget(left_panel)
        body_splitter.addWidget(right_panel)
        body_splitter.setStretchFactor(0, 4)
        body_splitter.setStretchFactor(1, 6)
        main_layout.addWidget(body_splitter)

    @pyqtSlot(str)
    def _handle_card_transaction(self, uid: str) -> None:
        self.uid_display.setText(uid)
        selected_mode = self.mode_group.checkedId()

        if selected_mode == 2:  # Check Balance / Register Card
            wallet = database.get_wallet(uid)
            if wallet is None:
                database.register_card_if_absent(uid)
                self._update_feedback("New card registered successfully.\nInitial Balance: 0.00 THB", success=True)
            else:
                self._update_feedback(f"Card Active.\nCurrent Balance: {wallet['balance']:.2f} THB", success=True)

        elif selected_mode == 1:  # Top-Up
            try:
                amount = float(self.amount_input.text().strip())
                if amount <= 0:
                    raise ValueError
            except ValueError:
                self._update_feedback("Invalid top-up amount entered.", success=False)
                return

            success, msg, balance = database.process_top_up(uid, amount)
            if success:
                self._update_feedback(f"Top-Up Successful: +{amount:.2f} THB\nCurrent Balance: {balance:.2f} THB", success=True)
            else:
                self._update_feedback(f"Top-Up Failed: {msg}", success=False)

        self._refresh_ledger()

    def _update_feedback(self, text: str, success: bool = True) -> None:
        self.status_box.setText(text)
        if success:
            self.status_box.setStyleSheet(
                "background-color: #064E3B; border: 1px solid #059669; "
                "border-radius: 6px; padding: 8px; color: #A7F3D0; font-weight: 500;"
            )
        else:
            self.status_box.setStyleSheet(
                "background-color: #7F1D1D; border: 1px solid #DC2626; "
                "border-radius: 6px; padding: 8px; color: #FECACA; font-weight: 500;"
            )

    def _refresh_ledger(self) -> None:
        records = database.get_recent_transactions(15)
        self.table.setRowCount(0)

        for row_idx, row in enumerate(records):
            self.table.insertRow(row_idx)

            id_item = QTableWidgetItem(str(row["transaction_id"]))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            uid_item = QTableWidgetItem(str(row["card_uid"]))
            uid_item.setFont(QFont("Consolas", 11))
            uid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            action = row["action_type"]
            action_item = QTableWidgetItem(action)
            action_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            action_item.setForeground(QColor("#34D399") if action == "TOP_UP" else QColor("#94A3B8"))

            amt_item = QTableWidgetItem(f"{row['amount']:.2f}")
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            bal_item = QTableWidgetItem(f"{row['balance_after']:.2f}")
            bal_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            time_item = QTableWidgetItem(str(row["timestamp"]))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table.setItem(row_idx, 0, id_item)
            self.table.setItem(row_idx, 1, uid_item)
            self.table.setItem(row_idx, 2, action_item)
            self.table.setItem(row_idx, 3, amt_item)
            self.table.setItem(row_idx, 4, bal_item)
            self.table.setItem(row_idx, 5, time_item)

    def closeEvent(self, event) -> None:
        if hasattr(self, "nfc_worker") and self.nfc_worker is not None:
            self.nfc_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(CASHIER_STYLE_SHEET)
    window = CashierApp()
    window.show()
    sys.exit(app.exec())