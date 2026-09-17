import sys
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import database
from nfc_worker import NFCWorker, DEFAULT_PORT


CASHIER_STYLE = """
QMainWindow,
QWidget#centralWidget {
    background-color: #F7F8F5;
}

QWidget {
    color: #14212B;
    font-family: "Segoe UI", sans-serif;
    font-size: 15px;
}

QFrame#headerFrame,
QFrame#panel {
    background-color: #FFFFFF;
    border: 1px solid #DDE5E0;
    border-radius: 14px;
}

QFrame#softPanel {
    background-color: #F3F8F5;
    border: 1px solid #DDE5E0;
    border-radius: 14px;
}

QLabel#appTitle {
    color: #10212C;
    font-size: 28px;
    font-weight: 800;
}

QLabel#pageTitle {
    color: #10212C;
    font-size: 29px;
    font-weight: 800;
}

QLabel#sectionTitle {
    color: #14212B;
    font-size: 19px;
    font-weight: 700;
}

QLabel#mutedText {
    color: #667682;
    font-size: 15px;
}

QLabel#largeStatus {
    color: #075E48;
    font-size: 27px;
    font-weight: 800;
}

QLabel#balanceValue {
    color: #087A58;
    font-size: 55px;
    font-weight: 800;
}

QLabel#readerStatus {
    background-color: #E9F7F0;
    border: 1px solid #BDE6D2;
    border-radius: 15px;
    color: #087A58;
    font-size: 15px;
    font-weight: 700;
    padding: 8px 14px;
}

QPushButton#navButton {
    background-color: #FFFFFF;
    border: 1px solid #D6DFDA;
    border-radius: 11px;
    color: #14212B;
    font-size: 16px;
    font-weight: 700;
    min-height: 66px;
    padding: 7px 12px;
}

QPushButton#navButton:hover {
    border-color: #0B8A65;
    background-color: #F2FAF6;
}

QPushButton#navButton[selected="true"] {
    background-color: #087A58;
    border-color: #087A58;
    color: #FFFFFF;
}

QPushButton#primaryButton {
    background-color: #087A58;
    border: 1px solid #087A58;
    border-radius: 9px;
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
    min-height: 50px;
    padding: 5px 16px;
}

QPushButton#primaryButton:hover {
    background-color: #0A936B;
}

QPushButton#primaryButton:disabled {
    background-color: #B9C7C1;
    border-color: #B9C7C1;
    color: #F5F7F6;
}

QPushButton#secondaryButton {
    background-color: #FFFFFF;
    border: 1px solid #C9D3CE;
    border-radius: 9px;
    color: #26343D;
    font-size: 16px;
    font-weight: 700;
    min-height: 50px;
    padding: 5px 16px;
}

QPushButton#secondaryButton:hover {
    background-color: #F1F5F3;
}

QPushButton#presetButton {
    background-color: #F6F8F7;
    border: 1px solid #D3DDD8;
    border-radius: 9px;
    color: #14212B;
    font-size: 20px;
    font-weight: 700;
    min-height: 54px;
}

QPushButton#presetButton:hover {
    background-color: #E5F5ED;
    border-color: #0B8A65;
    color: #087A58;
}

QLineEdit#amountInput {
    background-color: #FFFFFF;
    border: 2px solid #CBD7D1;
    border-radius: 10px;
    color: #10212C;
    font-size: 31px;
    font-weight: 800;
    min-height: 58px;
    padding: 5px 16px;
}

QLineEdit#amountInput:focus {
    border-color: #0B8A65;
}

QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F7F9F8;
    border: 1px solid #DDE5E0;
    border-radius: 8px;
    gridline-color: #E6EBE8;
    selection-background-color: #DDF2E8;
    selection-color: #14212B;
    font-size: 14px;
}

QHeaderView::section {
    background-color: #F0F3F1;
    color: #33434D;
    border: none;
    border-bottom: 1px solid #DDE5E0;
    font-size: 14px;
    font-weight: 700;
    padding: 11px 6px;
}

QMessageBox {
    background-color: #FFFFFF;
}

QMessageBox QLabel {
    color: #14212B;
    font-size: 15px;
}
"""


class NFCBridge(QObject):
    """Event bridge for NFC worker thread and UI thread"""

    tag_detected = pyqtSignal(str, bool, object, str)
    tag_removed = pyqtSignal()

    def emit_tag(
        self,
        uid: str,
        is_valid: bool,
        token_uuid: Optional[str],
        status: str,
    ) -> None:
        self.tag_detected.emit(
            uid,
            is_valid,
            token_uuid,
            status,
        )

    def emit_removal(self) -> None:
        self.tag_removed.emit()


