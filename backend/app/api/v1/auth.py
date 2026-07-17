from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_session_token
from app.config import get_settings
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> User:
    return auth_service.signup(
        db,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        age_attested=payload.age_attested,
        accept_terms=payload.accept_terms,
    )


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    user, token = auth_service.login(db, email=payload.email, password=payload.password)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_days * 24 * 60 * 60,
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session_token: str | None = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> None:
    settings = get_settings()
    auth_service.logout(db, token=session_token)
    response.delete_cookie(key=settings.session_cookie_name, path="/")


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
