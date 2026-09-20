"""Token minting — stdlib only.

Two kinds of token live here, with deliberately different designs.

A **session** token is 256 bits of CSPRNG output, stored only as a digest:
reading the database therefore cannot mint a working session. The digest is a
plain SHA-256 rather than a password KDF because the token is machine-generated
and high-entropy — there is nothing to brute-force — and every authenticated
request would otherwise pay the KDF's cost.

A **password-reset** token is signed and stateless instead, because it has to
survive being emailed: there is no row to look it up in, and none is wanted (D3
made sessions rows precisely so they can be revoked; a reset link is short-lived
by construction and retired by use). What makes it single-use is the *stamp*: a
keyed digest of the password hash it was minted against, so the moment the
password changes — by this token or by any other means — every outstanding token
for that account stops verifying. The stamp is keyed rather than plain so the
token never carries a value derived from the stored hash alone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

TOKEN_BYTES = 32

#: Truncated to keep the emailed token short; 128 bits is far beyond forgery.
STAMP_LENGTH = 32


def mint_token(nbytes: int = TOKEN_BYTES) -> str:
    """A fresh URL-safe session token (43 characters at the default size)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """The stored form of *token* — what lookups are keyed on."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResetToken:
    """A verified reset claim: the account, and the password it was minted for."""

    user_id: int
    stamp: str


def password_stamp(password_hash: str, *, secret: str) -> str:
    """The keyed digest that retires a reset token once the password changes."""
    return hmac.new(
        secret.encode("utf-8"), (password_hash or "").encode("utf-8"), hashlib.sha256
    ).hexdigest()[:STAMP_LENGTH]


def mint_reset_token(
    user_id: int,
    password_hash: str,
    *,
    secret: str,
    ttl: int,
) -> str:
    """A signed, expiring reset token for *user_id*.

    Signed with the app's secret rather than stored: see the module docstring for
    why this token is stateless while a session is a row.
    """
    payload = {
        "uid": int(user_id),
        "stamp": password_stamp(password_hash, secret=secret),
        "exp": int(time.time()) + int(ttl),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_sign(body, secret)}"


def read_reset_token(token: str, *, secret: str) -> ResetToken | None:
    """The claim behind *token*, or ``None``.

    ``None`` covers every way a token can be unusable — wrong signature,
    malformed, expired — because the caller does the same thing in each case, and
    saying which it was would only help whoever is guessing. Nothing raises here:
    this parses attacker-supplied input.
    """
    try:
        if not isinstance(token, str) or token.count(".") != 1:
            return None
        body, signature = token.split(".")
        if not hmac.compare_digest(_sign(body, secret), signature):
            return None
        payload = json.loads(_b64decode(body))
        if int(payload["exp"]) <= time.time():
            return None
        return ResetToken(user_id=int(payload["uid"]), stamp=str(payload["stamp"]))
    except (ValueError, TypeError, KeyError):
        return None


def _sign(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
