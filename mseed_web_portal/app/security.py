from __future__ import annotations

"""Password hashing utilities.

New passwords are hashed with bcrypt (``$2b$`` prefix).  Legacy hashes created
by the previous ``sha256_crypt`` scheme (``$5$`` prefix) are still accepted on
login and are transparently upgraded to bcrypt the next time the user signs in
(see ``needs_rehash`` / ``app_db.authenticate_user``).

We call the ``bcrypt`` library directly instead of going through passlib's
bcrypt backend: passlib 1.7.4 is incompatible with bcrypt >= 4.1 (it reads the
removed ``bcrypt.__about__`` attribute and mishandles the 72-byte limit), which
breaks hashing entirely.  passlib is only used for *verifying* old
sha256_crypt hashes, where it has no such issue.
"""

import bcrypt
from passlib.hash import sha256_crypt

# bcrypt only considers the first 72 bytes of a password.  Truncate explicitly
# so long passwords hash deterministically instead of raising on bcrypt >= 5.
_BCRYPT_MAX_BYTES = 72
_BCRYPT_ROUNDS = 12
MIN_PASSWORD_LENGTH = 8


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must contain at least {MIN_PASSWORD_LENGTH} characters."
        )
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("ascii")


# Backwards-compatible alias (some tools import get_password_hash).
def get_password_hash(password: str) -> str:
    return hash_password(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        if password_hash.startswith("$2"):
            return bcrypt.checkpw(_prepare(password), password_hash.encode("ascii"))
        if password_hash.startswith("$5$"):  # legacy sha256_crypt
            return sha256_crypt.verify(password, password_hash)
    except (ValueError, TypeError):
        return False
    return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash should be upgraded to current bcrypt settings."""
    if not password_hash:
        return False
    if not password_hash.startswith("$2"):
        return True  # legacy sha256_crypt -> upgrade to bcrypt
    try:
        # Hash layout: $2b$<rounds>$...
        rounds = int(password_hash.split("$")[2])
    except (IndexError, ValueError):
        return True
    return rounds < _BCRYPT_ROUNDS
