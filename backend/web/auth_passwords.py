"""
Single place to verify stored passwords (bcrypt, legacy pbkdf2, dev fallbacks).
"""

from __future__ import annotations

import hmac
import hashlib
from typing import Optional


def verify_password_against_stored(plain: str, stored: Optional[str]) -> bool:
    if not plain or not stored or not isinstance(stored, str):
        return False
    s = stored.strip()
    if not s:
        return False
    if s.startswith("fallback_hash_"):
        return hmac.compare_digest(plain, s.replace("fallback_hash_", "", 1))
    if s.startswith("$2a$") or s.startswith("$2b$") or s.startswith("$2y$"):
        try:
            import bcrypt

            return bcrypt.checkpw(
                plain.encode("utf-8"),
                s.encode("utf-8"),
            )
        except Exception:
            return False
    # Legacy main.py pbkdf2: 32-char salt + hex digest
    if len(s) >= 64:
        try:
            salt = s[:32]
            hash_part = s[32:]
            hash_obj = hashlib.pbkdf2_hmac(
                "sha256", plain.encode(), salt.encode(), 100000
            )
            return hmac.compare_digest(hash_obj.hex(), hash_part)
        except Exception:
            return False
    return False


def hash_password_bcrypt(plain: str) -> str:
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
