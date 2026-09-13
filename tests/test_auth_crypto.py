"""Phase 1a — ``crypto.py`` and ``tokens.py``.

The gate for this step: a password round-trips; wrong passwords and corrupt rows
fail closed without raising; the encoded form carries the policy; legacy rows
still verify and are flagged for upgrade; and every verify path costs exactly one
KDF (the property that stops response time from revealing whether a row is
corrupt — asserted by counting calls, not by timing).
"""

import pytest

from basis.plugins.auth import crypto, tokens

PASSWORD = "correct horse battery staple"

# One KDF at import; most assertions below are read-only against it.
_HASH = crypto.hash_password(PASSWORD)


def _encode(password, n, r, p, version=crypto.FORMAT_VERSION):
    """Build a valid encoded hash at arbitrary parameters."""
    salt = b"x" * crypto.SALT_BYTES
    digest = crypto._kdf(crypto._prepare(password), salt, n, r, p)
    return "$".join(
        (
            crypto.SCHEME,
            str(version),
            str(n),
            str(r),
            str(p),
            crypto._b64encode(salt),
            crypto._b64encode(digest),
        )
    )


# ── round trip ────────────────────────────────────────────────────────────


def test_password_round_trips():
    assert crypto.verify_password(PASSWORD, _HASH) is True


def test_wrong_password_fails():
    assert crypto.verify_password(PASSWORD + "x", _HASH) is False


def test_empty_password_round_trips():
    # Length policy belongs to the route layer (D17), so "" is hashable here —
    # and must verify, or the two ends disagree about what was stored.
    assert crypto.verify_password("", crypto.hash_password("")) is True


def test_same_password_hashes_differently():
    assert crypto.hash_password(PASSWORD) != crypto.hash_password(PASSWORD)


# ── the encoded form ──────────────────────────────────────────────────────


def test_encoded_form_records_scheme_version_and_policy():
    scheme, version, n, r, p, salt, digest = _HASH.split("$")
    assert scheme == crypto.SCHEME
    assert int(version) == crypto.FORMAT_VERSION
    assert (int(n), int(r), int(p)) == (crypto.SCRYPT_N, crypto.SCRYPT_R, crypto.SCRYPT_P)
    assert salt and digest


def test_inspect_hash_reports_ok_for_a_fresh_hash():
    info = crypto.inspect_hash(_HASH)
    assert info.state == "ok"
    assert info.scheme == crypto.SCHEME
    assert crypto.needs_rehash(_HASH) is False


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "garbage",
        "scrypt",
        "scrypt$1$16384$8$5$onlyfivefields",
        "scrypt$1$16384$8$5$!!!$!!!",  # invalid base64 characters
        "scrypt$1$notanint$8$5$c2FsdA$aGFzaA",  # non-numeric params
        "scrypt$1$16384$8$5$$",  # missing salt/digest
        "scrypt$99$16384$8$5$c2FsdA$aGFzaA",  # a format we cannot read
        "bcrypt$1$16384$8$5$c2FsdA$aGFzaA",  # a scheme we do not implement
        None,
        123,
    ],
)
def test_unreadable_hashes_are_corrupt_and_never_raise(encoded):
    assert crypto.inspect_hash(encoded).state == "corrupt"
    assert crypto.verify_password(PASSWORD, encoded) is False


# ── legacy rows upgrade, stronger rows are left alone ─────────────────────


def test_weaker_legacy_hash_verifies_and_is_flagged_for_upgrade():
    legacy = _encode(PASSWORD, 2 ** 12, 8, 1)
    assert crypto.verify_password(PASSWORD, legacy) is True
    assert crypto.inspect_hash(legacy).state == "legacy"
    assert crypto.needs_rehash(legacy) is True


def test_older_format_version_is_flagged_but_still_verifies():
    legacy = _encode(PASSWORD, crypto.SCRYPT_N, crypto.SCRYPT_R, crypto.SCRYPT_P, version=0)
    assert crypto.verify_password(PASSWORD, legacy) is True
    assert crypto.needs_rehash(legacy) is True


