from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.services import auth_service

__all__ = ["get_db", "get_session_token", "get_current_user"]

_settings = get_settings()


def get_session_token(
    session_token: str | None = Cookie(default=None, alias=_settings.session_cookie_name),
) -> str | None:
    """Raw session cookie value, if present. Shared by get_current_user and the logout
    route (which needs the token even when it no longer resolves to a user)."""
    return session_token


def get_current_user(
    session_token: str | None = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> User:
    user = auth_service.authenticate(db, token=session_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
