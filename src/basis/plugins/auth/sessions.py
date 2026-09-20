"""Session storage — the one place a session row is read or written (§4.2).

Routes never query ``AuthSession`` themselves, so moving sessions to another
backend (Redis, a signed cookie) touches this module and nothing else.

Everything here is synchronous, matching the framework's blocking DB/store
posture (D12) and the synchronous CSR initial-state path.
"""

from datetime import timedelta

from sqlmodel import Session, select

from basis.plugins.auth.models import AuthSession, UserFields, utcnow
from basis.plugins.auth.tokens import hash_token, mint_token


def create_session(
    db: Session,
    user: UserFields,
    *,
    ttl: timedelta,
    user_agent: str | None = None,
    ip: str | None = None,
) -> str:
    """Start a session for *user* and return the raw token.

    The token is returned, never stored: what the database holds is its digest,
    so a database read cannot mint a working session.
    """
    token = mint_token()
    now = utcnow()
    db.add(
        AuthSession(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + ttl,
            last_seen_at=now,
            user_agent=user_agent,
            ip=ip,
        )
    )
    db.commit()
    return token


def resolve_session(db: Session, token: str | None) -> AuthSession | None:
    """The live session row behind *token*, or ``None``.

    ``None`` covers every way a session can be unusable — never issued, revoked,
    expired — because the caller has the same thing to do in each case: treat the
    request as anonymous. Revocation is row deletion, so "revoked" is not a
    separate state to check for.
    """
    if not token:
        return None
    row = db.exec(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).first()
    if row is None or row.expires_at <= utcnow():
        return None
    return row


def touch_session(db: Session, row: AuthSession, *, ttl: timedelta) -> None:
    """Slide *row*'s expiry forward, so a session in use does not time out.

    Deliberately separate from :func:`resolve_session`: resolution runs on every
    render once ``$auth`` seeds itself, and a read on that path must not become a
    write.
    """
    now = utcnow()
    row.last_seen_at = now
    row.expires_at = now + ttl
    db.add(row)
    db.commit()


def revoke_session(db: Session, token: str | None) -> bool:
    """End the session behind *token*. Returns whether a row was removed."""
    if not token:
        return False
    row = db.exec(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def revoke_all_sessions(db: Session, user_id: int) -> int:
    """End every session for *user_id* — "log out everywhere". Returns the count."""
    rows = db.exec(select(AuthSession).where(AuthSession.user_id == user_id)).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)
