"""Encrypt OAuth tokens at rest. Never log or return decrypted tokens to clients."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.token_encryption_key.strip()
    if key:
        # Accept raw Fernet key or derive from arbitrary secret
        try:
            return Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            digest = hashlib.sha256(key.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    # Dev fallback derived from SECRET_KEY — not production-grade KMS
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt token; check TOKEN_ENCRYPTION_KEY") from exc
