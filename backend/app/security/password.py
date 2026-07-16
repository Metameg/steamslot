"""Password hashing and verification using argon2."""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    """Hash a plaintext password using argon2."""
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    """Verify a plaintext password against its argon2 hash."""
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False
