"""Symmetric encryption for per-user secrets (Gemini API keys).

Why Fernet:
- AES-128-CBC + HMAC-SHA256, IV per message, versioned token format. Safe
  defaults; we don't want to hand-roll AES-GCM here.
- A single ``APP_ENCRYPTION_KEY`` (env-supplied, 32 bytes urlsafe-b64) is
  enough for our threat model: protect rest-at-rest of stolen DB dumps.
  We are NOT defending against an attacker who already has app memory.

If APP_ENCRYPTION_KEY is unset the feature is disabled — calls to encrypt
raise ``EncryptionDisabled`` so routers can return 503 with a clear
message instead of silently storing plaintext. In production
``config.validate_for_runtime`` already refuses to start without it.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionDisabled(RuntimeError):
    """Raised when APP_ENCRYPTION_KEY is missing."""


class DecryptionError(RuntimeError):
    """Raised when ciphertext can't be decrypted (rotated key, tampering)."""


def _fernet() -> Fernet:
    key = get_settings().app_encryption_key
    if not key:
        raise EncryptionDisabled(
            "APP_ENCRYPTION_KEY is not configured; per-user secrets "
            "cannot be stored. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`"
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise EncryptionDisabled(
            f"APP_ENCRYPTION_KEY is malformed: {exc}"
        ) from exc


def encrypt(plaintext: str) -> bytes:
    """Encrypt a UTF-8 string and return the Fernet token as bytes."""
    if not plaintext:
        raise ValueError("plaintext must be non-empty")
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(token: bytes) -> str:
    """Decrypt bytes produced by ``encrypt``. Raises DecryptionError if the
    key changed or the ciphertext was tampered with."""
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        # Don't leak which step failed in the message — could be useful to
        # an attacker fishing for "yes the key rotated" signals.
        logger.exception("Failed to decrypt user secret")
        raise DecryptionError("ciphertext unreadable") from exc


def last4(plaintext: str) -> str:
    """Return up to the last 4 chars of a key for display purposes."""
    return plaintext[-4:] if plaintext else ""