def test_stronger_than_policy_is_not_downgraded():
    # Policy may move down; a row that is already stronger must not be rehashed
    # weaker on next login.
    stronger = _encode(PASSWORD, crypto.SCRYPT_N * 2, crypto.SCRYPT_R, crypto.SCRYPT_P)
    assert crypto.verify_password(PASSWORD, stronger) is True
    assert crypto.needs_rehash(stronger) is False


# ── input preparation ─────────────────────────────────────────────────────


def test_nfkc_equivalent_passwords_verify():
    composed = "caf\u00e9-password"  # é as one code point
    decomposed = "cafe\u0301-password"  # e + combining acute
    assert crypto.verify_password(decomposed, crypto.hash_password(composed)) is True


def test_over_long_password_is_refused_not_truncated():
    long_password = "a" * (crypto.MAX_PASSWORD_BYTES + 1)
    with pytest.raises(ValueError):
        crypto.hash_password(long_password)
    # Verifying one fails closed rather than raising into the request.
    assert crypto.verify_password(long_password, _HASH) is False


def test_multibyte_password_is_capped_on_bytes_not_characters():
    # Fewer characters than the cap, more bytes: the byte cap is what counts.
    long_multibyte = "\u20ac" * (crypto.MAX_PASSWORD_BYTES // 3 + 1)
    assert len(long_multibyte) < crypto.MAX_PASSWORD_BYTES
    with pytest.raises(ValueError):
        crypto.hash_password(long_multibyte)


def test_non_string_password_is_refused():
    with pytest.raises(TypeError):
        crypto.hash_password(b"bytes")
    assert crypto.verify_password(b"bytes", _HASH) is False


# ── the uniform-cost invariant ────────────────────────────────────────────


@pytest.mark.parametrize(
    "password,encoded",
    [
        (PASSWORD, _HASH),  # correct
        ("wrong", _HASH),  # wrong password
        ("a" * (crypto.MAX_PASSWORD_BYTES + 1), _HASH),  # unusable input
        (PASSWORD, "scrypt$1$16384$8$5$!!!$!!!"),  # corrupt row
        (PASSWORD, "garbage"),  # unparseable row
    ],
)
def test_every_verify_path_costs_exactly_one_kdf(monkeypatch, password, encoded):
    """No path may return before paying the KDF.

    Otherwise response time distinguishes "corrupt row" from "live account,
    wrong password" — an oracle this module exists to avoid.
    """
    calls = []
    real_kdf = crypto._kdf

    def counting_kdf(*args, **kwargs):
        calls.append(args)
        return real_kdf(*args, **kwargs)

    monkeypatch.setattr(crypto, "_kdf", counting_kdf)
    crypto.verify_password(password, encoded)
    assert len(calls) == 1


# ── maxmem must track the policy ──────────────────────────────────────────


def test_maxmem_exceeds_openssl_requirement():
    """A policy bump must not run into hashlib's default memory cap.

    ``maxmem=0`` (the default) fails outright at N=2**15, so the derived value
    has to clear OpenSSL's own accounting at every point of the policy range.
    """
    assert crypto._maxmem(crypto.SCRYPT_N, crypto.SCRYPT_R, crypto.SCRYPT_P) > (
        128 * crypto.SCRYPT_R * (crypto.SCRYPT_N + crypto.SCRYPT_P + 2)
    )
    # The next policy step up must also be reachable.
    assert crypto._maxmem(2 ** 15, 8, 1) > 128 * 8 * (2 ** 15 + 1 + 2)


def test_hashing_at_policy_parameters_succeeds():
    # Guards against the maxmem regression: this is exactly the shape of call
    # that raises "memory limit exceeded" if maxmem is omitted.
    assert crypto.hash_password("x").startswith(f"{crypto.SCHEME}${crypto.FORMAT_VERSION}$")


# ── tokens ────────────────────────────────────────────────────────────────


def test_tokens_are_unique_and_url_safe():
    minted = {tokens.mint_token() for _ in range(50)}
    assert len(minted) == 50
    assert all(set(t) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_") for t in minted)


def test_token_hash_is_deterministic_and_not_the_token():
    token = tokens.mint_token()
    assert tokens.hash_token(token) == tokens.hash_token(token)
    assert tokens.hash_token(token) != token
    assert len(tokens.hash_token(token)) == 64  # sha256 hex
