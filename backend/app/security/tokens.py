"""Session token generation and hashing utilities."""
import hashlib
import secrets


def generate_session_token() -> str:
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a session token using SHA256."""
    return hashlib.sha256(token.encode()).hexdigest()
