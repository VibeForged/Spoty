"""add soundboard_sounds table

Revision ID: a8d8c9e0d1b2
Revises: fb3b22957a16
Create Date: 2026-06-13 01:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8d8c9e0d1b2"
down_revision: str | None = "736da436f12c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if 'soundboard_sounds' not in tables:
        op.create_table(
            "soundboard_sounds",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("guild_id", sa.BigInteger(), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("url", sa.String(length=1000), nullable=False),
            sa.Column("created_by", sa.BigInteger(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("guild_id", "name", name="uq_soundboard_guild_name"),
        )


def downgrade() -> None:
    op.drop_table("soundboard_sounds")
