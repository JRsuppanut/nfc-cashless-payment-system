import sys
from datetime import datetime
from typing import Dict, Optional

from PyQt6.QtCore import QLocale, QObject, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import database
from nfc_worker import NFCWorker

STALL_IDENTIFIER = "STALL-01"

APP_STYLE = """
QMainWindow, QWidget#root {
    background: #F5F8FC;
    color: #0B1F3A;
    font-family: "Segoe UI";
    font-size: 16px;
}
QFrame#card, QFrame#headerCard {
    background: #FFFFFF;
    border: 1px solid #D5E1F0;
    border-radius: 14px;
}
QLabel#pageTitle {
    color: #071C3D;
    font-size: 31px;
    font-weight: 700;
}
QLabel#sectionTitle {
    color: #071C3D;
    font-size: 25px;
    font-weight: 700;
}
QLabel#helperText {
    color: #667A98;
    font-size: 15px;
}
QLabel#bigMoney {
    color: #1E4ED8;
    font-size: 40px;
    font-weight: 800;
}
QPushButton {
    min-height: 46px;
    padding: 7px 15px;
    border: 1px solid #AFC5E5;
    border-radius: 10px;
    background: #FFFFFF;
    color: #0B2348;
    font-size: 16px;
    font-weight: 650;
}
QPushButton:hover {
    background: #EEF5FF;
    border-color: #6EA8FE;
}
QPushButton:pressed {
    background: #DCEAFF;
}
QPushButton#primaryButton, QPushButton#categoryActive {
    color: #FFFFFF;
    background: #2864E8;
    border-color: #2864E8;
}
QPushButton#primaryButton:hover, QPushButton#categoryActive:hover {
    background: #174ED0;
}
QPushButton#dangerButton {
    color: #B42318;
    background: #FFF5F4;
    border-color: #FDA29B;
}
QPushButton:disabled {
    color: #FFFFFF;
    background: #B5C6DF;
    border-color: #B5C6DF;
}
QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit {
    min-height: 42px;
    padding: 5px 10px;
    background: #FFFFFF;
    color: #0B1F3A;
    border: 1px solid #C7D6EA;
    border-radius: 9px;
    selection-background-color: #2864E8;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {
    border: 2px solid #5A91F2;
}
QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #F7FAFE;
    border: 1px solid #D5E1F0;
    border-radius: 10px;
    gridline-color: #E4ECF7;
    selection-background-color: #DCEAFF;
    selection-color: #071C3D;
}
QHeaderView::section {
    background: #EDF3FA;
    color: #16345F;
    border: none;
    border-bottom: 1px solid #D5E1F0;
    padding: 10px 7px;
    font-size: 14px;
    font-weight: 700;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #EEF3F9;
    width: 12px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #AFC5E5;
    min-height: 30px;
    border-radius: 6px;
}
QCheckBox {
    spacing: 9px;
    font-size: 16px;
}
"""


class NFCBridge(QObject):
    tag_detected = pyqtSignal(str, bool, object, str)
    tag_removed = pyqtSignal()

    def emit_tag(
        self, uid: str, is_valid: bool, token_uuid: Optional[str], status: str
    ) -> None:
        self.tag_detected.emit(uid, is_valid, token_uuid, status)

    def emit_removal(self) -> None:
        self.tag_removed.emit()


