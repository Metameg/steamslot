from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.services.auth_service import (
    AgeNotAttestedError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    TermsNotAcceptedError,
)
from app.services.ledger_service import InsufficientBalanceError
from app.services.pack_service import PackNotFoundError, PackTypeUnavailableError
from app.services.rng_engine import NoEligibleGamesError


def register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions raised by services to HTTP responses, so route handlers
    never need to catch these themselves."""

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

    @app.exception_handler(InsufficientBalanceError)
    async def _insufficient_balance(request: Request, exc: InsufficientBalanceError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={"detail": "Insufficient wallet balance"},
        )

    @app.exception_handler(PackTypeUnavailableError)
    async def _pack_type_unavailable(request: Request, exc: PackTypeUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "Pack type is not available for purchase"},
        )

    @app.exception_handler(PackNotFoundError)
    async def _pack_not_found(request: Request, exc: PackNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Pack not found"},
        )

    @app.exception_handler(NoEligibleGamesError)
    async def _no_eligible_games(request: Request, exc: NoEligibleGamesError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "No eligible games available to fulfill this pack"},
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "Conflict with current database state"},
        )
