"""clean rebuild playlist schema

Revision ID: 002_rebuild_playlists
Revises: 001_initial
Create Date: 2026-05-09

"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "002_rebuild_playlists"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _drop_if_exists(name: str) -> None:
    if _table_exists(name):
        op.drop_table(name)


def upgrade() -> None:
    _drop_if_exists("playlist_item_votes")
    _drop_if_exists("playlist_votes")
    _drop_if_exists("playlist_items")
    _drop_if_exists("playlist_tracks")
    _drop_if_exists("playlists")

    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(100), nullable=False),
        sa.Column("visibility", sa.String(20), server_default="private", nullable=False),
        sa.Column("share_code", sa.String(8), nullable=True),
        sa.Column("track_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id",
            "owner_id",
            "name_key",
            name="uq_playlist_guild_owner_name_key",
        ),
        sa.UniqueConstraint("share_code", name="uq_playlist_share_code"),
    )
    op.create_index("idx_playlists_guild_owner", "playlists", ["guild_id", "owner_id"])

    op.create_table(
        "playlist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "playlist_id",
            sa.Integer(),
            sa.ForeignKey("playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("source", sa.String(30), server_default="unknown", nullable=False),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("thumbnail", sa.String(1000), nullable=True),
        sa.Column("added_by", sa.BigInteger(), nullable=False),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playlist_id", "position", name="uq_pi_playlist_position"),
    )
    op.create_index("idx_pi_playlist_position", "playlist_items", ["playlist_id", "position"])

    op.create_table(
        "playlist_item_votes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "playlist_item_id",
            sa.Integer(),
            sa.ForeignKey("playlist_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("vote", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playlist_item_id", "user_id", name="uq_vote_item_user"),
    )
    op.create_index("idx_piv_item_vote", "playlist_item_votes", ["playlist_item_id", "vote"])


def downgrade() -> None:
    _drop_if_exists("playlist_item_votes")
    _drop_if_exists("playlist_items")
    _drop_if_exists("playlists")

    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("share_code", sa.String(8), nullable=True),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "owner_id", "name", name="uq_playlist_guild_owner_name"),
        sa.UniqueConstraint("share_code"),
    )
    op.create_index("idx_playlists_guild", "playlists", ["guild_id"])

    op.create_table(
        "playlist_tracks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "playlist_id",
            sa.Integer(),
            sa.ForeignKey("playlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("added_by", sa.BigInteger(), nullable=False),
        sa.Column("likes", sa.Integer(), server_default="0"),
        sa.Column("dislikes", sa.Integer(), server_default="0"),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playlist_id", "position", name="uq_pt_playlist_position"),
    )
    op.create_index("idx_pt_playlist", "playlist_tracks", ["playlist_id"])

    op.create_table(
        "playlist_votes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "playlist_track_id",
            sa.Integer(),
            sa.ForeignKey("playlist_tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("vote", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playlist_track_id", "user_id", name="uq_vote_track_user"),
    )
