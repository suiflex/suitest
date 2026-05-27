"""AES-256-GCM crypto helper + SQLAlchemy ``EncryptedBytes`` column type.

The encryption key is read from ``SUITEST_ENCRYPTION_KEY`` (urlsafe-base64 of
exactly 32 bytes) at call time. Downstream models (Integration.secrets,
LLMConfig.api_key, McpProvider.secrets) declare encrypted columns via
``EncryptedBytes`` without re-implementing the cipher. See CLAUDE.md § 2.3.
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect

_MISSING = "SUITEST_ENCRYPTION_KEY not set (expect 32 bytes base64)."
_WRONG_LEN = "SUITEST_ENCRYPTION_KEY must decode to 32 bytes."

_NONCE_LEN = 12


def _key() -> bytes:
    raw = os.environ.get("SUITEST_ENCRYPTION_KEY")
    if not raw:
        raise RuntimeError(_MISSING)
    key = base64.urlsafe_b64decode(raw)
    if len(key) != 32:
        raise RuntimeError(_WRONG_LEN)
    return key


def encrypt(plaintext: str, aad: bytes = b"") -> bytes:
    """Encrypt ``plaintext`` to ``nonce || ciphertext || GCM-tag`` bytes."""
    aes = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    return nonce + ct


def decrypt(blob: bytes, aad: bytes = b"") -> str:
    """Decrypt a ``nonce || ciphertext || GCM-tag`` blob back to a string.

    Raises ``cryptography.exceptions.InvalidTag`` on tampering or AAD mismatch.
    """
    if not blob:
        raise ValueError("nothing to decrypt")
    aes = AESGCM(_key())
    nonce, ct = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    return aes.decrypt(nonce, ct, aad).decode("utf-8")


class EncryptedBytes(TypeDecorator[str]):
    """SQLAlchemy column that transparently encrypts/decrypts strings.

    Stored on the wire as ``LargeBinary`` (AES-GCM ``nonce||ct||tag``). The
    Python side reads/writes plain ``str``. AAD is intentionally not bound at the
    type level — callers needing AAD should call ``encrypt`` / ``decrypt``
    directly.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value: bytes | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return decrypt(value)