class CashierApp(QMainWindow):
    MODE_ISSUE = 0
    MODE_TOP_UP = 1
    MODE_CHECK = 2
    MODE_RETURN = 3

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Food Court Cashier")
        self.resize(1480, 860)
        self.setMinimumSize(1120, 700)

        database.initialize_database()

        self._active_uid: Optional[str] = None
        self._active_token_uuid: Optional[str] = None
        self._is_card_authenticated = False
        self._last_card_status = ""
        self._current_mode = self.MODE_ISSUE

        self._pending_top_up_amount: Optional[float] = None
        self._pending_top_up_uid: Optional[str] = None
        self._pending_top_up_token: Optional[str] = None
        
        # State for transaction history filter
        self._ledger_filter_uid: Optional[str] = None

        self.nfc_bridge = NFCBridge()
        self.nfc_bridge.tag_detected.connect(self._handle_card_detected)
        self.nfc_bridge.tag_removed.connect(self._handle_card_removed)

        self._init_ui()
        self._refresh_ledger()

        # Port configuration is managed centrally by NFCWorker
        self.nfc_worker = NFCWorker(
            on_tag_detected=self.nfc_bridge.emit_tag,
            on_tag_removed=self.nfc_bridge.emit_removal,
        )
        self.nfc_worker.start()

        QTimer.singleShot(
            1200,
            self._update_reader_connection_state,
        )

    # =========================================================
    # UI CONSTRUCTION
    # =========================================================

    def _init_ui(self) -> None:
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(22, 18, 22, 20)
        main_layout.setSpacing(14)

        main_layout.addWidget(self._create_header())
        main_layout.addLayout(self._create_navigation())

        body_layout = QHBoxLayout()
        body_layout.setSpacing(16)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._create_issue_page())
        self.page_stack.addWidget(self._create_top_up_page())
        self.page_stack.addWidget(self._create_check_page())
        self.page_stack.addWidget(self._create_return_page())

        body_layout.addWidget(self.page_stack, 56)
        body_layout.addWidget(self._create_ledger_panel(), 44)

        main_layout.addLayout(body_layout, 1)
        self._switch_mode(self.MODE_ISSUE)

    def _create_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("headerFrame")

        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 10, 18, 10)

        title = QLabel("Food Court Cashier")
        title.setObjectName("appTitle")

        self.reader_status_label = QLabel(
            f"●  NFC Reader: {DEFAULT_PORT}"
        )
        self.reader_status_label.setObjectName("readerStatus")

        terminal_label = QLabel("CASHIER-01")
        terminal_label.setStyleSheet(
            "font-size: 16px;"
            "font-weight: 800;"
            "padding-left: 14px;"
        )

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.reader_status_label)
        layout.addWidget(terminal_label)

        return frame

    def _create_navigation(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(10)

        navigation_items = [
            "Set Up a New Card",
            "Add Money to Card",
            "Check Card Balance",
            "Return Card and Refund Balance",
        ]

        self.nav_buttons = []

        for index, text in enumerate(navigation_items):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)

            button.clicked.connect(
                lambda checked=False, mode=index: self._switch_mode(mode)
            )

            layout.addWidget(button, 1)
            self.nav_buttons.append(button)

        return layout

    @staticmethod
    def _create_panel(soft: bool = False) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("softPanel" if soft else "panel")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        return frame, layout

    @staticmethod
    def _create_page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("mutedText")
        subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)

        return page, layout

    # =========================================================
    # PAGE 1: SET UP CARD
    # =========================================================

    def _create_issue_page(self) -> QWidget:
        page, layout = self._create_page(
            "Set Up a New Card",
            "Place a new or returned NFC card on the reader, then confirm.",
        )

        card_panel, card_layout = self._create_panel(soft=True)

        self.issue_status_title = QLabel("Ready for a New Card")
        self.issue_status_title.setObjectName("largeStatus")

        self.issue_status_message = QLabel("Place the card on the NFC reader.")
        self.issue_status_message.setObjectName("mutedText")
        self.issue_status_message.setWordWrap(True)

        self.issue_uid = QLabel("UID: —")

        card_layout.addWidget(self.issue_status_title)
        card_layout.addWidget(self.issue_status_message)
        card_layout.addWidget(self.issue_uid)
        layout.addWidget(card_panel)

        data_panel, data_layout = self._create_panel()

        data_title = QLabel("Card and Database Information")
        data_title.setObjectName("sectionTitle")
        data_layout.addWidget(data_title)

        data_grid = QGridLayout()
        data_grid.setHorizontalSpacing(24)
        data_grid.setVerticalSpacing(9)

        data_rows = [
            ("On-card system marker", "FCTK"),
            ("On-card Token UUID", "Generated automatically"),
            ("On-card Authentication Code", "Generated using HMAC-SHA256"),
            ("Database starting balance", "฿0.00"),
        ]

        for row, (name, value) in enumerate(data_rows):
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: 700; color: #33434D;")

            value_label = QLabel(value)
            value_label.setObjectName("mutedText")

            data_grid.addWidget(name_label, row, 0)
            data_grid.addWidget(value_label, row, 1)

        data_grid.setColumnStretch(1, 1)
        data_layout.addLayout(data_grid)
        layout.addWidget(data_panel)

        self.btn_provision = QPushButton("Confirm and Set Up Card")
        self.btn_provision.setObjectName("primaryButton")
        self.btn_provision.setEnabled(False)
        self.btn_provision.clicked.connect(self._handle_provision_action)

        layout.addWidget(self.btn_provision)
        layout.addStretch()

        return page

    # =========================================================
    # PAGE 2: ADD MONEY
    # =========================================================

    def _create_top_up_page(self) -> QWidget:
        page, layout = self._create_page(
            "Add Money to Card",
            "Enter an amount or choose a common amount. Then tap the card and confirm the transaction.",
        )

        amount_panel, amount_layout = self._create_panel()

        amount_row = QHBoxLayout()

        amount_label = QLabel("Amount (THB)")
        amount_label.setObjectName("sectionTitle")

        self.amount_input = QLineEdit("100.00")
        self.amount_input.setObjectName("amountInput")
        self.amount_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.amount_input.setPlaceholderText("Enter amount")

        amount_row.addWidget(amount_label)
        amount_row.addWidget(self.amount_input, 1)
        amount_layout.addLayout(amount_row)

        presets_layout = QGridLayout()
        presets_layout.setSpacing(9)

        preset_amounts = [50, 100, 200, 300, 500, 1000]

        for index, amount in enumerate(preset_amounts):
            button = QPushButton(f"฿{amount:,}")
            button.setObjectName("presetButton")

            button.clicked.connect(
                lambda checked=False, value=amount: self.amount_input.setText(f"{value:.2f}")
            )

            presets_layout.addWidget(button, index // 3, index % 3)

        amount_layout.addLayout(presets_layout)
        layout.addWidget(amount_panel)

        scan_panel, scan_layout = self._create_panel(soft=True)

        self.top_up_status_title = QLabel("Ready to Scan")
        self.top_up_status_title.setObjectName("largeStatus")

        self.top_up_status_message = QLabel("Place the card on the NFC reader.")
        self.top_up_status_message.setObjectName("mutedText")
        self.top_up_status_message.setWordWrap(True)

        self.top_up_identity = QLabel("UID: —     Token: Not detected")
        self.top_up_identity.setObjectName("mutedText")
        self.top_up_identity.setWordWrap(True)

        scan_layout.addWidget(self.top_up_status_title)
        scan_layout.addWidget(self.top_up_status_message)
        scan_layout.addWidget(self.top_up_identity)
        layout.addWidget(scan_panel)

        self.btn_confirm_top_up = QPushButton("Confirm Add Money")
        self.btn_confirm_top_up.setObjectName("primaryButton")
        self.btn_confirm_top_up.setEnabled(False)
        self.btn_confirm_top_up.clicked.connect(self._confirm_top_up)

        layout.addWidget(self.btn_confirm_top_up)
        layout.addStretch()

        self.amount_input.textChanged.connect(self._handle_amount_changed)

        return page

    # =========================================================
    # PAGE 3: CHECK BALANCE
    # =========================================================

    def _create_check_page(self) -> QWidget:
        page, layout = self._create_page(
            "Check Card Balance",
            "Tap a card to verify it and display the current balance.",
        )

        balance_panel, balance_layout = self._create_panel(soft=True)

        balance_title = QLabel("Current Balance")
        balance_title.setObjectName("sectionTitle")
        balance_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.check_balance_value = QLabel("—")
        self.check_balance_value.setObjectName("balanceValue")
        self.check_balance_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        balance_layout.addWidget(balance_title)
        balance_layout.addWidget(self.check_balance_value)
        layout.addWidget(balance_panel)

        status_panel, status_layout = self._create_panel()

        self.check_status = QLabel("Waiting for Card")
        self.check_status.setObjectName("largeStatus")

        self.check_message = QLabel("Place the card on the NFC reader.")
        self.check_message.setObjectName("mutedText")
        self.check_message.setWordWrap(True)

        self.check_identity = QLabel("UID: —     Token: Not detected")
        self.check_identity.setObjectName("mutedText")
        self.check_identity.setWordWrap(True)

        status_layout.addWidget(self.check_status)
        status_layout.addWidget(self.check_message)
        status_layout.addWidget(self.check_identity)

        layout.addWidget(status_panel)
        layout.addStretch()

        return page

    # =========================================================
    # PAGE 4: RETURN CARD
    # =========================================================

    def _create_return_page(self) -> QWidget:
        page, layout = self._create_page(
            "Return Card and Refund Balance",
            "Review the remaining balance before returning the card.",
        )

        values_panel, values_layout = self._create_panel()

        values_grid = QGridLayout()
        values_grid.setVerticalSpacing(13)

        value_titles = ["Current Balance", "Refund Amount", "Card Status"]

        for row, text in enumerate(value_titles):
            label = QLabel(text)
            label.setObjectName("sectionTitle")
            values_grid.addWidget(label, row, 0)

        self.return_balance_value = QLabel("—")
        self.return_refund_value = QLabel("—")
        self.return_card_status = QLabel("Waiting for Card")

        for value_label in [
            self.return_balance_value,
            self.return_refund_value,
            self.return_card_status,
        ]:
            value_label.setStyleSheet(
                "font-size: 24px;"
                "font-weight: 800;"
                "color: #087A58;"
                "padding: 6px;"
            )

        values_grid.addWidget(self.return_balance_value, 0, 1)
        values_grid.addWidget(self.return_refund_value, 1, 1)
        values_grid.addWidget(self.return_card_status, 2, 1)

        values_grid.setColumnStretch(1, 1)
        values_layout.addLayout(values_grid)

        self.return_warning = QLabel(
            "Tap a card to display the refundable balance. No change will be made until you confirm."
        )
        self.return_warning.setWordWrap(True)
        self.return_warning.setStyleSheet(
            "background-color: #FFF5E8;"
            "border: 1px solid #F3C98B;"
            "border-radius: 8px;"
            "color: #A54B08;"
            "font-size: 15px;"
            "font-weight: 650;"
            "padding: 12px;"
        )

        values_layout.addWidget(self.return_warning)

        self.return_identity = QLabel("UID: —     Token: Not detected")
        self.return_identity.setObjectName("mutedText")
        self.return_identity.setWordWrap(True)

        values_layout.addWidget(self.return_identity)
        layout.addWidget(values_panel)

        button_layout = QHBoxLayout()

        self.btn_return = QPushButton("Confirm Refund and Return Card")
        self.btn_return.setObjectName("primaryButton")
        self.btn_return.setEnabled(False)
        self.btn_return.clicked.connect(self._handle_return_action)

        cancel_button = QPushButton("Cancel Return")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self._clear_return_preview)

        button_layout.addWidget(self.btn_return, 2)
        button_layout.addWidget(cancel_button, 1)

        layout.addLayout(button_layout)
        layout.addStretch()

        return page

    # =========================================================
    # TRANSACTION TABLE
    # =========================================================

    def _create_ledger_panel(self) -> QFrame:
        panel, layout = self._create_panel()
        
        header_layout = QHBoxLayout()
        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        self.ledger_title = QLabel("Recent Transactions")
        self.ledger_title.setObjectName("pageTitle")

        self.ledger_subtitle = QLabel("Latest cashier and stall transactions")
        self.ledger_subtitle.setObjectName("mutedText")

        title_layout.addWidget(self.ledger_title)
        title_layout.addWidget(self.ledger_subtitle)
        
        # Clear filter button
        self.btn_clear_filter = QPushButton("Show All")
        self.btn_clear_filter.setObjectName("secondaryButton")
        self.btn_clear_filter.hide()
        self.btn_clear_filter.clicked.connect(self._clear_ledger_filter)

        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_clear_filter)

        layout.addLayout(header_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Time", "Card ID", "Action", "Amount", "Balance", "Status"])

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setShowGrid(False)
        
        # Add click event for filtering by UID
        self.table.cellClicked.connect(self._handle_ledger_click)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.table, 1)
        return panel
        
    def _clear_ledger_filter(self) -> None:
        self._ledger_filter_uid = None
        self.ledger_subtitle.setText("Latest cashier and stall transactions")
        self.btn_clear_filter.hide()
        self._refresh_ledger()

    def _handle_ledger_click(self, row: int, column: int) -> None:
        # If clicked on the Card ID column (index 1)
        if column == 1:
            item = self.table.item(row, column)
            if item and item.text() and item.text() != "Unknown":
                self._ledger_filter_uid = item.text()
                self.ledger_subtitle.setText(f"Filtered by Card ID: {self._ledger_filter_uid}")
                self.btn_clear_filter.show()
                self._refresh_ledger()

    def _refresh_ledger(self) -> None:
        records = database.get_recent_transactions(20, self._ledger_filter_uid)
        self.table.setRowCount(0)

        action_names = {
            "TOP_UP": "Add Money",
            "PAY": "Payment",
            "REFUND_RETURN": "Card Return",
        }

        for row_index, record in enumerate(records):
            self.table.insertRow(row_index)

            try:
                time_text = datetime.fromisoformat(str(record["timestamp"])).strftime("%H:%M")
            except (TypeError, ValueError):
                time_text = str(record["timestamp"])[11:16]
                
            card_id_text = str(record.get("card_uid", "Unknown"))
            action_code = str(record["action_type"])
            amount = float(record["amount"])

            if action_code == "TOP_UP":
                amount_text = f"+฿{amount:,.2f}"
                amount_color = QColor("#087A58")
            else:
                amount_text = f"-฿{amount:,.2f}"
                amount_color = QColor("#D65A00")

            action_text = action_names.get(action_code, action_code.replace("_", " ").title())

            values = [
                time_text,
                card_id_text,
                action_text,
                amount_text,
                f"฿{float(record['balance_after']):,.2f}",
                "Success",
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if column == 1:
                    # Style Card ID to look like a hyperlink
                    item.setForeground(QColor("#2864E8"))
                    font = QFont("Segoe UI", 14)
                    font.setUnderline(True)
                    item.setFont(font)
                    item.setToolTip("Click to filter transactions for this card")
                elif column == 3:
                    item.setForeground(amount_color)
                    item.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
                elif column == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif column == 5:
                    item.setForeground(QColor("#087A58"))

                self.table.setItem(row_index, column, item)

    # =========================================================
    # NAVIGATION
    # =========================================================

    def _switch_mode(self, mode: int) -> None:
        self._current_mode = mode
        self.page_stack.setCurrentIndex(mode)

        for index, button in enumerate(self.nav_buttons):
            button.setProperty("selected", index == mode)
            button.style().unpolish(button)
            button.style().polish(button)

        if not self._active_uid:
            return

        if mode == self.MODE_ISSUE:
            self._prepare_issue_view()
        elif mode == self.MODE_TOP_UP:
            self._clear_pending_top_up()
            self._set_top_up_feedback(
                "Remove and Tap Again",
                "The current card has already been read. Remove it and tap it again after selecting the amount.",
                None,
            )
        elif mode == self.MODE_CHECK:
            self._show_balance()
        elif mode == self.MODE_RETURN:
            self._prepare_return_view()

    # =========================================================
    # NFC CARD EVENTS
    # =========================================================

    @pyqtSlot(str, bool, object, str)
    def _handle_card_detected(
        self,
        uid: str,
        is_valid: bool,
        token_uuid: Optional[str],
        status: str,
    ) -> None:
        self._active_uid = uid
        self._active_token_uuid = token_uuid
        self._is_card_authenticated = is_valid
        self._last_card_status = status

        self._update_identity_labels()

        if self._current_mode == self.MODE_ISSUE:
            self._prepare_issue_view()
        elif self._current_mode == self.MODE_TOP_UP:
            self._prepare_top_up_confirmation()
        elif self._current_mode == self.MODE_CHECK:
            self._show_balance()
        elif self._current_mode == self.MODE_RETURN:
            self._prepare_return_view()

        self._refresh_ledger()

    @pyqtSlot()
    def _handle_card_removed(self) -> None:
        self._active_uid = None
        self._active_token_uuid = None
        self._is_card_authenticated = False
        self._last_card_status = ""

        self._clear_pending_top_up()
        self._reset_card_views()

    # =========================================================
    # SET UP CARD
    # =========================================================

    def _prepare_issue_view(self) -> None:
        self.issue_uid.setText(f"UID: {self._active_uid or '—'}")

        if not self._active_uid:
            self.btn_provision.setEnabled(False)
            return

        if not self._is_card_authenticated:
            if self._last_card_status == "FOREIGN_OR_UNINITIALIZED_CARD":
                self.issue_status_title.setText("New Card Detected")
                self.issue_status_message.setText("Confirm to write a secure food court token.")
                self.btn_provision.setEnabled(True)
            else:
                self.issue_status_title.setText("Card Could Not Be Verified")
                self.issue_status_message.setText(f"Card error: {self._last_card_status}")
                self.btn_provision.setEnabled(False)
            return

        wallet = database.get_wallet_by_token(self._active_token_uuid)

        if wallet is None or wallet["status"] == "AVAILABLE":
            self.issue_status_title.setText("Returned Card Ready")
            self.issue_status_message.setText("Confirm to assign a new token to this reusable card.")
            self.btn_provision.setEnabled(True)
        else:
            self.issue_status_title.setText("Card Is Already Active")
            self.issue_status_message.setText("Return the card and refund its balance before setting it up again.")
            self.btn_provision.setEnabled(False)

    def _handle_provision_action(self) -> None:
        if not self._active_uid:
            QMessageBox.warning(self, "Set Up Card", "No card is present on the reader.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Card Setup",
            "Set up this card with a new food court token and a starting balance of ฿0.00?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        success, result = self.nfc_worker.provision_active_card()

        if success:
            token_uuid = result
            database.register_provisioned_card(token_uuid, self._active_uid)

            self._active_token_uuid = token_uuid
            self._is_card_authenticated = True
            self._last_card_status = "TOKEN_VERIFIED"

            self.issue_status_title.setText("Card Set Up Successfully")
            self.issue_status_message.setText("The card is active with a starting balance of ฿0.00.")
            self.btn_provision.setEnabled(False)

            self._update_identity_labels()
            self._refresh_ledger()
        else:
            self.issue_status_title.setText("Card Setup Failed")
            self.issue_status_message.setText(self._friendly_error(result))

    # =========================================================
    # ADD MONEY WITH CONFIRMATION
    # =========================================================

    def _prepare_top_up_confirmation(self) -> None:
        self._clear_pending_top_up()

        if not self._is_card_authenticated or not self._active_token_uuid:
            self._set_top_up_feedback(
                "Card Rejected",
                f"The card could not be verified ({self._last_card_status}).",
                False,
            )
            return

        try:
            amount = float(self.amount_input.text().replace(",", "").strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            self._set_top_up_feedback(
                "Invalid Amount",
                "Enter an amount greater than zero. Then remove and tap the card again.",
                False,
            )
            return

        wallet = database.get_wallet_by_token(self._active_token_uuid)

        if wallet is None:
            self._set_top_up_feedback(
                "Wallet Not Found",
                "Set up this card before adding money.",
                False,
            )
            return

        if wallet["status"] != "ACTIVE":
            self._set_top_up_feedback(
                "Card Is Not Active",
                "This card cannot receive money in its current status.",
                False,
            )
            return

        current_balance = float(wallet["balance"])
        new_balance = current_balance + amount

        self._pending_top_up_amount = amount
        self._pending_top_up_uid = self._active_uid
        self._pending_top_up_token = self._active_token_uuid

        self._set_top_up_feedback(
            "Card Verified — Confirm Amount",
            f"Add ฿{amount:,.2f} to this card?\n"
            f"Current balance: ฿{current_balance:,.2f}   New balance: ฿{new_balance:,.2f}",
            True,
        )

        self.btn_confirm_top_up.setText(f"Confirm Add ฿{amount:,.2f}")
        self.btn_confirm_top_up.setEnabled(True)

    def _confirm_top_up(self) -> None:
        if (
            self._pending_top_up_amount is None
            or not self._pending_top_up_uid
            or not self._pending_top_up_token
        ):
            QMessageBox.warning(self, "Add Money", "No verified transaction is waiting for confirmation.")
            return

        if (
            not self._active_uid
            or self._active_uid != self._pending_top_up_uid
            or self._active_token_uuid != self._pending_top_up_token
        ):
            self._clear_pending_top_up()
            QMessageBox.warning(self, "Add Money", "The card was removed or changed. Please tap the card again.")
            return

        amount = self._pending_top_up_amount

        success, message, balance = database.process_top_up(
            self._pending_top_up_token,
            self._pending_top_up_uid,
            amount,
        )

        if success:
            self._set_top_up_feedback(
                "Money Added Successfully",
                f"Added ฿{amount:,.2f}\nCurrent balance: ฿{balance:,.2f}\nRemove the card before the next transaction.",
                True,
            )
            self._clear_pending_top_up(keep_message=True)
            self._refresh_ledger()
        else:
            self._set_top_up_feedback("Unable to Add Money", self._friendly_error(message), False)
            self._clear_pending_top_up(keep_message=True)

    def _handle_amount_changed(self, _new_text: str) -> None:
        if self._pending_top_up_amount is None:
            return
        self._clear_pending_top_up()
        self._set_top_up_feedback(
            "Amount Changed",
            "The previous confirmation was cancelled. Remove the card and tap it again to confirm the new amount.",
            None,
        )

    def _clear_pending_top_up(self, keep_message: bool = False) -> None:
        self._pending_top_up_amount = None
        self._pending_top_up_uid = None
        self._pending_top_up_token = None

        if hasattr(self, "btn_confirm_top_up"):
            self.btn_confirm_top_up.setEnabled(False)
            self.btn_confirm_top_up.setText("Confirm Add Money")

        if not keep_message and hasattr(self, "top_up_status_title") and not self._active_uid:
            self._set_top_up_feedback("Ready to Scan", "Place the card on the NFC reader.", None)

    # =========================================================
    # CHECK BALANCE
    # =========================================================

    def _show_balance(self) -> None:
        self._update_identity_labels()

        if not self._is_card_authenticated or not self._active_token_uuid:
            self.check_balance_value.setText("—")
            self.check_status.setText("Card Rejected")
            self.check_status.setStyleSheet("color: #B42318;")
            self.check_message.setText(f"The card could not be verified ({self._last_card_status}).")
            return

        wallet = database.get_wallet_by_token(self._active_token_uuid)

        if wallet is None:
            self.check_balance_value.setText("—")
            self.check_status.setText("Wallet Not Found")
            self.check_status.setStyleSheet("color: #B42318;")
            self.check_message.setText("Set up this card before use.")
            return

        self.check_balance_value.setText(f"฿{wallet['balance']:,.2f}")
        self.check_status.setText(str(wallet["status"]).title())
        self.check_status.setStyleSheet("color: #087A58;")
        self.check_message.setText("Card verified successfully. Remove the card when finished.")

    # =========================================================
    # RETURN CARD
    # =========================================================

    def _prepare_return_view(self) -> None:
        self._update_identity_labels()
        self.btn_return.setEnabled(False)

        if not self._is_card_authenticated or not self._active_token_uuid:
            self.return_balance_value.setText("—")
            self.return_refund_value.setText("—")
            self.return_card_status.setText("Card Rejected")
            self.return_warning.setText(f"The card could not be verified ({self._last_card_status}).")
            return

        wallet = database.get_wallet_by_token(self._active_token_uuid)

        if wallet is None:
            self.return_balance_value.setText("—")
            self.return_refund_value.setText("—")
            self.return_card_status.setText("Wallet Not Found")
            self.return_warning.setText("No wallet record exists for this card.")
            return

        balance = float(wallet["balance"])
        status = str(wallet["status"])

        self.return_balance_value.setText(f"฿{balance:,.2f}")
        self.return_refund_value.setText(f"฿{balance:,.2f}")
        self.return_card_status.setText(status.title())

        if status == "ACTIVE":
            self.return_warning.setText(
                "After confirmation, the balance will become ฿0.00 and the card will be available for reuse."
            )
            self.btn_return.setEnabled(True)
        else:
            self.return_warning.setText("This card has already been returned.")

    def _handle_return_action(self) -> None:
        if not self._active_uid or not self._active_token_uuid:
            QMessageBox.warning(self, "Return Card", "No verified card is present.")
            return

        wallet = database.get_wallet_by_token(self._active_token_uuid)

        if wallet is None:
            QMessageBox.warning(self, "Return Card", "No wallet record was found.")
            return

        refund_amount = float(wallet["balance"])

        confirm = QMessageBox.question(
            self,
            "Confirm Refund and Card Return",
            f"Refund ฿{refund_amount:,.2f} and make this card available for reuse?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        success, message, refunded_amount = database.process_card_return(
            self._active_token_uuid,
            self._active_uid,
        )

        if success:
            self.return_balance_value.setText("฿0.00")
            self.return_refund_value.setText(f"฿{refunded_amount:,.2f}")
            self.return_card_status.setText("Available")
            self.return_warning.setText(f"Return completed. Give ฿{refunded_amount:,.2f} to the customer.")
            self.btn_return.setEnabled(False)
            self._refresh_ledger()
        else:
            QMessageBox.warning(self, "Return Card", self._friendly_error(message))

    # =========================================================
    # RESET AND FEEDBACK
    # =========================================================

    def _reset_card_views(self) -> None:
        self.issue_status_title.setText("Ready for a New Card")
        self.issue_status_message.setText("Place the card on the NFC reader.")
        self.issue_uid.setText("UID: —")
        self.btn_provision.setEnabled(False)

        self._set_top_up_feedback("Ready to Scan", "Place the card on the NFC reader.", None)
        self.top_up_identity.setText("UID: —     Token: Not detected")

        self.check_balance_value.setText("—")
        self.check_status.setText("Waiting for Card")
        self.check_status.setStyleSheet("color: #075E48;")
        self.check_message.setText("Place the card on the NFC reader.")
        self.check_identity.setText("UID: —     Token: Not detected")

        self._clear_return_preview()

    def _clear_return_preview(self) -> None:
        self.return_balance_value.setText("—")
        self.return_refund_value.setText("—")
        self.return_card_status.setText("Waiting for Card")
        self.return_warning.setText(
            "Tap a card to display the refundable balance. No change will be made until you confirm."
        )
        self.return_identity.setText("UID: —     Token: Not detected")
        self.btn_return.setEnabled(False)

    def _update_identity_labels(self) -> None:
        uid = self._active_uid or "—"
        
        # Removed [12:] to display the full 36-character Token UUID
        token = self._active_token_uuid if self._active_token_uuid else "Not detected"
        identity_text = f"UID: {uid}     Token: {token}"

        # Print the Token UUID to the terminal for easy copying during web application testing
        if self._active_token_uuid:
            print(f"\n[DEBUG] Use this Token for web testing: {self._active_token_uuid}\n")

        self.issue_uid.setText(f"UID: {uid}")
        self.top_up_identity.setText(identity_text)
        self.check_identity.setText(identity_text)
        self.return_identity.setText(identity_text)

    def _set_top_up_feedback(self, title: str, message: str, success: Optional[bool]) -> None:
        self.top_up_status_title.setText(title)
        self.top_up_status_message.setText(message)

        if success is True:
            color = "#087A58"
        elif success is False:
            color = "#B42318"
        else:
            color = "#075E48"

        self.top_up_status_title.setStyleSheet(f"color: {color};")

    @staticmethod
    def _friendly_error(code: str) -> str:
        messages = {
            "INVALID_AMOUNT": "The amount must be greater than zero.",
            "WALLET_NOT_FOUND": "No wallet record was found for this card.",
            "WALLET_SUSPENDED": "This card is not active.",
            "CARD_NOT_ACTIVE": "This card is not active.",
            "CARD_NOT_PRESENT": "Keep the card on the reader and try again.",
            "HARDWARE_NOT_INITIALIZED": "The NFC reader is not connected.",
        }
        return messages.get(code, str(code).replace("_", " ").title())

    # =========================================================
    # NFC READER STATUS
    # =========================================================

    def _update_reader_connection_state(self) -> None:
        if self.nfc_worker.is_alive():
            self.reader_status_label.setText("●  NFC Reader Connected")
            self.reader_status_label.setStyleSheet("")
        else:
            self.reader_status_label.setText("●  NFC Reader Not Connected")
            self.reader_status_label.setStyleSheet(
                "background-color: #FDECEC;"
                "border: 1px solid #F3B7B2;"
                "border-radius: 15px;"
                "color: #B42318;"
                "font-size: 15px;"
                "font-weight: 700;"
                "padding: 8px 14px;"
            )

    # =========================================================
    # CLOSE APPLICATION
    # =========================================================

    def closeEvent(self, event) -> None:
        if hasattr(self, "nfc_worker") and self.nfc_worker is not None:
            self.nfc_worker.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(CASHIER_STYLE)
    app.setFont(QFont("Segoe UI", 14))

    window = CashierApp()
    window.showMaximized()

    sys.exit(app.exec())