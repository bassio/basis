"""Password hashing for the auth plugin — stdlib only.

The encoded form carries everything verification needs, so a later policy change
upgrades hashes on next login instead of locking anyone out::

    scrypt$<format-version>$<n>$<r>$<p>$<salt-b64>$<hash-b64>

The format version pins the *input preparation* (NFKC-normalised, UTF-8 encoded,
length-capped). That is not decoration: changing how a password is turned into
bytes changes every hash's meaning, so it has to be recorded, not assumed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass

SCHEME = "scrypt"

#: Bump when the input preparation changes (v1 = NFKC + UTF-8 + cap).
FORMAT_VERSION = 1

#: Policy. ``p`` raises an attacker's cost WITHOUT raising memory; ``N`` buys
#: memory-hardness and costs ``128*r*N`` bytes per concurrent hash. Measured at
#: these values: ~144 ms and 16 MiB per hash, so 40 concurrent logins pin
#: ~0.63 GiB. Raise ``N`` only if the host can afford ``memory × concurrency``;
#: otherwise raise ``p``.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 5

SALT_BYTES = 16
KEY_BYTES = 32

#: Refused, never truncated — truncation silently creates password collisions.
MAX_PASSWORD_BYTES = 1024


@dataclass(frozen=True)
class HashInfo:
    """A parsed encoded hash. ``state`` is authoritative; the rest may be empty."""

    scheme: str
    version: int
    n: int
    r: int
    p: int
    salt: bytes
    digest: bytes
    #: ``"ok"`` (current policy) · ``"legacy"`` (verifiable, below policy) ·
    #: ``"corrupt"`` (unparseable, unknown scheme, or a format we cannot read).
    state: str


_CORRUPT = HashInfo("", 0, 0, 0, 0, b"", b"", "corrupt")


def _maxmem(n: int, r: int, p: int) -> int:
    """OpenSSL's own memory accounting, plus headroom.

    Passing ``0`` (hashlib's default) caps memory below what scrypt already
    needs at ``N=2**15``, so the call fails outright rather than hashing slowly.
    ``maxmem`` therefore has to be derived from the parameters in use — never a
    literal, and never omitted.
    """
    return 128 * r * (n + p + 2) * 2


def _kdf(password: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password, salt=salt, n=n, r=r, p=p, dklen=KEY_BYTES, maxmem=_maxmem(n, r, p)
    )


def _prepare(password: str) -> bytes:
    """NFKC-normalise → UTF-8 encode → enforce the length cap.

    Normalising is what stops one visual password typed with a different Unicode
    composition from failing to verify. This is a pinning point: the format
    version, not this function's body, is what promises it.
    """
    if not isinstance(password, str):
        raise TypeError("password must be a str")
    # UTF-8 never encodes a character in fewer than one byte, so a byte-length
    # over the cap is already certain here — and this rejects it before copying
    # a potentially huge string.
    if len(password) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds {MAX_PASSWORD_BYTES} bytes")
    encoded = unicodedata.normalize("NFKC", password).encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password exceeds {MAX_PASSWORD_BYTES} bytes")
    return encoded


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    # validate=True: without it, urlsafe_b64decode silently drops non-alphabet
    # characters, which would turn a corrupt row into a short, "valid" digest.
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


def _at_least_policy(n: int, r: int, p: int) -> bool:
    """True when the stored cost is not weaker than policy in any dimension.

    A conservative test, not an equivalence: a hash is only replaced when some
    parameter is below the current policy, so tuning policy can never downgrade a
    hash that was already stronger.
    """
    return n >= SCRYPT_N and r >= SCRYPT_R and p >= SCRYPT_P


def inspect_hash(encoded: str) -> HashInfo:
    """Parse an encoded hash without verifying anything.

    Callers use this to tell a legacy row (verifiable, worth upgrading) from a
    corrupt one (unreadable, worth logging) — a distinction that must not be
    invisible, or data corruption only surfaces as a user who cannot log in.
    """
    parts = encoded.split("$") if isinstance(encoded, str) else []
    if len(parts) != 7 or parts[0] != SCHEME:
        return _CORRUPT
    _, version, n, r, p, salt_b64, digest_b64 = parts
    try:
        version_i, n_i, r_i, p_i = int(version), int(n), int(r), int(p)
        salt, digest = _b64decode(salt_b64), _b64decode(digest_b64)
    except Exception:
        return _CORRUPT
    if not salt or not digest or version_i > FORMAT_VERSION:
        return _CORRUPT
    state = "ok" if (version_i == FORMAT_VERSION and _at_least_policy(n_i, r_i, p_i)) else "legacy"
    return HashInfo(SCHEME, version_i, n_i, r_i, p_i, salt, digest, state)


def hash_password(password: str) -> str:
    """Hash *password* at the current policy.

    Raises ``ValueError`` for input we refuse to hash (over the length cap) —
    rejecting is honest, truncating is not.
    """
    prepared = _prepare(password)
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _kdf(prepared, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(
        (
            SCHEME,
            str(FORMAT_VERSION),
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _b64encode(salt),
            _b64encode(digest),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Check *password* against *encoded*, always paying exactly one KDF.

    Returns ``False`` — never raises — for a wrong password, an unusable input, a
    corrupt row or a scheme we do not implement. The unusable paths still run a
    KDF: short-circuiting would let response time distinguish "this row is
    corrupt" from "live account, wrong password".
    """
    info = inspect_hash(encoded)
    if info.state == "corrupt":
        _kdf(b"", b"\0" * SALT_BYTES, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        return False
    try:
        candidate = _prepare(password)
    except (TypeError, ValueError):
        _kdf(b"", info.salt, info.n, info.r, info.p)
        return False
    return hmac.compare_digest(_kdf(candidate, info.salt, info.n, info.r, info.p), info.digest)


def needs_rehash(encoded: str) -> bool:
    """True when a *successfully verified* hash is below the current policy.

    Only meaningful after ``verify_password`` returned True — a corrupt row has
    no password to rehash from.
    """
    return inspect_hash(encoded).state == "legacy"
