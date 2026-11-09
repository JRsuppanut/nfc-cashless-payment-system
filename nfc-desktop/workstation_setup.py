"""Configure the cashier or stall profile on this computer."""

import sys

import psycopg2
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFormLayout,
    QMessageBox, QPushButton,
)
from serial.tools import list_ports

import terminal_registry as registry


class WorkstationSetup(QDialog):
    def __init__(self, terminals):
        super().__init__()
        self.setWindowTitle("ตั้งค่าเครื่อง Cashier / Stall")
        self.setMinimumWidth(440)
        form = QFormLayout(self)

        # Show only active stations registered by the food court administrator.
        self.station = QComboBox()
        self.station.setPlaceholderText("เลือกแคชเชียร์หรือร้าน")
        for role, station_id, name, active in terminals:
            if active:
                self.station.addItem(f"{station_id} — {name}", (role, station_id))
        self.station.setCurrentIndex(-1)

        # Allow manual entry when the reader is disconnected during testing.
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.addItems([port.device for port in list_ports.comports()])
        self.port.setCurrentIndex(-1)
        self.port.lineEdit().setPlaceholderText("เลือกหรือกรอกพอร์ต เช่น COM4")

        save_button = QPushButton("บันทึกการตั้งค่า")
        save_button.clicked.connect(self.save)
        form.addRow("แคชเชียร์หรือร้าน", self.station)
        form.addRow("พอร์ตเครื่องอ่านบัตร", self.port)
        form.addRow(save_button)

    def save(self):
        station = self.station.currentData()
        if station is None:
            QMessageBox.warning(self, "กรุณาเลือก", "เลือกแคชเชียร์หรือร้านก่อนบันทึก")
            return

        role, station_id = station
        port = self.port.currentText().strip().upper()
        # Reuse the local profile already read by both desktop apps.
        try:
            registry.bind(role, station_id, port)
        except ValueError as error:
            QMessageBox.warning(self, "ตรวจสอบข้อมูล", str(error))
        except (OSError, psycopg2.Error):
            QMessageBox.warning(self, "บันทึกไม่ได้", "ตรวจสอบฐานข้อมูลและสิทธิ์บันทึกของเครื่องนี้")
        else:
            QMessageBox.information(self, "บันทึกแล้ว", f"{station_id} ใช้พอร์ต {port}\nเปิดแอปใหม่เพื่อใช้ค่าที่บันทึก")
            self.accept()


def main():
    app = QApplication(sys.argv)
    # Admin is responsible for creating and updating the registry.
    try:
        terminals = registry.list_terminals()
    except psycopg2.errors.UndefinedTable:
        QMessageBox.warning(None, "ยังไม่ได้ตั้งระบบ", "เปิด Admin กับฐานข้อมูลนี้ก่อนตั้งค่าเครื่อง")
        return 1
    except psycopg2.Error:
        QMessageBox.warning(None, "เชื่อมฐานข้อมูลไม่ได้", "ตรวจสอบการตั้งค่า PostgreSQL แล้วเปิดใหม่")
        return 1

    if not any(row[3] for row in terminals):
        QMessageBox.warning(None, "ไม่มีจุดเปิดใช้งาน", "ให้ผู้ดูแลเพิ่มหรือเปิดใช้งานแคชเชียร์หรือร้านก่อน")
        return 1

    WorkstationSetup(terminals).exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())