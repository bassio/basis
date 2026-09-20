"""Login throttling — lockout state as a database row (D13).

An in-memory counter would be per-worker, and therefore silently wrong behind
``uvicorn --workers N``: each worker would count its own share of the failures
and none would reach the threshold. A row is already correct at any worker
count, and it survives a restart.

The key pairs the caller with the account (``ip|email``) rather than using the
email alone, so a stranger cannot lock a real user out of their own account by
failing on their address. Counting happens for unknown emails too — a throttle
that only counted real accounts would itself answer "does this account exist?".
"""

from datetime import datetime, timedelta

from sqlmodel import Session

from basis.plugins.auth.models import LoginAttempt, utcnow


def key_for(ip: str | None, email: str) -> str:
    """The throttle key for one caller's attempts on one account."""
    return f"{ip or 'unknown'}|{email}"


def check_locked(db: Session, key: str) -> datetime | None:
    """The moment *key* is locked until, or ``None`` when it is not locked."""
    row = db.get(LoginAttempt, key)
    if row is None or row.locked_until is None:
        return None
    if row.locked_until <= utcnow():
        return None
    return row.locked_until


def record_failure(
    db: Session,
    key: str,
    *,
    threshold: int,
    window: int,
    duration: int,
) -> None:
    """Count one failed attempt, locking *key* once it reaches *threshold*.

    Failures older than *window* are forgotten first, so a slow trickle of
    typos never accumulates into a lockout — only a burst does.

    *duration* should be at least *window*: a lock that expires while its own
    window is still open would relock on the very next mistake, since the count
    that triggered it is still there.
    """
    now = utcnow()
    row = db.get(LoginAttempt, key)
    if row is None:
        row = LoginAttempt(key=key, count=0, window_start=now)
        db.add(row)
    elif now - row.window_start > timedelta(seconds=window):
        row.count = 0
        row.window_start = now
    row.count += 1
    if row.count >= threshold:
        row.locked_until = now + timedelta(seconds=duration)
    db.commit()


def clear_failures(db: Session, key: str) -> None:
    """Forget *key*'s failures — proving the password resets the window."""
    row = db.get(LoginAttempt, key)
    if row is not None:
        db.delete(row)
        db.commit()
