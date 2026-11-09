"""Token creation and HMAC verification for the food-court NFC system."""

import os
import hmac
import hashlib
import uuid
from typing import Tuple, Optional


MAGIC_HEADER = b"FCTK"  # 4-byte identifier
TOKEN_PAYLOAD_PAGES = 9  # Legacy binary payload: 36 bytes


def _key() -> bytes:
    """Load the shared secret key from the environment."""
    secret_key = os.environ.get("FOODCOURT_SECRET_KEY", "").encode("utf-8")

    # Never fall back to a hardcoded key when configuration is missing.
    if len(secret_key) < 32:
        raise RuntimeError("SECRET_KEY_NOT_CONFIGURED")

    return secret_key


class TokenSecurity:
    @staticmethod
    def generate_hmac(uid_bytes: bytes, token_uuid_bytes: bytes) -> bytes:
        """Compute a 16-byte truncated HMAC-SHA256 for the UID and token."""
        payload = bytes(uid_bytes) + MAGIC_HEADER + bytes(token_uuid_bytes)
        full_hmac = hmac.new(_key(), payload, hashlib.sha256).digest()
        return full_hmac[:16]

    @classmethod
    def create_token_payload(cls, uid_bytes: bytes) -> Tuple[bytes, str]:
        """Create the original 36-byte binary payload.

        Retained for compatibility. The latest NFC worker writes an NDEF URL
        instead of writing this binary payload separately.
        """
        raw_uuid = uuid.uuid4().bytes
        signature = cls.generate_hmac(uid_bytes, raw_uuid)
        payload = MAGIC_HEADER + raw_uuid + signature
        return payload, str(uuid.UUID(bytes=raw_uuid))

    @classmethod
    def verify_token_payload(cls, uid_bytes: bytes, payload_bytes: bytes) -> Tuple[bool, Optional[str], str]:
        """Verify the original binary payload and return its token UUID."""
        if len(payload_bytes) != 36:
            return False, None, "INVALID_PAYLOAD_LENGTH"

        magic = payload_bytes[0:4]
        token_uuid_bytes = payload_bytes[4:20]
        received_signature = payload_bytes[20:36]

        if magic != MAGIC_HEADER:
            return False, None, "FOREIGN_OR_UNINITIALIZED_CARD"

        expected_signature = cls.generate_hmac(uid_bytes, token_uuid_bytes)

        # Compare signatures without ordinary string or byte equality.
        if not hmac.compare_digest(received_signature, expected_signature):
            return False, None, "SIGNATURE_VERIFICATION_FAILED"

        token_uuid_str = str(uuid.UUID(bytes=token_uuid_bytes))
        return True, token_uuid_str, "TOKEN_VERIFIED"

    @classmethod
    def sign_url_token(cls, uid_bytes: bytes, token: str) -> str:
        """Return the HMAC signature as 32 hexadecimal characters.

        The NFC worker stores this signature in the URL's 's' parameter.
        The secret key itself is never included in the URL.
        """
        token_uuid_bytes = uuid.UUID(str(token)).bytes
        signature = cls.generate_hmac(uid_bytes, token_uuid_bytes)
        return signature.hex()

    @classmethod
    def verify_url_token(cls, uid_bytes: bytes, token: str, signature: str) -> bool:
        """Verify the URL signature against the physical UID and token."""
        try:
            received_signature = bytes.fromhex(signature)
            token_uuid_bytes = uuid.UUID(str(token)).bytes
            expected_signature = cls.generate_hmac(uid_bytes, token_uuid_bytes)

            return len(received_signature) == 16 and hmac.compare_digest(received_signature, expected_signature)

        except (ValueError, TypeError, AttributeError):
            # Invalid UUIDs and malformed signatures are rejected.
            return False

        # A missing secret key raises RuntimeError intentionally.
        # The caller must report a configuration error instead of accepting
        # the card or silently using another key.