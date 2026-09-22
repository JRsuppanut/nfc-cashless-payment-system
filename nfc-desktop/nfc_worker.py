import time
import threading
import uuid
from typing import Callable, Optional, Tuple
import serial
from adafruit_pn532.uart import PN532_UART

# ==========================================
# ⚙️ SYSTEM CONFIGURATION
# ==========================================
DEFAULT_PORT = "COM4"

# ⚠️ เปลี่ยน IP ตรงนี้เป็น IPv4 ของคอมพิวเตอร์คุณ (เช่น http://192.168.1.45:8000)
BASE_URL = "http://10.59.30.226:8000" 

class NFCWorker(threading.Thread):
    def __init__(
        self,
        port: str = DEFAULT_PORT,
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
        # อ่านข้อมูล 26 หน้า (Page 4 ถึง 29) รวม 104 ไบต์ เพื่อให้ครอบคลุม NDEF URL
        buffer = bytearray()
        try:
            for page in range(4, 30):
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

        if self._current_uid is None or self._current_uid != uid_str:
            self._current_uid = uid_str
            raw_data = self._read_card_pages()

            is_valid = False
            token_uuid = None
            status = "FOREIGN_OR_UNINITIALIZED_CARD"

            if raw_data is None:
                status = "MEMORY_READ_FAILED"
            else:
                # 🔍 NDEF Message Parsing (แยกส่วน URL ออกมาจากข้อมูลในบัตร)
                idx = raw_data.find(b'\x03') # หา Tag 0x03 (NDEF Message)
                if idx != -1 and idx + 1 < len(raw_data):
                    msg_len = raw_data[idx + 1]
                    if idx + 2 + msg_len <= len(raw_data):
                        ndef_msg = raw_data[idx + 2 : idx + 2 + msg_len]
                        
                        # ตรวจสอบว่าเป็น NDEF URI Record หรือไม่ (0xD1 = Well-known, 0x55 = 'U')
                        if len(ndef_msg) > 4 and ndef_msg[0] == 0xD1 and ndef_msg[3] == 0x55:
                            payload_len = ndef_msg[2]
                            payload = ndef_msg[4 : 4 + payload_len]
                            
                            # ตัด byte แรก (Prefix code) ออก แล้วแปลงเป็นตัวอักษร
                            url_bytes = payload[1:]
                            try:
                                url_str = url_bytes.decode('utf-8')
                                # ดึงค่า Token UUID ออกมาจาก URL
                                if "wallet?t=" in url_str:
                                    token_uuid = url_str.split("wallet?t=")[1].split("&")[0]
                                    is_valid = True
                                    status = "TOKEN_VERIFIED"
                                else:
                                    status = "NO_TOKEN_IN_URL"
                            except UnicodeDecodeError:
                                status = "URL_DECODE_FAILED"

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
        Write a standard NDEF URI Record to the card so smartphones can open it automatically.
        """
        with self._lock:
            if not self._pn532:
                return False, "HARDWARE_NOT_INITIALIZED"

            raw_uid = self._pn532.read_passive_target(timeout=0.2)
            if raw_uid is None:
                return False, "CARD_NOT_PRESENT"

            # 1. สร้าง Token UUID อันใหม่ และประกอบ URL
            token_uuid = str(uuid.uuid4())
            full_url = f"{BASE_URL}/wallet?t={token_uuid}"
            
            # 2. แปลง URL ให้อยู่ในโครงสร้าง NDEF URI Record
            url_bytes = full_url.encode('utf-8')
            payload = b'\x00' + url_bytes # 0x00 = Full URI string
            
            # NDEF Header: MB=1, ME=1, CF=0, SR=1, IL=0, TNF=1 (0xD1), Type_Len=1, Payload_Len, Type='U' (0x55)
            record = b'\xD1\x01' + bytes([len(payload)]) + b'U' + payload
            
            # NDEF Message TLV: Tag 0x03, Length, Record, Terminator 0xFE
            ndef_data = bytearray()
            ndef_data.append(0x03)
            ndef_data.append(len(record))
            ndef_data.extend(record)
            ndef_data.append(0xFE)
            
            # เติม 0x00 ให้พอดีกับขนาดหน้า (Page) ของบัตร (หาร 4 ลงตัว)
            while len(ndef_data) % 4 != 0:
                ndef_data.append(0x00)

            try:
                # 3. เขียนข้อมูลลงบัตร เริ่มที่ Page 4
                total_pages = len(ndef_data) // 4
                for idx in range(total_pages):
                    page = 4 + idx
                    chunk = ndef_data[idx*4 : (idx+1)*4]
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