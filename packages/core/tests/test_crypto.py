"""AES-256-GCM crypto helper + EncryptedBytes SQLAlchemy type tests."""

from __future__ import annotations

import base64

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import Column, MetaData, Table, create_engine, insert, select, text
from suitest_core.crypto import EncryptedBytes, decrypt, encrypt

_ZERO_KEY_B64 = base64.urlsafe_b64encode(b"\x00" * 32).decode()


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """encrypt/decrypt round-trips with matching AAD; wrong AAD raises InvalidTag."""
    monkeypatch.setenv("SUITEST_ENCRYPTION_KEY", _ZERO_KEY_B64)
    blob = encrypt("hello", aad=b"ws_1")
    # nonce(12) + ciphertext(len plaintext) + GCM tag(16)
    assert len(blob) == 12 + len("hello") + 16
    assert decrypt(blob, aad=b"ws_1") == "hello"
    with pytest.raises(InvalidTag):
        decrypt(blob, aad=b"ws_2")


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing SUITEST_ENCRYPTION_KEY raises a clear RuntimeError."""
    monkeypatch.delenv("SUITEST_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SUITEST_ENCRYPTION_KEY not set"):
        encrypt("x")


def test_wrong_key_length_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key that does not decode to 32 bytes raises a clear RuntimeError."""
    short_key = base64.urlsafe_b64encode(b"\x00" * 31).decode()
    monkeypatch.setenv("SUITEST_ENCRYPTION_KEY", short_key)
    with pytest.raises(RuntimeError, match="32 bytes"):
        encrypt("x")


def test_encrypted_bytes_sqlalchemy_type_bind_and_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EncryptedBytes encrypts at rest and decrypts on load (sync sqlite)."""
    monkeypatch.setenv("SUITEST_ENCRYPTION_KEY", _ZERO_KEY_B64)
    meta = MetaData()
    table = Table("t", meta, Column("blob", EncryptedBytes()))

    engine = create_engine("sqlite:///:memory:")
    try:
        meta.create_all(engine)
        with engine.begin() as conn:
            conn.execute(insert(table).values(blob="secret-value"))

        # Read back through the type → decrypted string.
        with engine.connect() as conn:
            loaded = conn.execute(select(table.c.blob)).scalar_one()
        assert loaded == "secret-value"

        # Read the raw column bytes (bypass the type) → confirm at-rest encryption.
        with engine.connect() as conn:
            raw = conn.execute(text("SELECT blob FROM t")).scalar_one()
        assert isinstance(raw, bytes)
        assert b"secret-value" not in raw
    finally:
        engine.dispose()
