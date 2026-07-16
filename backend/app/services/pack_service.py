import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LedgerEntry, OddsBand, OddsTable, Pack, PackType, Pull
from app.models.base import utcnow
from app.models.enums import LedgerEntryType, PackStatus, PullStatus
from app.services.ledger_service import append_entry
from app.services.rng_engine import roll


class PackTypeUnavailableError(Exception):
    pass


class PackNotFoundError(Exception):
    pass


def purchase_pack(
    db: Session, *, user_id: uuid.UUID, pack_type_id: uuid.UUID, idempotency_key: str
) -> Pack:
    pack_type = db.get(PackType, pack_type_id)
    if pack_type is None or not pack_type.is_active:
        raise PackTypeUnavailableError(f"pack_type {pack_type_id} is not available")

    odds_table = db.scalar(
        select(OddsTable)
        .where(OddsTable.pack_type_id == pack_type_id, OddsTable.is_published.is_(True))
        .order_by(OddsTable.version.desc())
    )
    if odds_table is None:
        raise PackTypeUnavailableError(f"pack_type {pack_type_id} has no published odds table")

    existing_entry = db.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key))
    if existing_entry is not None:
        pack = db.get(Pack, existing_entry.reference_id)
        assert pack is not None, "purchase ledger entry exists without a linked pack"
        return pack

    pack = Pack(
        user_id=user_id,
        pack_type_id=pack_type_id,
        odds_table_id=odds_table.id,
        price_paid=pack_type.price,
        status=PackStatus.unopened,
    )
    db.add(pack)
    db.flush()  # assign pack.id

    append_entry(
        db,
        user_id=user_id,
        entry_type=LedgerEntryType.pack_purchase,
        amount=-pack_type.price,
        idempotency_key=idempotency_key,
        reference_type="pack",
        reference_id=pack.id,
    )
    return pack


def open_pack(db: Session, *, user_id: uuid.UUID, pack_id: uuid.UUID) -> Pull:
    pack = db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if pack is None:
        raise PackNotFoundError(f"pack {pack_id} not found for user {user_id}")

    if pack.status == PackStatus.opened:
        existing_pull = db.scalar(select(Pull).where(Pull.pack_id == pack_id))
        assert existing_pull is not None, "opened pack has no linked pull"
        return existing_pull

    bands = list(db.scalars(select(OddsBand).where(OddsBand.odds_table_id == pack.odds_table_id)))
    result = roll(db, bands)

    pull = Pull(
        pack_id=pack.id,
        user_id=user_id,
        game_id=result.game.id,
        odds_band_id=result.band.id,
        locked_value=result.game.regular_price,
        status=PullStatus.vaulted,
        roll_metadata={"effective_probabilities": result.effective_probabilities},
    )
    db.add(pull)
    pack.status = PackStatus.opened
    pack.opened_at = utcnow()
    db.flush()
    return pull
