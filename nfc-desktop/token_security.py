import hmac
import hashlib
import uuid
from typing import Tuple, Optional

# Secret key held exclusively by the payment system infrastructure
# In production, load this securely from an environment variable or KMS
SYSTEM_SECRET_KEY = b"KMUTNB_CPE_FOODCOURT_SECRET_2026"
MAGIC_HEADER = b"FCTK"  # 4 bytes identifier
TOKEN_PAYLOAD_PAGES = 9  # Pages 4 through 12 (36 bytes total)


class TokenSecurity:
    @staticmethod
    def generate_hmac(uid_bytes: bytes, token_uuid_bytes: bytes) -> bytes:
        """
        Compute a truncated 16-byte HMAC-SHA256 over the UID, magic header, and token UUID.
        """
        payload = uid_bytes + MAGIC_HEADER + token_uuid_bytes
        full_hmac = hmac.new(SYSTEM_SECRET_KEY, payload, hashlib.sha256).digest()
        return full_hmac[:16]

    @classmethod
    def create_token_payload(cls, uid_bytes: bytes) -> Tuple[bytes, str]:
        """
        Generate a serialized 36-byte token payload for NTAG21x provisioning.
        Returns the raw 36 bytes and the string representation of the Token UUID.
        """
        raw_uuid = uuid.uuid4().bytes
        signature = cls.generate_hmac(uid_bytes, raw_uuid)
        payload = MAGIC_HEADER + raw_uuid + signature
        return payload, str(uuid.UUID(bytes=raw_uuid))

    @classmethod
    def verify_token_payload(
        cls, uid_bytes: bytes, payload_bytes: bytes
    ) -> Tuple[bool, Optional[str], str]:
        """
        Verify the integrity and authenticity of the 36-byte payload read from the card.
        Returns: (is_valid, token_uuid_str, status_message)
        """
        if len(payload_bytes) != 36:
            return False, None, "INVALID_PAYLOAD_LENGTH"

        magic = payload_bytes[0:4]
        token_uuid_bytes = payload_bytes[4:20]
        received_signature = payload_bytes[20:36]

        if magic != MAGIC_HEADER:
            return False, None, "FOREIGN_OR_UNINITIALIZED_CARD"

        expected_signature = cls.generate_hmac(uid_bytes, token_uuid_bytes)

        # Constant-time comparison to mitigate timing attacks
        if not hmac.compare_digest(received_signature, expected_signature):
            return False, None, "SIGNATURE_VERIFICATION_FAILED"

        token_uuid_str = str(uuid.UUID(bytes=token_uuid_bytes))
        return True, token_uuid_str, "TOKEN_VERIFIED"