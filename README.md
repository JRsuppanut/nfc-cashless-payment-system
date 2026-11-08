# NFC Cashless Food Court Payment System

An enterprise-grade, account-based contactless payment infrastructure designed for low-latency food court environments. This system utilizes NFC technology (NTAG21x) strictly as identity carriers (UIDs), delegating all monetary state and transaction processing to a centralized ACID-compliant PostgreSQL database. This architectural paradigm mitigates hardware cloning risks and prevents stored-value manipulation.

## System Architecture

The architecture is decoupled into three primary subsystems operating concurrently:

1. **nfc-desktop**: A native Python (Tkinter) GUI application containing standalone modules for the Cashier (card registration, top-ups, refunds) and Stall POS (balance deduction). It interfaces directly with a locally connected NXP PN532 module via a USB-UART bridge.

2. **nfc-embedded**: C++ firmware for the ESP32-S3 microcontroller. It functions as a standalone IoT Kiosk scanner utilizing a PN532 transceiver in High-Speed UART (HSU) mode, forwarding scanned 7-byte UIDs to the backend via HTTP POST requests over Wi-Fi.

3. **nfc-web-application**: A FastAPI backend providing RESTful endpoints and real-time WebSocket connections. It serves the centralized Kiosk dashboard (`kiosk.html`) to display live wallet balances instantly upon physical card taps.

## Repository Structure

```
nfc-cashless-payment-system/
├── nfc-desktop/
│   ├── cashier_app.py       # GUI for administration, top-ups, and refunds
│   ├── stall_pos_app.py     # GUI for vendor food transactions
│   ├── nfc_worker.py        # Background daemon for non-blocking serial I/O
│   ├── database.py          # PostgreSQL connection and execution wrapper
│   └── requirements.txt     # Python dependencies for desktop modules
├── nfc-embedded/
│   └── kiosk_nfc_scanner/
│       └── kiosk_nfc_scanner.ino  # ESP32-S3 firmware for network-attached NFC scanning
├── nfc-web-application/
│   ├── main.py              # FastAPI server, REST routes, and WebSocket controllers
│   ├── database.py          # Backend database models and connection pooling
│   └── templates/
│       └── kiosk.html       # Jinja2 template for the interactive customer display
└── README.md

```

## Hardware Specifications & Wiring

### Components Required

* **Microcontroller:** ESP32-S3 Development Board

* **NFC Controller:** NXP PN532 Module (Configured for HSU / UART Mode: `I0=0, I1=0`)

* **Contactless Target:** NTAG21x ISO/IEC 14443-A Tags (13.56 MHz, 7-Byte UID)

* **Host Bridge:** CP2102 / CH340 USB-to-UART (For Desktop POS integration)

### ESP32-S3 to PN532 UART Wiring

| ESP32-S3 Pin | PN532 Pin | Function | 
| ----- | ----- | ----- | 
| `3V3` / `5V` | `VCC` | Power Supply | 
| `GND` | `GND` | Common Ground | 
| `IO17` (`TX2`) | `RXD` | Serial Receive | 
| `IO16` (`RX2`) | `TXD` | Serial Transmit | 

## Software Dependencies

* **Runtime:** Python 3.10+

* **Relational Database:** PostgreSQL 15+ (Primary) or SQLite3 (Fallback)

* **Backend Frameworks:** FastAPI, Uvicorn, Jinja2, WebSockets

* **Hardware Drivers:** `pyserial`, `adafruit-circuitpython-pn532`

## Installation and Deployment

### 1. Database Initialization

1. Ensure the PostgreSQL service is running. Create a new database named `nfc_cashless_db`.

2. Update the connection strings in both `nfc-desktop/database.py` and `nfc-web-application/database.py` with your local PostgreSQL credentials (Host, Port, User, Password).

### 2. Backend & Kiosk Display (`nfc-web-application`)

Navigate to the web application directory and install dependencies:

```
cd nfc-web-application
pip install fastapi uvicorn jinja2 websockets psycopg2

```

Initialize the ASGI server on port 8000:

```
python -m uvicorn main:app --host 0.0.0.0 --port 8000

```

*Access the interactive Kiosk node via a web browser at `http://<SERVER_IP>:8000/kiosk`.*

### 3. Desktop POS Terminals (`nfc-desktop`)

Navigate to the desktop application directory and install dependencies:

```
cd nfc-desktop
pip install -r requirements.txt

```

Launch the respective operational terminal:

```
python cashier_app.py
# OR
python stall_pos_app.py

```

### 4. Embedded Kiosk Scanner (`nfc-embedded`)

1. Open `nfc-embedded/kiosk_nfc_scanner/kiosk_nfc_scanner.ino` in the Arduino IDE.

2. Update the `SERVER_URL` constant (e.g., `http://10.137.155.226:8000/api/kiosk/scan`) and Wi-Fi credentials (`ssid`, `password`).

3. Compile and flash the firmware to the ESP32-S3.

4. Monitor the Serial Output (115200 baud) to verify network connection and PN532 initialization.

## Security & Concurrency Considerations

* **Zero Stored Value:** Physical tags store no monetary data. Raw EEPROM memory dumps cannot be replayed to manipulate credit variables.

* **ACID Atomicity:** Balance deductions utilize strict database-level transaction serialization, completely preventing race conditions during concurrent multi-stall accesses.

* **Role-Based Isolation:** Cashier and Stall POS terminals operate as distinct processes, enforcing the Principle of Least Privilege.

* **Software Debouncing:** Implemented a state-driven cooldown timestamp threshold per UID to eliminate catastrophic double-tap transactions.

## Troubleshooting

* **`[WinError 10048] Address in use`**: The port 8000 is occupied by a background process. Resolve this by terminating the existing process: `netstat -ano | findstr :8000` followed by `taskkill /PID <PID> /F`.

* **Database Unavailable in GUI**: Verify that the `postgresql-x64` service is running in `services.msc` and the connection parameters in `database.py` match your pgAdmin configuration.

* **`PN53x board not found`**: Validate the crossed UART wiring (TX to RX, RX to TX) and ensure both DIP switches on the PN532 module are set to the `0` (OFF) position.

* **Card Data Cannot Be Verified**: The business logic intentionally blocks duplicate active card registrations. Clear the respective row in the PostgreSQL database before re-registering an existing UID.
