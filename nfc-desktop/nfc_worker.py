import time
import threading
from typing import Callable, Optional, Tuple
import serial
from adafruit_pn532.uart import PN532_UART
from token_security import TokenSecurity

START_PAGE = 4
TOTAL_PAGES = 9  # Pages 4 to 12


class NFCWorker(threading.Thread):
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        on_tag_detected: Optional[Callable[[str, bool, Optional[str], str], None]] = None,
        on_tag_removed: Optional[Callable[[], None]] = None,
        poll_interval: float = 0.05,
        absence_threshold: int = 3,
    ) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.on_tag_detected = on_tag_detected
        self.on_tag_removed = on_tag_removed
        self.poll_interval = poll_interval
        self.absence_threshold = absence_threshold

        self._running: bool = False
        self._serial_conn: Optional[serial.Serial] = None
        self._pn532: Optional[PN532_UART] = None

        self._current_uid: Optional[str] = None
        self._consecutive_absence: int = 0
        self._lock = threading.Lock()

    def run(self) -> None:
        self._running = True

        try:
            self._serial_conn = serial.Serial(self.port, self.baudrate, timeout=0.1)
            self._pn532 = PN532_UART(self._serial_conn, debug=False)
            self._pn532.SAM_configuration()
        except Exception as exc:
            print(f"[NFCWorker] Initialization error: {exc}")
            self._running = False
            return

        while self._running:
            with self._lock:
                try:
                    raw_uid = self._pn532.read_passive_target(timeout=0.08)

                    if raw_uid is not None:
                        uid_str = ":".join(f"{b:02X}" for b in raw_uid)
                        self._process_presence(raw_uid, uid_str)
                    else:
                        self._process_absence()

                except Exception as loop_error:
                    print(f"[NFCWorker] Polling glitch: {loop_error}")
                    time.sleep(0.1)

            time.sleep(self.poll_interval)

        self._cleanup()

    def _read_card_pages(self) -> Optional[bytes]:
        """Read 36 bytes (Pages 4 through 12) from the active NTAG target."""
        buffer = bytearray()
        try:
            for page in range(START_PAGE, START_PAGE + TOTAL_PAGES):
                page_data = self._pn532.ntag2xx_read_block(page)
                if page_data is None or len(page_data) != 4:
                    return None
                buffer.extend(page_data)
            return bytes(buffer)
        except Exception as read_exc:
            print(f"[NFCWorker] Memory read failure: {read_exc}")
            return None

    def _process_presence(self, raw_uid: bytearray, uid_str: str) -> None:
        self._consecutive_absence = 0

        # State transition: ABSENT -> PRESENT (Rising Edge)
        if self._current_uid is None or self._current_uid != uid_str:
            self._current_uid = uid_str
            raw_payload = self._read_card_pages()

            if raw_payload is None:
                is_valid = False
                token_uuid = None
                status = "MEMORY_READ_FAILED"
            else:
                is_valid, token_uuid, status = TokenSecurity.verify_token_payload(
                    bytes(raw_uid), raw_payload
                )

            if self.on_tag_detected:
                self.on_tag_detected(uid_str, is_valid, token_uuid, status)

    def _process_absence(self) -> None:
        if self._current_uid is not None:
            self._consecutive_absence += 1
            if self._consecutive_absence >= self.absence_threshold:
                self._current_uid = None
                self._consecutive_absence = 0
                if self.on_tag_removed:
                    self.on_tag_removed()

    def provision_active_card(self) -> Tuple[bool, str]:
        """
        Write new cryptographic token structure to the currently present card.
        Must be called from Cashier issuance workflow.
        """
        with self._lock:
            if not self._pn532:
                return False, "HARDWARE_NOT_INITIALIZED"

            raw_uid = self._pn532.read_passive_target(timeout=0.2)
            if raw_uid is None:
                return False, "CARD_NOT_PRESENT"

            payload, token_uuid = TokenSecurity.create_token_payload(bytes(raw_uid))

            try:
                # Write in 4-byte pages across Page 4 through 12
                for idx, page in enumerate(range(START_PAGE, START_PAGE + TOTAL_PAGES)):
                    chunk = payload[idx * 4 : (idx + 1) * 4]
                    if not self._pn532.ntag2xx_write_block(page, chunk):
                        return False, f"WRITE_FAILED_AT_PAGE_{page}"

                return True, token_uuid
            except Exception as write_exc:
                return False, f"PROVISIONING_EXCEPTION: {write_exc}"

    def stop(self) -> None:
        self._running = False
        if self.is_alive():
            self.join(timeout=1.0)

    def _cleanup(self) -> None:
        if self._serial_conn and self._serial_conn.is_open:
            self._serial_conn.close()