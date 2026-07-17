from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.services.auth_service import (
    AgeNotAttestedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    TermsNotAcceptedError,
)


def register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions raised by services to HTTP responses, so route handlers
    never need to catch these themselves. Ledger/pack/rng exceptions and the
    IntegrityError->409 mapping are added by Task 7 alongside the routes that raise
    them."""

    @app.exception_handler(EmailAlreadyExistsError)
    async def _email_already_exists(request: Request, exc: EmailAlreadyExistsError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "Email already registered"},
        )

    @app.exception_handler(InvalidCredentialsError)
    async def _invalid_credentials(request: Request, exc: InvalidCredentialsError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid email or password"},
        )

    @app.exception_handler(AgeNotAttestedError)
    async def _age_not_attested(request: Request, exc: AgeNotAttestedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Age attestation is required"},
        )

    @app.exception_handler(TermsNotAcceptedError)
    async def _terms_not_accepted(request: Request, exc: TermsNotAcceptedError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Terms of service must be accepted"},
        )
