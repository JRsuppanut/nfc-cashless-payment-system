import time
import threading
from typing import Callable, Optional
import serial
from adafruit_pn532.uart import PN532_UART


class NFCWorker(threading.Thread):
    """
    Background worker thread managing PN532 serial communication.
    Implements edge-triggered card detection with hysteresis-backed state machine.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        on_tag_detected: Optional[Callable[[str], None]] = None,
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

        # State machine variables
        self._current_uid: Optional[str] = None
        self._consecutive_absence: int = 0

    def run(self) -> None:
        """Main execution loop for continuous hardware polling."""
        self._running = True

        try:
            self._serial_conn = serial.Serial(self.port, self.baudrate, timeout=0.1)
            self._pn532 = PN532_UART(self._serial_conn, debug=False)
            self._pn532.SAM_configuration()
        except Exception as exc:
            print(f"[NFCWorker] Hardware initialization failed: {exc}")
            self._running = False
            return

        while self._running:
            try:
                # Fast polling with short timeout to maintain responsive edge detection
                raw_uid = self._pn532.read_passive_target(timeout=0.1)

                if raw_uid is not None:
                    # Format raw bytes to standard colon-delimited hex string
                    detected_uid = ":".join(f"{b:02X}" for b in raw_uid)
                    self._handle_tag_present(detected_uid)
                else:
                    self._handle_tag_absent()

            except Exception as loop_error:
                # Prevent thread crash on transient serial communication glitches
                print(f"[NFCWorker] Polling communication error: {loop_error}")
                time.sleep(0.2)

            time.sleep(self.poll_interval)

        self._cleanup()

    def _handle_tag_present(self, detected_uid: str) -> None:
        """Process card presence frame."""
        self._consecutive_absence = 0

        # State transition: ABSENT -> PRESENT (Rising Edge Trigger)
        if self._current_uid is None:
            self._current_uid = detected_uid
            if self.on_tag_detected:
                self.on_tag_detected(detected_uid)

        # State transition: Token replaced without clear absence phase
        elif self._current_uid != detected_uid:
            self._current_uid = detected_uid
            if self.on_tag_detected:
                self.on_tag_detected(detected_uid)

        # State: Tag lingering on antenna -> Suppress further actions
        else:
            pass

    def _handle_tag_absent(self) -> None:
        """Process card absence frame with hysteresis filter."""
        if self._current_uid is not None:
            self._consecutive_absence += 1

            # Assert card removal only after exceeding absence threshold
            if self._consecutive_absence >= self.absence_threshold:
                self._current_uid = None
                self._consecutive_absence = 0
                if self.on_tag_removed:
                    self.on_tag_removed()

    def stop(self) -> None:
        """Signal worker thread termination and await joining."""
        self._running = False
        if self.is_alive():
            self.join(timeout=1.0)

    def _cleanup(self) -> None:
        """Safely release underlying serial resources."""
        if self._serial_conn and self._serial_conn.is_open:
            self._serial_conn.close()