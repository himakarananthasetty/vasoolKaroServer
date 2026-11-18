"""Add a per-user idempotency key to payout requests.

Revision ID: 0002_payout_idempotency
Revises: 0001_initial
Create Date: 2026-11-18

"""

from alembic import op

revision = "0002_payout_idempotency"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE payouts ADD COLUMN idempotency_key VARCHAR(64);")
    op.create_unique_constraint("uq_payouts_idempotency", "payouts", ["user_id", "idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_payouts_idempotency", "payouts", type_="unique")
    op.execute("ALTER TABLE payouts DROP COLUMN idempotency_key;")
