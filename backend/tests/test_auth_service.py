from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Session as SessionModel
from app.models import User
from app.models.base import utcnow
from app.security.tokens import hash_token
from app.services import auth_service
from app.services.auth_service import (
    AgeNotAttestedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    TermsNotAcceptedError,
    authenticate,
    login,
    logout,
    signup,
)


def _signup(db, email="auth@example.com", password="correct horse battery staple"):
    return signup(
        db,
        email=email,
        password=password,
        display_name="Auth Test",
        age_attested=True,
        accept_terms=True,
    )


def test_signup_persists_user_with_expected_fields(db_session):
    user = _signup(db_session)

    assert user.id is not None
    fetched = db_session.get(User, user.id)
    assert fetched is not None
    assert fetched.email == "auth@example.com"
    assert fetched.display_name == "Auth Test"
    assert fetched.age_attested is True
    assert fetched.terms_accepted_at is not None


def test_signup_hashes_password_not_plaintext(db_session):
    password = "correct horse battery staple"
    user = _signup(db_session, password=password)

    assert user.password_hash is not None
    assert user.password_hash != password


def test_signup_raises_when_age_not_attested(db_session):
    with pytest.raises(AgeNotAttestedError):
        signup(
            db_session,
            email="young@example.com",
            password="password123",
            display_name="Young Person",
            age_attested=False,
            accept_terms=True,
        )


def test_signup_raises_when_terms_not_accepted(db_session):
    with pytest.raises(TermsNotAcceptedError):
        signup(
            db_session,
            email="noterms@example.com",
            password="password123",
            display_name="No Terms",
            age_attested=True,
            accept_terms=False,
        )


def test_signup_raises_on_duplicate_email(db_session):
    _signup(db_session, email="dupe@example.com")
    with pytest.raises(EmailAlreadyExistsError):
        _signup(db_session, email="dupe@example.com")


def test_login_returns_user_and_working_token(db_session):
    password = "correct horse battery staple"
    signed_up = _signup(db_session, email="login@example.com", password=password)

    user, token = login(db_session, email="login@example.com", password=password)

    assert user.id == signed_up.id
    session_row = db_session.scalar(
        select(SessionModel).where(SessionModel.token_hash == hash_token(token))
    )
    assert session_row is not None
    assert session_row.user_id == user.id


def test_login_raises_invalid_credentials_on_wrong_password(db_session):
    _signup(db_session, email="wrongpw@example.com", password="rightpassword")
    with pytest.raises(InvalidCredentialsError):
        login(db_session, email="wrongpw@example.com", password="wrongpassword")


def test_login_raises_invalid_credentials_on_unknown_email(db_session):
    with pytest.raises(InvalidCredentialsError):
        login(db_session, email="doesnotexist@example.com", password="whatever")


def test_login_unknown_email_still_calls_verify_password(db_session, mocker):
    spy = mocker.spy(auth_service, "verify_password")

    with pytest.raises(InvalidCredentialsError):
        login(db_session, email="doesnotexist@example.com", password="whatever")

    assert spy.called
    assert spy.call_args.args[1] == auth_service._DUMMY_PASSWORD_HASH


def test_login_raises_invalid_credentials_on_null_password_hash(db_session, mocker):
    user = User(
        email="oauthonly@example.com",
        password_hash=None,
        display_name="OAuth Only",
        age_attested=True,
        terms_accepted_at=utcnow(),
    )
    db_session.add(user)
    db_session.flush()

    spy = mocker.spy(auth_service, "verify_password")

    with pytest.raises(InvalidCredentialsError):
        login(db_session, email="oauthonly@example.com", password="whatever")

    assert spy.called
    assert spy.call_args.args[1] == auth_service._DUMMY_PASSWORD_HASH


def test_authenticate_returns_user_for_valid_token(db_session):
    password = "correct horse battery staple"
    signed_up = _signup(db_session, email="authtok@example.com", password=password)
    _, token = login(db_session, email="authtok@example.com", password=password)

    result = authenticate(db_session, token=token)

    assert result is not None
    assert result.id == signed_up.id


def test_authenticate_returns_none_for_unknown_token(db_session):
    assert authenticate(db_session, token="garbage-token-that-does-not-exist") is None


def test_authenticate_returns_none_for_none_token(db_session):
    assert authenticate(db_session, token=None) is None


def test_authenticate_returns_none_for_expired_session(db_session):
    user = _signup(db_session, email="expired@example.com")
    token = "expired-token-value"
    expired_session = SessionModel(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() - timedelta(days=1),
    )
    db_session.add(expired_session)
    db_session.flush()

    assert authenticate(db_session, token=token) is None


def test_authenticate_returns_none_for_revoked_session(db_session):
    password = "correct horse battery staple"
    _signup(db_session, email="revoked@example.com", password=password)
    _, token = login(db_session, email="revoked@example.com", password=password)

    logout(db_session, token=token)

    assert authenticate(db_session, token=token) is None


def test_logout_revokes_session_so_authenticate_returns_none(db_session):
    password = "correct horse battery staple"
    _signup(db_session, email="logout@example.com", password=password)
    _, token = login(db_session, email="logout@example.com", password=password)

    assert authenticate(db_session, token=token) is not None

    logout(db_session, token=token)

    assert authenticate(db_session, token=token) is None


def test_logout_with_none_token_is_a_noop(db_session):
    logout(db_session, token=None)
