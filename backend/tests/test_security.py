"""Tests for security utilities: password hashing and session tokens."""
import pytest
from app.security.password import hash_password, verify_password
from app.security.tokens import generate_session_token, hash_token


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password_differs_from_plaintext(self):
        """Hash should differ from plaintext password."""
        pw = "my_secure_password"
        hashed = hash_password(pw)
        assert hashed != pw

    def test_hash_password_uses_random_salt(self):
        """Two hashes of the same password should differ (random salt per call)."""
        pw = "my_secure_password"
        hash1 = hash_password(pw)
        hash2 = hash_password(pw)
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Verify password should return True for correct password."""
        pw = "my_secure_password"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_verify_password_incorrect(self):
        """Verify password should return False for wrong password."""
        pw = "my_secure_password"
        hashed = hash_password(pw)
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_returns_false_for_malformed_hash(self):
        """Verify password should return False for malformed/corrupted hash."""
        # Test with a string that's not a valid argon2 hash
        assert verify_password("anything", "not-a-valid-argon2-hash") is False


class TestTokens:
    """Tests for session token generation and hashing."""

    def test_hash_token_is_deterministic(self):
        """Hash token should produce same output for same input."""
        token = "my_token_xyz"
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        assert hash1 == hash2

    def test_hash_token_is_hex_64(self):
        """Hash token should produce 64-character hex string (sha256)."""
        token = "my_token_xyz"
        hashed = hash_token(token)
        assert len(hashed) == 64
        # Verify it's a valid hex string
        assert all(c in "0123456789abcdef" for c in hashed)
        # Verify hash differs from plaintext token
        assert hashed != token

    def test_generate_session_token_returns_distinct_values(self):
        """Two calls should return different values (high entropy)."""
        token1 = generate_session_token()
        token2 = generate_session_token()
        assert token1 != token2

    def test_generate_session_token_reasonably_long(self):
        """Generated token should be reasonably long."""
        token = generate_session_token()
        # secrets.token_urlsafe(32) produces ~43 characters
        assert len(token) >= 40