class ReceiptDialog(QDialog):
    def __init__(self, receipt: Dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Payment Receipt")
        self.resize(620, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Payment Successful")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(f"Order #{receipt['order_id']}  •  {receipt['stall_name']}")
        subtitle.setObjectName("helperText")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        lines = [
            "FOOD COURT PAYMENT RECEIPT",
            "=" * 48,
            f"Order: #{receipt['order_id']}",
            f"Stall: {receipt['stall_name']} ({receipt['stall_id']})",
            f"Date:  {self._format_timestamp(receipt['created_at'])}",
            "-" * 48,
        ]

        for item in receipt["items"]:
            lines.append(
                f"{item['product_name']}  x{item['quantity']}"
                f"  @ ฿{item['unit_price']:.2f}"
                f"  = ฿{item['item_total']:.2f}"
            )
            if item.get("item_note"):
                lines.append(f"  Note: {item['item_note']}")

        lines.extend(
            [
                "-" * 48,
                f"TOTAL:             ฿{receipt['total_amount']:.2f}",
                f"REMAINING BALANCE: ฿{receipt['balance_after']:.2f}",
                "=" * 48,
                "Thank you",
            ]
        )

        receipt_box = QPlainTextEdit("\n".join(lines))
        receipt_box.setReadOnly(True)
        receipt_box.setFont(QFont("Consolas", 13))
        layout.addWidget(receipt_box, 1)

        close_button = QPushButton("Close Receipt")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    @staticmethod
    def _format_timestamp(value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M:%S")
        except (TypeError, ValueError):
            return str(value)


class StallPOSApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Food Court Stall POS [{STALL_IDENTIFIER}]")
        self.resize(1600, 900)
        self.setMinimumSize(1180, 720)

        database.initialize_database()

        self.cart: Dict[int, Dict] = {}
        self.products = []
        self.current_category = "All"
        self.selected_cart_product_id: Optional[int] = None
        self.selected_management_product_id: Optional[int] = None
        self.awaiting_payment = False
        self.operation_mode = "POS"

        self.nfc_bridge = NFCBridge()
        self.nfc_bridge.tag_detected.connect(self._handle_card_detected)
        self.nfc_bridge.tag_removed.connect(self._handle_card_removed)

        self._build_ui()
        self._load_stall_information()
        self._reload_products()
        self._refresh_cart()
        self._refresh_recent_sales()

        # Port configuration is managed centrally by NFCWorker
        self.nfc_worker = NFCWorker(
            on_tag_detected=self.nfc_bridge.emit_tag,
            on_tag_removed=self.nfc_bridge.emit_removal,
        )
        self.nfc_worker.start()

        self.reader_timer = QTimer(self)
        self.reader_timer.timeout.connect(self._refresh_reader_status)
        self.reader_timer.start(1000)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        outer.addWidget(self._build_header())

        self.pages = QStackedWidget()
        self.pos_page = self._build_pos_page()
        self.balance_page = self._build_balance_page()
        self.management_page = self._build_management_page()
        self.pages.addWidget(self.pos_page)
        self.pages.addWidget(self.balance_page)
        self.pages.addWidget(self.management_page)
        outer.addWidget(self.pages, 1)

    def _build_header(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("headerCard")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 11, 20, 11)
        layout.setSpacing(10)

        self.header_title = QLabel("Food Court Stall POS")
        self.header_title.setObjectName("pageTitle")
        layout.addWidget(self.header_title)
        layout.addStretch()

        self.pos_nav_button = QPushButton("Point of Sale")
        self.pos_nav_button.setObjectName("primaryButton")
        self.pos_nav_button.clicked.connect(self._show_pos_page)
        layout.addWidget(self.pos_nav_button)

        self.manage_nav_button = QPushButton("Manage Menu")
        self.manage_nav_button.clicked.connect(self._show_management_page)
        layout.addWidget(self.manage_nav_button)

        self.balance_nav_button = QPushButton("Check Card Balance")
        self.balance_nav_button.clicked.connect(self._show_balance_page)
        layout.addWidget(self.balance_nav_button)

        self.reader_badge = QLabel("● Connecting to NFC Reader")
        self.reader_badge.setMinimumWidth(235)
        self.reader_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_reader_badge(False, "Connecting to NFC Reader")
        layout.addWidget(self.reader_badge)

        stall_badge = QLabel(STALL_IDENTIFIER)
        stall_badge.setStyleSheet(
            "font-size: 17px; font-weight: 800; padding: 0 8px; color: #071C3D;"
        )
        layout.addWidget(stall_badge)
        return frame

    def _build_pos_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(self._build_menu_panel(), 24)
        layout.addWidget(self._build_order_panel(), 41)
        layout.addWidget(self._build_summary_panel(), 35)
        return page

    def _build_menu_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Menu")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.category_widget = QWidget()
        self.category_layout = QGridLayout(self.category_widget)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setSpacing(7)
        layout.addWidget(self.category_widget)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.menu_content = QWidget()
        self.menu_grid = QGridLayout(self.menu_content)
        self.menu_grid.setContentsMargins(0, 4, 0, 4)
        self.menu_grid.setSpacing(10)
        self.menu_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.menu_content)
        layout.addWidget(scroll, 1)
        return panel

    def _build_order_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(11)

        title = QLabel("Current Order")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.order_table = QTableWidget(0, 5)
        self.order_table.setHorizontalHeaderLabels(
            ["Product", "Quantity", "Price", "Total", "Order Note"]
        )
        self.order_table.setAlternatingRowColors(True)
        self.order_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.order_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.order_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.order_table.verticalHeader().setVisible(False)
        self.order_table.verticalHeader().setDefaultSectionSize(52)
        self.order_table.itemSelectionChanged.connect(self._cart_selection_changed)
        header = self.order_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.order_table, 1)

        self.remove_button = QPushButton("Remove Item")
        self.remove_button.setObjectName("dangerButton")
        self.remove_button.clicked.connect(self._remove_selected_item)
        layout.addWidget(self.remove_button)

        self.note_for_label = QLabel("Order Note — select an item first")
        self.note_for_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(self.note_for_label)

        note_row = QHBoxLayout()
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Example: No chili, extra sauce")
        self.note_input.setMaxLength(250)
        self.note_input.returnPressed.connect(self._save_item_note)
        self.save_note_button = QPushButton("Save Note to Selected Item")
        self.save_note_button.setObjectName("primaryButton")
        self.save_note_button.clicked.connect(self._save_item_note)
        note_row.addWidget(self.note_input, 1)
        note_row.addWidget(self.save_note_button)
        layout.addLayout(note_row)
        return panel

    def _build_summary_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Payment Summary")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        summary_card = QFrame()
        summary_card.setStyleSheet(
            "QFrame { background:#EAF3FF; border:1px solid #B7D4FF; border-radius:12px; }"
        )
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(17, 14, 17, 14)
        self.item_count_label = QLabel("Items: 0")
        self.item_count_label.setStyleSheet("font-size:18px;font-weight:700;")
        self.total_label = QLabel("฿0.00")
        self.total_label.setObjectName("bigMoney")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        summary_layout.addWidget(self.item_count_label)
        summary_layout.addWidget(QLabel("Total"))
        summary_layout.addWidget(self.total_label)
        layout.addWidget(summary_card)

        self.pay_button = QPushButton("Proceed to Card Payment")
        self.pay_button.setObjectName("primaryButton")
        self.pay_button.clicked.connect(self._begin_payment)
        layout.addWidget(self.pay_button)

        self.clear_button = QPushButton("Clear Order")
        self.clear_button.clicked.connect(self._clear_order)
        layout.addWidget(self.clear_button)

        self.payment_status = QLabel("Add menu items to begin an order.")
        self.payment_status.setWordWrap(True)
        self.payment_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.payment_status.setMinimumHeight(85)
        self._set_payment_status("Add menu items to begin an order.", "neutral")
        layout.addWidget(self.payment_status)

        recent_title = QLabel("Recent Sales")
        recent_title.setObjectName("sectionTitle")
        layout.addWidget(recent_title)

        self.sales_table = QTableWidget(0, 3)
        self.sales_table.setHorizontalHeaderLabels(["Time", "Amount", "Balance"])
        self.sales_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.sales_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.sales_table.verticalHeader().setVisible(False)
        self.sales_table.setMinimumHeight(280)
        sales_header = self.sales_table.horizontalHeader()
        sales_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        sales_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        sales_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.sales_table, 1)
        return panel

    def _build_balance_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 35, 40, 35)
        card_layout.setSpacing(17)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Check Card Balance")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        helper = QLabel("Place the customer card on the NFC reader. No payment will be made.")
        helper.setObjectName("helperText")
        helper.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(helper)

        self.balance_value = QLabel("—")
        self.balance_value.setObjectName("bigMoney")
        self.balance_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.balance_value)

        self.balance_card_status = QLabel("Waiting for Card")
        self.balance_card_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.balance_card_status.setStyleSheet(
            "font-size:28px;font-weight:750;color:#1E4ED8;"
        )
        card_layout.addWidget(self.balance_card_status)

        self.balance_uid_label = QLabel("UID: —")
        self.balance_uid_label.setObjectName("helperText")
        self.balance_uid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.balance_uid_label)

        back = QPushButton("Back to Order")
        back.clicked.connect(self._show_pos_page)
        card_layout.addWidget(back)
        layout.addWidget(card)
        return page

    def _build_management_page(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        table_card = QFrame()
        table_card.setObjectName("card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(20, 18, 20, 18)
        table_layout.setSpacing(11)

        title = QLabel("Stall and Menu Management")
        title.setObjectName("pageTitle")
        table_layout.addWidget(title)
        helper = QLabel("Add, edit, hide, or remove menu items for this stall.")
        helper.setObjectName("helperText")
        table_layout.addWidget(helper)

        stall_row = QHBoxLayout()
        stall_row.addWidget(QLabel("Stall Name"))
        self.stall_name_input = QLineEdit()
        self.save_stall_button = QPushButton("Save Stall Name")
        self.save_stall_button.setObjectName("primaryButton")
        self.save_stall_button.clicked.connect(self._save_stall_name)
        stall_row.addWidget(self.stall_name_input, 1)
        stall_row.addWidget(self.save_stall_button)
        table_layout.addLayout(stall_row)

        self.product_table = QTableWidget(0, 5)
        self.product_table.setHorizontalHeaderLabels(
            ["ID", "Menu Item", "Category", "Price", "Available"]
        )
        self.product_table.setAlternatingRowColors(True)
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.product_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.itemSelectionChanged.connect(self._management_selection_changed)
        product_header = self.product_table.horizontalHeader()
        product_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        product_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        product_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        product_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table_layout.addWidget(self.product_table, 1)
        outer.addWidget(table_card, 64)

        form_card = QFrame()
        form_card.setObjectName("card")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(22, 18, 22, 18)
        form_layout.setSpacing(10)

        form_title = QLabel("Menu Item Details")
        form_title.setObjectName("sectionTitle")
        form_layout.addWidget(form_title)

        form_layout.addWidget(QLabel("Menu Item Name"))
        self.product_name_input = QLineEdit()
        self.product_name_input.setPlaceholderText("Example: Chicken Rice")
        form_layout.addWidget(self.product_name_input)

        form_layout.addWidget(QLabel("Category"))
        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.addItems(["Rice", "Noodles", "Drinks", "Dessert", "Other"])
        form_layout.addWidget(self.category_input)

        form_layout.addWidget(QLabel("Price (THB)"))
        self.price_input = QDoubleSpinBox()
        self.price_input.setRange(0.0, 100000.0)
        self.price_input.setDecimals(2)
        self.price_input.setSingleStep(5.0)
        self.price_input.setPrefix("฿")
        self.price_input.setLocale(
            QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        )
        form_layout.addWidget(self.price_input)

        self.available_check = QCheckBox("Available for sale")
        self.available_check.setChecked(True)
        form_layout.addWidget(self.available_check)

        self.add_product_button = QPushButton("Add as New Menu Item")
        self.add_product_button.setObjectName("primaryButton")
        self.add_product_button.clicked.connect(self._add_product)
        form_layout.addWidget(self.add_product_button)

        self.update_product_button = QPushButton("Save Changes")
        self.update_product_button.clicked.connect(self._update_product)
        form_layout.addWidget(self.update_product_button)

        self.new_form_button = QPushButton("Clear Form")
        self.new_form_button.clicked.connect(self._clear_product_form)
        form_layout.addWidget(self.new_form_button)

        self.delete_product_button = QPushButton("Delete / Hide Menu Item")
        self.delete_product_button.setObjectName("dangerButton")
        self.delete_product_button.clicked.connect(self._delete_product)
        form_layout.addWidget(self.delete_product_button)

        self.management_message = QLabel("Select a menu item to edit, or enter a new one.")
        self.management_message.setWordWrap(True)
        self.management_message.setObjectName("helperText")
        form_layout.addWidget(self.management_message)
        form_layout.addStretch()
        outer.addWidget(form_card, 36)
        return page

    # ----------------------------------------------------------- Navigation

    def _show_pos_page(self) -> None:
        self.operation_mode = "POS"
        self.pages.setCurrentWidget(self.pos_page)
        self._set_active_nav(self.pos_nav_button)
        self.awaiting_payment = False
        self._set_payment_status("Ready to take an order.", "neutral")

    def _show_balance_page(self) -> None:
        self.operation_mode = "BALANCE"
        self.pages.setCurrentWidget(self.balance_page)
        self._set_active_nav(self.balance_nav_button)
        self.awaiting_payment = False
        self.balance_value.setText("—")
        self.balance_card_status.setText("Waiting for Card")
        self.balance_uid_label.setText("UID: —")

    def _show_management_page(self) -> None:
        self.operation_mode = "MANAGEMENT"
        self.pages.setCurrentWidget(self.management_page)
        self._set_active_nav(self.manage_nav_button)
        self.awaiting_payment = False
        self._load_management_products()

    def _set_active_nav(self, active: QPushButton) -> None:
        for button in (
            self.pos_nav_button,
            self.manage_nav_button,
            self.balance_nav_button,
        ):
            button.setObjectName("primaryButton" if button is active else "")
            button.style().unpolish(button)
            button.style().polish(button)

    # ------------------------------------------------------------- Products

    def _load_stall_information(self) -> None:
        stall = database.get_stall(STALL_IDENTIFIER)
        if stall:
            self.stall_name_input.setText(str(stall["stall_name"]))

    def _reload_products(self) -> None:
        self.products = database.get_products(STALL_IDENTIFIER)
        categories = sorted(
            {str(product["category"]) for product in self.products},
            key=str.casefold,
        )
        if self.current_category != "All" and self.current_category not in categories:
            self.current_category = "All"
        self._render_categories(["All"] + categories)
        self._render_menu()

    def _render_categories(self, categories) -> None:
        self._clear_layout(self.category_layout)
        for index, category in enumerate(categories):
            button = QPushButton(category)
            if category == self.current_category:
                button.setObjectName("categoryActive")
            button.clicked.connect(
                lambda checked=False, value=category: self._select_category(value)
            )
            self.category_layout.addWidget(button, index // 3, index % 3)

    def _select_category(self, category: str) -> None:
        self.current_category = category
        self._reload_products()

    def _render_menu(self) -> None:
        self._clear_layout(self.menu_grid)
        visible = [
            product
            for product in self.products
            if self.current_category == "All"
            or str(product["category"]) == self.current_category
        ]
        if not visible:
            empty = QLabel("No available menu items in this category.")
            empty.setObjectName("helperText")
            empty.setWordWrap(True)
            self.menu_grid.addWidget(empty, 0, 0, 1, 2)
            return

        for index, product in enumerate(visible):
            card = QFrame()
            card.setStyleSheet(
                "QFrame {background:#EDF5FF;border:1px solid #BBD6FF;border-radius:12px;}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 13, 14, 13)
            card_layout.setSpacing(7)

            name = QLabel(str(product["product_name"]))
            name.setWordWrap(True)
            name.setStyleSheet("font-size:18px;font-weight:750;border:none;")
            price = QLabel(f"฿{float(product['price']):,.2f}")
            price.setStyleSheet("font-size:24px;font-weight:800;color:#1E4ED8;border:none;")
            add_button = QPushButton("+  Add")
            add_button.setObjectName("primaryButton")
            add_button.clicked.connect(
                lambda checked=False, item=product: self._add_to_cart(item)
            )
            card_layout.addWidget(name)
            card_layout.addWidget(price)
            card_layout.addWidget(add_button)
            self.menu_grid.addWidget(card, index // 2, index % 2)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                StallPOSApp._clear_layout(child_layout)

    # ---------------------------------------------------------------- Cart

    def _add_to_cart(self, product: Dict) -> None:
        product_id = int(product["product_id"])
        if product_id in self.cart:
            self.cart[product_id]["quantity"] += 1
        else:
            self.cart[product_id] = {
                "product_id": product_id,
                "name": str(product["product_name"]),
                "price": float(product["price"]),
                "quantity": 1,
                "note": "",
            }
        self.selected_cart_product_id = product_id
        self.awaiting_payment = False
        self._refresh_cart(select_product_id=product_id)
        self._set_payment_status("Order updated. Review it before payment.", "neutral")

    def _refresh_cart(self, select_product_id: Optional[int] = None) -> None:
        self.order_table.blockSignals(True)
        self.order_table.setRowCount(0)
        total_quantity = 0
        total_amount = 0.0
        row_to_select = None

        for row_index, (product_id, item) in enumerate(self.cart.items()):
            self.order_table.insertRow(row_index)
            item_total = round(float(item["price"]) * int(item["quantity"]), 2)
            total_quantity += int(item["quantity"])
            total_amount = round(total_amount + item_total, 2)

            name_item = QTableWidgetItem(str(item["name"]))
            name_item.setData(Qt.ItemDataRole.UserRole, product_id)
            price_item = QTableWidgetItem(f"฿{float(item['price']):,.2f}")
            total_item = QTableWidgetItem(f"฿{item_total:,.2f}")
            note_item = QTableWidgetItem(str(item.get("note", "")))

            price_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            total_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.order_table.setItem(row_index, 0, name_item)
            self.order_table.setCellWidget(
                row_index,
                1,
                self._create_quantity_control(product_id, int(item["quantity"])),
            )
            for column, table_item in (
                (2, price_item),
                (3, total_item),
                (4, note_item),
            ):
                self.order_table.setItem(row_index, column, table_item)

            if product_id == select_product_id:
                row_to_select = row_index

        self.order_table.blockSignals(False)
        self.item_count_label.setText(f"Items: {total_quantity}")
        self.total_label.setText(f"฿{total_amount:,.2f}")
        self.pay_button.setEnabled(bool(self.cart))
        self.clear_button.setEnabled(bool(self.cart))

        if row_to_select is not None:
            self.order_table.selectRow(row_to_select)
        elif not self.cart:
            self.selected_cart_product_id = None
            self.note_for_label.setText("Order Note — select an item first")
            self.note_input.clear()

    def _cart_selection_changed(self) -> None:
        row = self.order_table.currentRow()
        if row < 0:
            self.selected_cart_product_id = None
            self.note_for_label.setText("Order Note — select an item first")
            self.note_input.clear()
            return
        name_item = self.order_table.item(row, 0)
        if name_item is None:
            return
        product_id = int(name_item.data(Qt.ItemDataRole.UserRole))
        self.selected_cart_product_id = product_id
        item = self.cart[product_id]
        self.note_for_label.setText(f"Order Note for: {item['name']}")
        self.note_input.setText(str(item.get("note", "")))

    def _create_quantity_control(self, product_id: int, quantity: int) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        row = QHBoxLayout(container)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(5)

        minus_button = QPushButton("−")
        minus_button.setFixedSize(34, 34)
        minus_button.setToolTip("Decrease quantity")
        minus_button.setStyleSheet(
            "QPushButton {min-height:0;padding:0;border-radius:8px;"
            "font-size:20px;font-weight:800;background:#FFFFFF;"
            "border:1px solid #AFC5E5;color:#174ED0;}"
            "QPushButton:hover {background:#EAF3FF;}"
        )
        minus_button.clicked.connect(
            lambda checked=False, pid=product_id: self._change_product_quantity(pid, -1)
        )

        quantity_label = QLabel(str(quantity))
        quantity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        quantity_label.setMinimumWidth(25)
        quantity_label.setStyleSheet(
            "font-size:17px;font-weight:750;color:#071C3D;background:transparent;"
        )

        plus_button = QPushButton("+")
        plus_button.setFixedSize(34, 34)
        plus_button.setToolTip("Increase quantity")
        plus_button.setStyleSheet(
            "QPushButton {min-height:0;padding:0;border-radius:8px;"
            "font-size:20px;font-weight:800;background:#2864E8;"
            "border:1px solid #2864E8;color:#FFFFFF;}"
            "QPushButton:hover {background:#174ED0;}"
        )
        plus_button.clicked.connect(
            lambda checked=False, pid=product_id: self._change_product_quantity(pid, 1)
        )

        row.addStretch()
        row.addWidget(minus_button)
        row.addWidget(quantity_label)
        row.addWidget(plus_button)
        row.addStretch()
        return container

    def _change_product_quantity(self, product_id: int, change: int) -> None:
        if product_id not in self.cart:
            return
        new_quantity = int(self.cart[product_id]["quantity"]) + change
        if new_quantity <= 0:
            del self.cart[product_id]
            self.selected_cart_product_id = None
            self._refresh_cart()
        else:
            self.cart[product_id]["quantity"] = new_quantity
            self._refresh_cart(select_product_id=product_id)
        self.awaiting_payment = False

    def _remove_selected_item(self) -> None:
        product_id = self.selected_cart_product_id
        if product_id is None or product_id not in self.cart:
            self._show_information("Select an item in Current Order first.")
            return
        del self.cart[product_id]
        self.selected_cart_product_id = None
        self.note_input.clear()
        self._refresh_cart()
        self.awaiting_payment = False

    def _save_item_note(self) -> None:
        product_id = self.selected_cart_product_id
        if product_id is None or product_id not in self.cart:
            self._show_information("Select an item in Current Order before saving a note.")
            return
        self.cart[product_id]["note"] = self.note_input.text().strip()
        self._refresh_cart(select_product_id=product_id)
        self._set_payment_status(f"Note saved for {self.cart[product_id]['name']}.", "success")

    def _clear_order(self) -> None:
        if not self.cart:
            return
        answer = QMessageBox.question(
            self,
            "Clear Order",
            "Remove every item from the current order?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cart.clear()
            self.awaiting_payment = False
            self._refresh_cart()
            self._set_payment_status("Order cleared.", "neutral")

    def _cart_for_database(self):
        return [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "note": item.get("note", ""),
            }
            for item in self.cart.values()
        ]

    def _begin_payment(self) -> None:
        if not self.cart:
            self._show_information("Add at least one menu item before payment.")
            return
        self.awaiting_payment = True
        self._set_payment_status(
            "Waiting for Card\nAsk the customer to tap the NFC card once.", "waiting"
        )
        self.pay_button.setText("Waiting for Card...")
        self.pay_button.setEnabled(False)

    # ------------------------------------------------------------- NFC flow

    @pyqtSlot(str, bool, object, str)
    def _handle_card_detected(
        self, uid: str, is_valid: bool, token_uuid: Optional[str], status: str
    ) -> None:
        if self.operation_mode == "BALANCE":
            self._process_balance_check(uid, is_valid, token_uuid, status)
            return

        if self.operation_mode != "POS":
            return

        if not self.awaiting_payment:
            self._set_payment_status(
                "Card detected, but payment has not started.\n"
                "Review the order and press Proceed to Card Payment.",
                "warning",
            )
            return

        self.awaiting_payment = False
        self.pay_button.setText("Proceed to Card Payment")

        if not is_valid or not token_uuid:
            self.pay_button.setEnabled(bool(self.cart))
            self._set_payment_status(f"Card Rejected\n{self._friendly_status(status)}", "error")
            return

        success, message, balance, order_id, total = database.process_order_payment(
            token_uuid=token_uuid,
            card_uid=uid,
            stall_id=STALL_IDENTIFIER,
            cart_items=self._cart_for_database(),
        )

        if not success:
            self.pay_button.setEnabled(bool(self.cart))
            if message == "INSUFFICIENT_FUNDS":
                shortage = max(0.0, total - balance)
                self._set_payment_status(
                    "Insufficient Balance\n"
                    f"Card balance: ฿{balance:,.2f}\n"
                    f"Additional amount needed: ฿{shortage:,.2f}",
                    "error",
                )
            else:
                self._set_payment_status(
                    f"Payment Failed\n{self._friendly_status(message)}", "error"
                )
            return

        receipt = database.get_order_receipt(int(order_id)) if order_id else None
        self._set_payment_status(
            f"Payment Successful\nPaid ฿{total:,.2f}\nRemaining balance ฿{balance:,.2f}",
            "success",
        )
        self.cart.clear()
        self.selected_cart_product_id = None
        self._refresh_cart()
        self._refresh_recent_sales()

        if receipt:
            dialog = ReceiptDialog(receipt, self)
            dialog.exec()

    def _process_balance_check(
        self, uid: str, is_valid: bool, token_uuid: Optional[str], status: str
    ) -> None:
        self.balance_uid_label.setText(f"UID: {uid}")
        if not is_valid or not token_uuid:
            self.balance_value.setText("—")
            self.balance_card_status.setText(f"Card Rejected — {self._friendly_status(status)}")
            self.balance_card_status.setStyleSheet("font-size:25px;font-weight:750;color:#B42318;")
            return

        wallet = database.get_wallet_by_token(token_uuid)
        if wallet is None:
            self.balance_value.setText("—")
            self.balance_card_status.setText("Card is not registered")
            self.balance_card_status.setStyleSheet("font-size:25px;font-weight:750;color:#B42318;")
            return

        self.balance_value.setText(f"฿{float(wallet['balance']):,.2f}")
        self.balance_card_status.setText(f"Card Status: {wallet['status']}")
        self.balance_card_status.setStyleSheet("font-size:25px;font-weight:750;color:#1E4ED8;")

    @pyqtSlot()
    def _handle_card_removed(self) -> None:
        if self.operation_mode == "BALANCE":
            self.balance_card_status.setText("Card removed — ready for another card")
            self.balance_card_status.setStyleSheet("font-size:25px;font-weight:750;color:#1E4ED8;")
        elif self.operation_mode == "POS" and self.awaiting_payment:
            self._set_payment_status("Card removed. Waiting for a card to pay.", "waiting")

    def _refresh_reader_status(self) -> None:
        connected = bool(
            hasattr(self, "nfc_worker")
            and self.nfc_worker.is_alive()
            and getattr(self.nfc_worker, "_pn532", None) is not None
        )
        self._style_reader_badge(
            connected,
            "NFC Reader Connected" if connected else "NFC Reader Not Connected",
        )

    def _style_reader_badge(self, connected: bool, text: str) -> None:
        if connected:
            self.reader_badge.setText(f"●  {text}")
            self.reader_badge.setStyleSheet(
                "background:#E8F2FF;color:#174ED0;border:1px solid #8EB9FF;"
                "border-radius:11px;padding:12px;font-weight:750;"
            )
        else:
            self.reader_badge.setText(f"●  {text}")
            self.reader_badge.setStyleSheet(
                "background:#FFF1F0;color:#B42318;border:1px solid #FDA29B;"
                "border-radius:11px;padding:12px;font-weight:750;"
            )

    # --------------------------------------------------------- Recent sales

    def _refresh_recent_sales(self) -> None:
        rows = database.get_recent_stall_orders(STALL_IDENTIFIER, 8)
        self.sales_table.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.sales_table.insertRow(row_index)
            try:
                shown_time = datetime.fromisoformat(str(row["created_at"])).strftime("%H:%M")
            except ValueError:
                shown_time = str(row["created_at"])
            values = [
                shown_time,
                f"฿{float(row['total_amount']):,.2f}",
                f"฿{float(row['balance_after']):,.2f}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.sales_table.setItem(row_index, column, item)

    # ------------------------------------------------------- Menu management

    def _load_management_products(self) -> None:
        products = database.get_products(STALL_IDENTIFIER, include_unavailable=True)
        self.product_table.blockSignals(True)
        self.product_table.setRowCount(0)
        for row_index, product in enumerate(products):
            self.product_table.insertRow(row_index)
            values = [
                str(product["product_id"]),
                str(product["product_name"]),
                str(product["category"]),
                f"฿{float(product['price']):,.2f}",
                "Yes" if int(product["is_available"]) else "No",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.product_table.setItem(row_index, column, item)
        self.product_table.blockSignals(False)

    def _management_selection_changed(self) -> None:
        row = self.product_table.currentRow()
        if row < 0:
            return
        product_id_item = self.product_table.item(row, 0)
        if product_id_item is None:
            return
        self.selected_management_product_id = int(product_id_item.text())
        products = database.get_products(STALL_IDENTIFIER, include_unavailable=True)
        product = next(
            (item for item in products if int(item["product_id"]) == self.selected_management_product_id),
            None,
        )
        if product is None:
            return
        self.product_name_input.setText(str(product["product_name"]))
        self.category_input.setCurrentText(str(product["category"]))
        self.price_input.setValue(float(product["price"]))
        self.available_check.setChecked(bool(product["is_available"]))
        self.management_message.setText(f"Editing menu item ID {self.selected_management_product_id}.")

    def _read_product_form(self):
        name = self.product_name_input.text().strip()
        category = self.category_input.currentText().strip() or "Other"
        price = float(self.price_input.value())
        available = self.available_check.isChecked()
        if not name:
            self._show_information("Enter a menu item name.")
            return None
        return name, category, price, available

    def _add_product(self) -> None:
        values = self._read_product_form()
        if values is None:
            return
        success, message, product_id = database.add_product(STALL_IDENTIFIER, *values)
        if not success:
            self.management_message.setText(self._friendly_status(message))
            return
        self.management_message.setText(f"New menu item saved as ID {product_id}.")
        self._clear_product_form(clear_message=False)
        self._after_menu_change()

    def _update_product(self) -> None:
        if self.selected_management_product_id is None:
            self._show_information("Select a menu item from the table first.")
            return
        values = self._read_product_form()
        if values is None:
            return
        success, message = database.update_product(
            self.selected_management_product_id,
            STALL_IDENTIFIER,
            *values,
        )
        self.management_message.setText(
            "Menu item updated." if success else self._friendly_status(message)
        )
        if success:
            self._after_menu_change()

    def _delete_product(self) -> None:
        if self.selected_management_product_id is None:
            self._show_information("Select a menu item from the table first.")
            return
        answer = QMessageBox.question(
            self,
            "Delete or Hide Menu Item",
            "Remove this item from the sales menu?\nIf it already appears in a receipt, it will be marked unavailable instead.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        success, message = database.delete_product(self.selected_management_product_id, STALL_IDENTIFIER)
        if success:
            self.management_message.setText(
                "Menu item hidden because it is used in an order."
                if message == "MARKED_UNAVAILABLE"
                else "Menu item deleted."
            )
            self._clear_product_form(clear_message=False)
            self._after_menu_change()
        else:
            self.management_message.setText(self._friendly_status(message))

    def _clear_product_form(self, clear_message: bool = True) -> None:
        self.selected_management_product_id = None
        self.product_table.clearSelection()
        self.product_name_input.clear()
        self.category_input.setCurrentText("Other")
        self.price_input.setValue(0.0)
        self.available_check.setChecked(True)
        if clear_message:
            self.management_message.setText("Enter details for a new menu item.")
        self.product_name_input.setFocus()

    def _after_menu_change(self) -> None:
        self._load_management_products()
        self._reload_products()

    def _save_stall_name(self) -> None:
        success, message = database.update_stall_name(STALL_IDENTIFIER, self.stall_name_input.text())
        self.management_message.setText(
            "Stall name saved." if success else self._friendly_status(message)
        )

    # -------------------------------------------------------------- Helpers

    def _set_payment_status(self, text: str, kind: str) -> None:
        colors = {
            "neutral": ("#F7FAFE", "#667A98", "#D5E1F0"),
            "waiting": ("#EAF3FF", "#174ED0", "#8EB9FF"),
            "success": ("#ECFDF3", "#067647", "#75E0A7"),
            "warning": ("#FFF8E8", "#B54708", "#FEC84B"),
            "error": ("#FFF1F0", "#B42318", "#FDA29B"),
        }
        background, foreground, border = colors[kind]
        self.payment_status.setText(text)
        self.payment_status.setStyleSheet(
            f"background:{background};color:{foreground};border:1px solid {border};"
            "border-radius:11px;padding:12px;font-size:16px;font-weight:700;"
        )

    @staticmethod
    def _friendly_status(status: str) -> str:
        messages = {
            "MEMORY_READ_FAILED": "The card data could not be read.",
            "UNREGISTERED_TOKEN": "This card is not registered in the system.",
            "WALLET_NOT_FOUND": "This card is not registered in the system.",
            "CARD_SUSPENDED": "This card is not active.",
            "WALLET_SUSPENDED": "This card is not active.",
            "INVALID_AMOUNT": "The payment amount is invalid.",
            "EMPTY_ORDER": "The order has no items.",
            "PRODUCT_NOT_FOUND": "A menu item no longer exists. Reload the menu.",
            "PRODUCT_UNAVAILABLE": "A menu item is no longer available.",
            "DUPLICATE_PRODUCT_NAME": "A menu item with this name already exists.",
            "PRODUCT_NAME_REQUIRED": "Enter a menu item name.",
            "STALL_NAME_REQUIRED": "Enter a stall name.",
            "INVALID_PRICE": "The price is invalid.",
            "INSUFFICIENT_FUNDS": "The card balance is insufficient.",
        }
        return messages.get(status, status.replace("_", " ").title())

    def _show_information(self, text: str) -> None:
        QMessageBox.information(self, "Food Court Stall POS", text)

    def closeEvent(self, event) -> None:
        if hasattr(self, "reader_timer"):
            self.reader_timer.stop()
        if hasattr(self, "nfc_worker") and self.nfc_worker is not None:
            self.nfc_worker.stop()
        event.accept()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    application.setStyleSheet(APP_STYLE)
    window = StallPOSApp()
    window.show()
    sys.exit(application.exec())