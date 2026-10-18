# NFC Cashless Food Court Payment System

An account-based contactless payment infrastructure designed for low-latency food court environments. This system utilizes NFC technology (NTAG21x) strictly as identity carriers (UIDs), delegating all monetary state and transaction processing to a centralized ACID-compliant database. This architectural paradigm mitigates hardware cloning risks and prevents stored-value manipulation.

## System Architecture

The project is divided into three primary subsystems operating concurrently:

1. **nfc-desktop**: A native Python (Tkinter) GUI application containing standalone modules for the Cashier (card registration, top-ups, refunds) and Stall POS (balance deduction). It interfaces directly with a locally connected NXP PN532 module via USB-UART.
2. **nfc-embedded**: C++ firmware for the ESP32-S3 microcontroller. It functions as a standalone Kiosk scanner using a PN532 transceiver in High-Speed UART (HSU) mode, forwarding scanned 7-byte UIDs to the backend via HTTP POST requests.
3. **nfc-web-application**: A FastAPI backend providing RESTful endpoints and real-time WebSocket connections. It serves the centralized Kiosk dashboard (`kiosk.html`) to display live wallet balances instantly upon physical card taps.

## Hardware Requirements

* ESP32-S3 Development Board
* NXP PN532 NFC Module (Configured for UART mode: I0=0, I1=0)
* NTAG21x ISO/IEC 14443-A Tags (13.56 MHz)
* CP2102 / CH340 USB-to-UART Bridge (For desktop POS hardware integration)

## Software Dependencies

* Python 3.10+
* PostgreSQL (Primary datastore) or SQLite (Fallback persistence)
* Web Frameworks: FastAPI, Uvicorn, Jinja2
* Hardware Interfaces: `pyserial`, `adafruit-circuitpython-pn532`

## Installation and Execution

### 1. Web Application (Backend & Kiosk Display)
Navigate to the `nfc-web-application` directory and install the required dependencies.
Initialize the server on port 8000:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
