import uuid

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import rate_limit
from app.api.deps import get_current_user, get_db
from app.models import Game, Pack, PackType, Pull, User
from app.schemas.packs import (
    PackResponse,
    PackTypeResponse,
    PullResponse,
    PurchasePackRequest,
)
from app.services import pack_service

router = APIRouter(prefix="/packs", tags=["packs"])


def _limit_purchase(current_user: User = Depends(get_current_user)) -> None:
    rate_limit.enforce(rate_limit.PURCHASE_USER, "purchase-user", str(current_user.id))


def _limit_open(current_user: User = Depends(get_current_user)) -> None:
    rate_limit.enforce(rate_limit.OPEN_USER, "open-user", str(current_user.id))


def _pack_type_to_response(pack_type: PackType) -> PackTypeResponse:
    return PackTypeResponse(
        id=pack_type.id,
        name=pack_type.name,
        price_cents=pack_type.price,
        description=pack_type.description,
    )


def _pack_to_response(pack: Pack) -> PackResponse:
    return PackResponse(
        id=pack.id,
        pack_type_id=pack.pack_type_id,
        status=pack.status.value,
        price_paid_cents=pack.price_paid,
        purchased_at=pack.purchased_at,
    )


def _pull_to_response(pull: Pull, game: Game) -> PullResponse:
    return PullResponse(
        id=pull.id,
        game_title=game.title,
        game_header_image_url=game.header_image_url,
        locked_value_cents=pull.locked_value,
        status=pull.status.value,
        created_at=pull.created_at,
    )


@router.get("/types", response_model=list[PackTypeResponse])
def list_pack_types(db: Session = Depends(get_db)) -> list[PackTypeResponse]:
    pack_types = db.scalars(
        select(PackType).where(PackType.is_active.is_(True)).order_by(PackType.price)
    ).all()
    return [_pack_type_to_response(pt) for pt in pack_types]


@router.post(
    "/purchase",
    response_model=PackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_limit_purchase)],
)
def purchase_pack(
    payload: PurchasePackRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PackResponse:
    namespaced_key = f"{current_user.id}:{idempotency_key}"
    pack = pack_service.purchase_pack(
        db,
        user_id=current_user.id,
        pack_type_id=payload.pack_type_id,
        idempotency_key=namespaced_key,
    )
    return _pack_to_response(pack)


@router.post("/{pack_id}/open", response_model=PullResponse, dependencies=[Depends(_limit_open)])
def open_pack(
    pack_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PullResponse:
    pull = pack_service.open_pack(db, user_id=current_user.id, pack_id=pack_id)
    game = db.get(Game, pull.game_id)
    assert game is not None, "pull references a nonexistent game"
    return _pull_to_response(pull, game)


@router.get("/pulls", response_model=list[PullResponse])
def list_pulls(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PullResponse]:
    pulls = db.scalars(
        select(Pull).where(Pull.user_id == current_user.id).order_by(Pull.created_at.desc())
    ).all()
    responses = []
    for pull in pulls:
        game = db.get(Game, pull.game_id)
        assert game is not None, "pull references a nonexistent game"
        responses.append(_pull_to_response(pull, game))
    return responses
