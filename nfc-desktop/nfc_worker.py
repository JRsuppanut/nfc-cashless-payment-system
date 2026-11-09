"""PN532 UART worker for the Cashier application.

Requires the matching token_security.py and FOODCOURT_SECRET_KEY.
Preserves the original thread interface and tag callbacks.
"""

import os
import time
import threading
import uuid
from urllib.parse import urlsplit, parse_qs

import serial
from adafruit_pn532.uart import PN532_UART

from token_security import TokenSecurity


# Override these settings through environment variables when needed.
DEFAULT_PORT = os.environ.get("NFC_PORT", "COM4")
BASE_URL = os.environ.get("FOODCOURT_BASE_URL", "http://192.168.1.59:8000").rstrip("/")

# Start at the user-memory area and limit access to 144 bytes.
# This range fits NTAG213 and can also be used with NTAG215/216.
START_PAGE = 4
TOTAL_PAGES = 36


class NFCWorker(threading.Thread):
    # The latest Cashier checks this version before allowing card operations.
    API_VERSION = 2

    def __init__(self, port=DEFAULT_PORT, baudrate=115200, on_tag_detected=None,
                 on_tag_removed=None, poll_interval=0.1, absence_threshold=3):
        super().__init__(daemon=True)

        self.port, self.baudrate = port, baudrate
        self.on_tag_detected, self.on_tag_removed = on_tag_detected, on_tag_removed
        self.poll_interval, self.absence_threshold = poll_interval, absence_threshold

        self._running = False
        self._serial_conn = None
        self._pn532 = None
        self._current_uid = None
        self._consecutive_absence = 0

        # Polling and application requests share one reader.
        # RLock prevents their serial commands from overlapping.
        self._lock = threading.RLock()
        self.last_error = ""
        self._stop_event = threading.Event()

    @staticmethod
    def _uid(raw):
        """Convert UID bytes to the format used by the application."""
        return ":".join(f"{b:02X}" for b in raw)

    def check_configuration(self):
        """Check the HMAC key before preparing a new operation."""
        TokenSecurity.sign_url_token(b"\x00" * 7, str(uuid.UUID(int=0)))

    def run(self):
        """Connect to the reader, poll for cards, and reconnect after errors."""
        self._running = True

        while not self._stop_event.is_set():
            try:
                with self._lock:
                    self._serial_conn = serial.Serial(self.port, self.baudrate, timeout=0.2, write_timeout=1)
                    self._pn532 = PN532_UART(self._serial_conn, debug=False)
                    self._pn532.SAM_configuration()
                    self.last_error = ""

                while not self._stop_event.is_set():
                    with self._lock:
                        raw = self._pn532.read_passive_target(timeout=0.1)

                        if raw is None:
                            self._process_absence()
                        else:
                            self._process_presence(raw, self._uid(raw))

                    self._stop_event.wait(self.poll_interval)

            except Exception as exc:
                self.last_error = str(exc)

            finally:
                with self._lock:
                    self._cleanup()

                    # A disconnected reader cannot confirm card presence.
                    if self._current_uid is not None:
                        self._current_uid = None

                        if self.on_tag_removed:
                            self.on_tag_removed()

            # Event-based waiting allows stop() to interrupt the retry delay.
            self._stop_event.wait(1.5)

        self._running = False

    def _present(self, expected_uid=None):
        """Read physical card presence instead of trusting the cached UID."""
        if not self._pn532:
            raise RuntimeError("HARDWARE_NOT_INITIALIZED")

        raw = self._pn532.read_passive_target(timeout=0.2)

        if raw is None:
            raise RuntimeError("CARD_NOT_PRESENT")

        uid = self._uid(raw)

        if expected_uid and uid != expected_uid:
            raise RuntimeError("CARD_CHANGED")

        return bytes(raw), uid

    def _capacity(self):
        """Read the advertised data-area capacity from the capability container."""
        cc = self._pn532.ntag2xx_read_block(3)

        if cc is None or len(cc) != 4 or cc[0] != 0xE1:
            raise RuntimeError("UNSUPPORTED_TAG")

        return int(cc[2]) * 8

    def _read_card_pages(self):
        """Read only the supported user-memory range."""
        capacity = self._capacity()
        count = min(TOTAL_PAGES, capacity // 4)
        data = bytearray()

        for page in range(START_PAGE, START_PAGE + count):
            block = self._pn532.ntag2xx_read_block(page)

            if block is None or len(block) != 4:
                raise RuntimeError("MEMORY_READ_FAILED")

            data.extend(block)

        return bytes(data)

    def _decode(self, raw_uid, data):
        """Decode the supported NDEF URI record and verify its signed token."""
        try:
            pos = 0

            # Scan the Type 2 Tag TLV structure for an NDEF message.
            while pos < len(data):
                tag = data[pos]; pos += 1

                if tag == 0:
                    continue

                if tag == 0xFE:
                    break

                if pos >= len(data):
                    raise ValueError

                size = data[pos]; pos += 1

                if size == 0xFF:
                    size = int.from_bytes(data[pos:pos+2], "big"); pos += 2

                if pos + size > len(data):
                    raise ValueError

                record = data[pos:pos+size]; pos += size

                if tag != 3:
                    continue

                # A zero-length NDEF message may be blank or partially written.
                if not record:
                    return False, None, "FOREIGN_OR_UNINITIALIZED_CARD"

                # Accept the single short URI record written by this worker.
                if len(record) < 5 or record[0] != 0xD1 or record[1] != 1 or record[3] != 0x55:
                    raise ValueError

                length = record[2]
                payload = record[4:]

                if len(payload) != length:
                    raise ValueError

                prefixes = {0:"",1:"http://www.",2:"https://www.",3:"http://",4:"https://"}

                if not payload or payload[0] not in prefixes:
                    raise ValueError

                url = prefixes[payload[0]] + payload[1:].decode("utf-8")
                parts = urlsplit(url)
                base = urlsplit(BASE_URL)

                # Reject links belonging to a different server or page.
                if parts.scheme != base.scheme or parts.netloc != base.netloc or parts.path != base.path + "/wallet":
                    return False, None, "FOREIGN_URL"

                values = parse_qs(parts.query, keep_blank_values=True)

                if len(values.get("t", [])) != 1:
                    raise ValueError

                token = str(uuid.UUID(values["t"][0]))

                # Report legacy cards separately; do not treat them as verified.
                if "s" not in values:
                    return False, token, "LEGACY_UNSIGNED_CARD"

                # The signature is bound to both the physical UID and the token.
                if len(values["s"]) != 1 or not TokenSecurity.verify_url_token(raw_uid, token, values["s"][0]):
                    return False, token, "SIGNATURE_VERIFICATION_FAILED"

                return True, token, "TOKEN_VERIFIED"

            return False, None, "FOREIGN_OR_UNINITIALIZED_CARD"

        except RuntimeError as exc:
            return False, None, str(exc)

        except (ValueError, IndexError, UnicodeError):
            return False, None, "INVALID_CARD_DATA"

    def read_current_card(self, expected_uid=None):
        """Return a fresh card snapshot, including signature verification."""
        with self._lock:
            raw, uid = self._present(expected_uid)
            valid, token, status = self._decode(raw, self._read_card_pages())

            # Confirm that the same card is still present after reading.
            self._present(uid)

            return uid, valid, token, status

    def verify_current_card(self, expected_uid, expected_token):
        """Require the expected physical card and verified usage-cycle token."""
        snapshot = self.read_current_card(expected_uid)

        if not snapshot[1]:
            raise RuntimeError(snapshot[3])

        if snapshot[2] != expected_token:
            raise RuntimeError("TOKEN_CHANGED")

        return snapshot

    def _process_presence(self, raw_uid, uid_str):
        """Notify the application when a different card is detected."""
        self._consecutive_absence = 0

        if uid_str == self._current_uid:
            return

        self._current_uid = uid_str

        try:
            valid, token, status = self._decode(raw_uid, self._read_card_pages())
        except Exception as exc:
            valid, token, status = False, None, str(exc)

        # Keep the original callback argument order.
        if self.on_tag_detected:
            self.on_tag_detected(uid_str, valid, token, status)

    def _process_absence(self):
        """Require consecutive missed reads before reporting card removal."""
        if self._current_uid is None:
            return

        self._consecutive_absence += 1

        if self._consecutive_absence >= self.absence_threshold:
            self._current_uid = None
            self._consecutive_absence = 0

            if self.on_tag_removed:
                self.on_tag_removed()

    def provision_active_card(self, expected_uid=None, token_uuid=None):
        """Write a signed URL and verify the complete result by reading it back.

        Cashier supplies its saved token so an interrupted operation can retry
        with the same token instead of creating another usage cycle.
        """
        with self._lock:
            try:
                raw, uid = self._present(expected_uid)
                token = str(uuid.UUID(str(token_uuid))) if token_uuid else str(uuid.uuid4())
                signature = TokenSecurity.sign_url_token(raw, token)
                url = f"{BASE_URL}/wallet?t={token}&s={signature}"

                # Use standard NDEF URI prefix compression.
                if url.startswith("https://"):
                    payload = b"\x04" + url[8:].encode("utf-8")
                elif url.startswith("http://"):
                    payload = b"\x03" + url[7:].encode("utf-8")
                else:
                    raise RuntimeError("INVALID_BASE_URL")

                if len(payload) > 250:
                    raise RuntimeError("URL_TOO_LONG")

                # Build one short URI record inside an NDEF TLV.
                record = b"\xD1\x01" + bytes([len(payload)]) + b"U" + payload
                encoded = b"\x03" + bytes([len(record)]) + record + b"\xFE"
                encoded += b"\x00" * (-len(encoded) % 4)

                if len(encoded) > min(self._capacity(), TOTAL_PAGES * 4):
                    raise RuntimeError("TAG_CAPACITY_EXCEEDED")

                # Publish a zero length first, then write the remaining pages.
                # Publish the actual length only after all pages are written.
                # This reduces partial-record exposure; it is not an atomic write.
                staged = encoded[:1] + b"\x00" + encoded[2:4]
                writes = [(START_PAGE, staged)]
                writes += [(START_PAGE+i//4, encoded[i:i+4]) for i in range(4,len(encoded),4)]
                writes += [(START_PAGE, encoded[:4])]

                for page, block in writes:
                    # Never continue writing after the expected card is removed.
                    self._present(uid)

                    if not self._pn532.ntag2xx_write_block(page, block):
                        raise RuntimeError("WRITE_INTERRUPTED")

                # A successful write acknowledgement alone is insufficient.
                data = self._read_card_pages()
                self._present(uid)

                if data[:len(encoded)] != encoded:
                    raise RuntimeError("READBACK_MISMATCH")

                valid, actual, status = self._decode(raw, data)

                if not valid or actual != token:
                    raise RuntimeError(status if not valid else "TOKEN_CHANGED")

                self._current_uid = uid
                return True, token

            except Exception as exc:
                # Cashier retains the original operation for recovery.
                return False, str(exc)

    def stop(self):
        """Request shutdown without joining the worker from its own thread."""
        self._stop_event.set()
        self._running = False

        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout=2.0)

    def _cleanup(self):
        """Release the serial connection before shutdown or reconnection."""
        if self._serial_conn:
            try:
                self._serial_conn.close()
            except Exception:
                pass

        self._serial_conn = None
        self._pn532 = None