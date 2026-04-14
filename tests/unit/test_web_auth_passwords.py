"""Unit tests for :mod:`backend.web.auth_passwords`."""

from __future__ import annotations

import hashlib

import pytest

from backend.web.auth_passwords import hash_password_bcrypt, verify_password_against_stored


def test_fallback_hash_prefix() -> None:
    assert verify_password_against_stored("secret", "fallback_hash_secret")
    assert not verify_password_against_stored("wrong", "fallback_hash_secret")


def test_pbkdf2_legacy_format() -> None:
    salt = "a" * 32
    digest = hashlib.pbkdf2_hmac("sha256", b"pass", salt.encode(), 100000).hex()
    stored = salt + digest
    assert verify_password_against_stored("pass", stored)
    assert not verify_password_against_stored("nope", stored)


def test_bcrypt_roundtrip() -> None:
    pytest.importorskip("bcrypt")
    h = hash_password_bcrypt("my-password-9")
    assert verify_password_against_stored("my-password-9", h)
    assert not verify_password_against_stored("other", h)
