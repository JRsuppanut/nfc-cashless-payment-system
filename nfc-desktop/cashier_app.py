import sys
from typing import Optional
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
    QSplitter,
    QMessageBox
)
import database
from nfc_worker import NFCWorker

DEFAULT_PORT = "COM4"

CASHIER_STYLE = """
QMainWindow { 
    background-color: #0F172A; 
}
QWidget { 
    color: #F8FAFC; 
    font-family: "Segoe UI", sans-serif; 
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
QPushButton#actionBtn {
    background-color: #059669;
    border: 1px solid #10B981;
    color: #FFFFFF;
    font-size: 13px;
    font-weight: bold;
    min-height: 36px;
    border-radius: 6px;
}
QPushButton#actionBtn:hover {
    background-color: #10B981;
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
    """Bridge for cross-thread event marshaling."""
    tag_detected = pyqtSignal(str, bool, object, str)
    tag_removed = pyqtSignal()

    def emit_tag(self, uid: str, is_valid: bool, token_uuid: Optional[str], status: str) -> None:
        self.tag_detected.emit(uid, is_valid, token_uuid, status)

    def emit_removal(self) -> None:
        self.tag_removed.emit()


class CashierApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cashier Terminal - Food Court Cashless System")
        self.resize(1100, 700)
        self.setMinimumSize(920, 600)

        database.initialize_database()

        self._active_uid: Optional[str] = None
        self._active_token_uuid: Optional[str] = None
        self._is_card_authenticated: bool = False

        self.nfc_bridge = NFCBridge()
        self.nfc_bridge.tag_detected.connect(self._handle_card_detected)
        self.nfc_bridge.tag_removed.connect(self._handle_card_removed)

        self._init_ui()
        self._refresh_ledger()

        self.nfc_worker = NFCWorker(
            port=DEFAULT_PORT,
            on_tag_detected=self.nfc_bridge.emit_tag,
            on_tag_removed=self.nfc_bridge.emit_removal
        )
        self.nfc_worker.start()

    def _init_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # Header bar
        header_layout = QHBoxLayout()
        title_label = QLabel("CASHIER DESK TERMINAL")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #F8FAFC; letter-spacing: 1px;")

        badge_role = QLabel("ROLE: CASHIER / ISSUANCE")
        badge_role.setStyleSheet(
            "background-color: #065F46; color: #34D399; font-weight: bold; "
            "padding: 5px 12px; border-radius: 4px; font-size: 11px;"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(badge_role)
        main_layout.addLayout(header_layout)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)

        # Left Column: Controls & Card Operations
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(14)

        # Mode Selection
        mode_group = QGroupBox("OPERATION MODE")
        mode_layout = QVBoxLayout(mode_group)
        self.mode_group = QButtonGroup(self)
        self.radio_topup = QRadioButton("Top-Up Balance (Tap to Deposit)")
        self.radio_check = QRadioButton("Check Balance Only")
        self.radio_topup.setChecked(True)
        self.mode_group.addButton(self.radio_topup, 1)
        self.mode_group.addButton(self.radio_check, 2)
        mode_layout.addWidget(self.radio_topup)
        mode_layout.addWidget(self.radio_check)
        left_layout.addWidget(mode_group)

        # Parameters
        param_group = QGroupBox("DEPOSIT PARAMETERS")
        param_layout = QVBoxLayout(param_group)
        input_layout = QHBoxLayout()
        amt_label = QLabel("Amount (THB):")
        amt_label.setStyleSheet("font-weight: 600; color: #CBD5E1;")
        self.amount_input = QLineEdit("100")
        self.amount_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        input_layout.addWidget(amt_label)
        input_layout.addWidget(self.amount_input)
        param_layout.addLayout(input_layout)

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

        # Token Readout & Provisioning
        status_group = QGroupBox("AUTHENTICATED CARD READOUT")
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(8)

        uid_container = QHBoxLayout()
        uid_title = QLabel("UID:")
        uid_title.setStyleSheet("color: #64748B; font-weight: bold;")
        self.uid_display = QLabel("--:--:--:--:--:--:--")
        self.uid_display.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self.uid_display.setStyleSheet("color: #34D399;")
        uid_container.addWidget(uid_title)
        uid_container.addWidget(self.uid_display)
        uid_container.addStretch()
        status_layout.addLayout(uid_container)

        token_container = QHBoxLayout()
        token_title = QLabel("Token:")
        token_title.setStyleSheet("color: #64748B; font-weight: bold;")
        self.token_display = QLabel("No Authenticated Token")
        self.token_display.setFont(QFont("Consolas", 11))
        self.token_display.setStyleSheet("color: #94A3B8;")
        token_container.addWidget(token_title)
        token_container.addWidget(self.token_display)
        token_container.addStretch()
        status_layout.addLayout(token_container)

        self.status_box = QLabel("Ready. Place customer card on reader...")
        self.status_box.setWordWrap(True)
        self.status_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_box.setMinimumHeight(64)
        self.status_box.setStyleSheet(
            "background-color: #1E293B; border: 1px dashed #475569; "
            "border-radius: 6px; padding: 8px; color: #94A3B8;"
        )
        status_layout.addWidget(self.status_box)

        # Manual Card Provisioning Action
        self.btn_provision = QPushButton("Issue / Re-Provision Token to Card")
        self.btn_provision.setObjectName("actionBtn")
        self.btn_provision.clicked.connect(self._handle_provision_action)
        status_layout.addWidget(self.btn_provision)

        left_layout.addWidget(status_group)
        left_layout.addStretch()

        # Right Column: Recent Ledger Table
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(10)

        ledger_label = QLabel("RECENT CASHIER LEDGER ENTRIES")
        ledger_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        ledger_label.setStyleSheet("color: #94A3B8;")
        right_layout.addWidget(ledger_label)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID", "Card UID", "Token UUID", "Terminal", "Action", "Amount", "Balance"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        right_layout.addWidget(self.table)

        body_splitter.addWidget(left_panel)
        body_splitter.addWidget(right_panel)
        body_splitter.setStretchFactor(0, 4)
        body_splitter.setStretchFactor(1, 6)
        main_layout.addWidget(body_splitter)

    @pyqtSlot(str, bool, object, str)
    def _handle_card_detected(
        self, uid: str, is_valid: bool, token_uuid: Optional[str], status: str
    ) -> None:
        """Handle incoming card event verified by background worker."""
        self._active_uid = uid
        self._active_token_uuid = token_uuid
        self._is_card_authenticated = is_valid

        self.uid_display.setText(uid)
        self.token_display.setText(token_uuid[:18] + "..." if token_uuid else "None")

        selected_mode = self.mode_group.checkedId()

        # Handle unprovisioned or invalid cards
        if not is_valid:
            if status == "FOREIGN_OR_UNINITIALIZED_CARD":
                self._update_feedback(
                    f"Uninitialized Card Detected [{uid}].\nClick 'Issue / Re-Provision Token' below to activate.",
                    success=False
                )
            else:
                self._update_feedback(
                    f"SECURITY ALERT: Verification Failed ({status}).\nCounterfeit or damaged token rejected.",
                    success=False
                )
            return

        # Handle verified tokens
        if selected_mode == 2:  # Check Balance
            wallet = database.get_wallet_by_token(token_uuid)
            if wallet is None:
                self._update_feedback(
                    f"Token verified but no database record found.\nPlease re-provision card.",
                    success=False
                )
            else:
                self._update_feedback(
                    f"Card Verified: ACTIVE\nCurrent Balance: {wallet['balance']:.2f} THB",
                    success=True
                )

        elif selected_mode == 1:  # Top-Up
            try:
                amount = float(self.amount_input.text().strip())
                if amount <= 0:
                    raise ValueError
            except ValueError:
                self._update_feedback("Invalid top-up deposit amount entered.", success=False)
                return

            success, msg, balance = database.process_top_up(token_uuid, uid, amount)
            if success:
                self._update_feedback(
                    f"Top-Up Successful: +{amount:.2f} THB\nCurrent Balance: {balance:.2f} THB",
                    success=True
                )
            else:
                self._update_feedback(f"Top-Up Failed: {msg}", success=False)

        self._refresh_ledger()

    def _handle_provision_action(self) -> None:
        """Provision cryptographic token structure onto active card target."""
        if not self._active_uid:
            QMessageBox.warning(self, "Provisioning", "No card present on the reader.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Card Issuance",
            f"Write cryptographic token to card {self._active_uid}?\nExisting balance/data will be reset.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        success, result = self.nfc_worker.provision_active_card()
        if success:
            token_uuid = result
            database.register_provisioned_card(token_uuid, self._active_uid)
            self._active_token_uuid = token_uuid
            self._is_card_authenticated = True
            self.token_display.setText(token_uuid[:18] + "...")
            self._update_feedback(
                f"Token Provisioned Successfully!\nToken UUID: {token_uuid[:8]}... | Balance: 0.00 THB",
                success=True
            )
            self._refresh_ledger()
        else:
            self._update_feedback(f"Provisioning Failed: {result}", success=False)

    @pyqtSlot()
    def _handle_card_removed(self) -> None:
        """Reset interface upon card removal."""
        self._active_uid = None
        self._active_token_uuid = None
        self._is_card_authenticated = False

        self.uid_display.setText("--:--:--:--:--:--:--")
        self.token_display.setText("No Authenticated Token")
        self.status_box.setText("Card removed. Ready for next transaction.")
        self.status_box.setStyleSheet(
            "background-color: #1E293B; border: 1px dashed #475569; "
            "border-radius: 6px; padding: 8px; color: #94A3B8;"
        )

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
            uid_item.setFont(QFont("Consolas", 10))
            uid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            token_item = QTableWidgetItem(str(row["token_uuid"])[:8] + "...")
            token_item.setFont(QFont("Consolas", 10))
            token_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            term_item = QTableWidgetItem(str(row["terminal_type"]))
            term_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            action_item = QTableWidgetItem(str(row["action_type"]))
            action_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            action_item.setForeground(QColor("#34D399") if row["action_type"] == "TOP_UP" else QColor("#F87171"))

            amt_item = QTableWidgetItem(f"{row['amount']:.2f}")
            amt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            bal_item = QTableWidgetItem(f"{row['balance_after']:.2f}")
            bal_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row_idx, 0, id_item)
            self.table.setItem(row_idx, 1, uid_item)
            self.table.setItem(row_idx, 2, token_item)
            self.table.setItem(row_idx, 3, term_item)
            self.table.setItem(row_idx, 4, action_item)
            self.table.setItem(row_idx, 5, amt_item)
            self.table.setItem(row_idx, 6, bal_item)

    def closeEvent(self, event) -> None:
        if hasattr(self, "nfc_worker") and self.nfc_worker is not None:
            self.nfc_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(CASHIER_STYLE)
    window = CashierApp()
    window.show()
    sys.exit(app.exec())