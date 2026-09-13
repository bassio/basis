"""Session token minting — stdlib only.

A session token is 256 bits of CSPRNG output, stored only as a digest: reading
the database therefore cannot mint a working session. The digest is a plain
SHA-256 rather than a password KDF because the token is machine-generated and
high-entropy — there is nothing to brute-force — and every authenticated request
would otherwise pay the KDF's cost.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32


def mint_token(nbytes: int = TOKEN_BYTES) -> str:
    """A fresh URL-safe session token (43 characters at the default size)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """The stored form of *token* — what lookups are keyed on."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
