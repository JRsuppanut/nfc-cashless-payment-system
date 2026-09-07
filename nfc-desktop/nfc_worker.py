import time
import threading
import serial
from typing import Callable, Optional
from adafruit_pn532.uart import PN532_UART

class NFCWorker:
    """Manages serial communication with PN532 inside a dedicated background thread."""
    
    def __init__(self, port: str, on_tag_detected: Callable[[str], None], debug: bool = False):
        self.port = port
        self.on_tag_detected = on_tag_detected
        self.debug = debug
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._serial_connection: Optional[serial.Serial] = None
        self._pn532: Optional[PN532_UART] = None
        
    def start(self) -> None:
        """Initialize hardware connection and launch polling thread."""
        self._is_running = True
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop polling thread and release serial interface."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._serial_connection and self._serial_connection.is_open:
            self._serial_connection.close()

    def _polling_loop(self) -> None:
        """Continuously poll for NFC target presence."""
        try:
            self._serial_connection = serial.Serial(self.port, baudrate=115200, timeout=0.1)
            self._pn532 = PN532_UART(self._serial_connection, debug=self.debug)
            self._pn532.SAM_configuration()
        except Exception as exc:
            print(f"[NFCWorker] Initialization failed: {exc}")
            return

        last_seen_uid = ""
        last_seen_time = 0.0
        debounce_interval = 2.0  # Prevent immediate double reads

        while self._is_running:
            try:
                # Read passive target (ISO14443A Type 2 / NTAG)
                uid = self._pn532.read_passive_target(timeout=0.2)
                current_time = time.time()
                
                if uid is not None:
                    uid_str = ":".join(f"{b:02X}" for b in uid)
                    
                    # Apply debouncing
                    if uid_str != last_seen_uid or (current_time - last_seen_time) > debounce_interval:
                        last_seen_uid = uid_str
                        last_seen_time = current_time
                        self.on_tag_detected(uid_str)
                else:
                    # Reset last_seen_uid if card is removed
                    if (current_time - last_seen_time) > debounce_interval:
                        last_seen_uid = ""
                        
            except Exception as loop_err:
                # Catch communication glitches during tag removal
                time.sleep(0.1)
            
            time.sleep(0.05)