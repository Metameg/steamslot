from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Session as SessionModel
from app.models import User
from app.models.base import utcnow
from app.security.password import hash_password, verify_password
from app.security.tokens import generate_session_token, hash_token

SESSION_TTL = timedelta(days=get_settings().session_ttl_days)


class EmailAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AgeNotAttestedError(Exception):
    pass


class TermsNotAcceptedError(Exception):
    pass


def signup(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    age_attested: bool,
    accept_terms: bool,
) -> User:
    if not age_attested:
        raise AgeNotAttestedError
    if not accept_terms:
        raise TermsNotAcceptedError
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise EmailAlreadyExistsError

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        age_attested=True,
        terms_accepted_at=utcnow(),
    )
    db.add(user)
    db.flush()
    return user


def login(db: Session, *, email: str, password: str) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError

    token = generate_session_token()
    db.add(
        SessionModel(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + SESSION_TTL,
        )
    )
    db.flush()
    return user, token


def authenticate(db: Session, *, token: str | None) -> User | None:
    if not token:
        return None
    sess = db.scalar(select(SessionModel).where(SessionModel.token_hash == hash_token(token)))
    if sess is None or sess.revoked_at is not None or sess.expires_at <= utcnow():
        return None
    return db.get(User, sess.user_id)


def logout(db: Session, *, token: str | None) -> None:
    if not token:
        return
    sess = db.scalar(select(SessionModel).where(SessionModel.token_hash == hash_token(token)))
    if sess is not None and sess.revoked_at is None:
        sess.revoked_at = utcnow()
