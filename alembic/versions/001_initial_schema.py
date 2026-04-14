"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-04-14

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("prefix", sa.String(10), server_default="!"),
        sa.Column("dj_role_id", sa.BigInteger(), nullable=True),
        sa.Column("music_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("default_volume", sa.Integer(), server_default="50"),
        sa.Column("announce_songs", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("interactive_buttons", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("autoplay", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("queue_locked", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("inactivity_timeout", sa.Integer(), server_default="300"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("guild_id"),
    )

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
        sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False),
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
        sa.Column("playlist_track_id", sa.Integer(), sa.ForeignKey("playlist_tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("vote", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("playlist_track_id", "user_id", name="uq_vote_track_user"),
    )

    op.create_table(
        "fx_presets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("filter_string", sa.Text(), nullable=False),
        sa.Column("preset_data", sa.Text(), nullable=True),
        sa.Column("is_compatible", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "name", name="uq_fx_guild_name"),
    )

    op.create_table(
        "history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("track_title", sa.String(300), nullable=False),
        sa.Column("track_url", sa.String(500), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("played_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_history_guild", "history", ["guild_id"])
    op.create_index("idx_history_guild_played", "history", ["guild_id", "played_at"])

    op.create_table(
        "stats",
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("total_plays", sa.Integer(), server_default="0"),
        sa.Column("total_seconds_played", sa.BigInteger(), server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("guild_id"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("command_name", sa.String(50), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id", "command_name", "role_id", name="uq_perm_guild_cmd_role"),
    )
    op.create_index("idx_perms_guild", "permissions", ["guild_id"])


def downgrade() -> None:
    op.drop_table("permissions")
    op.drop_table("stats")
    op.drop_table("history")
    op.drop_table("fx_presets")
    op.drop_table("playlist_votes")
    op.drop_table("playlist_tracks")
    op.drop_table("playlists")
    op.drop_table("guild_settings")
