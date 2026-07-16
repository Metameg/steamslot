"""indexes and wallet check

Revision ID: 8f3a1c2d4e5b
Revises: 23ecc1bba190
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f3a1c2d4e5b'
down_revision: Union[str, Sequence[str], None] = '23ecc1bba190'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_ledger_entries_user_id', 'ledger_entries', ['user_id'])
    op.create_index('ix_packs_user_id', 'packs', ['user_id'])
    op.create_index('ix_pulls_user_id', 'pulls', ['user_id'])
    op.create_index('ix_odds_bands_odds_table_id', 'odds_bands', ['odds_table_id'])
    op.create_index('ix_odds_tables_pack_type_id', 'odds_tables', ['pack_type_id'])
    op.create_index('ix_redemption_requests_user_id', 'redemption_requests', ['user_id'])
    op.create_index('ix_redemption_requests_fulfilled_by', 'redemption_requests', ['fulfilled_by'])
    op.create_index('ix_withdrawals_user_id', 'withdrawals', ['user_id'])

    op.create_check_constraint(
        "ck_users_wallet_nonneg", "users", "wallet_balance_cached >= 0"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_users_wallet_nonneg", "users", type_="check")

    op.drop_index('ix_withdrawals_user_id', table_name='withdrawals')
    op.drop_index('ix_redemption_requests_fulfilled_by', table_name='redemption_requests')
    op.drop_index('ix_redemption_requests_user_id', table_name='redemption_requests')
    op.drop_index('ix_odds_tables_pack_type_id', table_name='odds_tables')
    op.drop_index('ix_odds_bands_odds_table_id', table_name='odds_bands')
    op.drop_index('ix_pulls_user_id', table_name='pulls')
    op.drop_index('ix_packs_user_id', table_name='packs')
    op.drop_index('ix_ledger_entries_user_id', table_name='ledger_entries')
