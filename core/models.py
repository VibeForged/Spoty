"""SQLAlchemy 2.0 declarative ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class GuildSettings(Base):
    """Per-guild bot configuration."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prefix: Mapped[str] = mapped_column(String(10), default="!")
    dj_role_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    music_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_volume: Mapped[int] = mapped_column(Integer, default=50)
    announce_songs: Mapped[bool] = mapped_column(Boolean, default=True)
    interactive_buttons: Mapped[bool] = mapped_column(Boolean, default=True)
    autoplay: Mapped[bool] = mapped_column(Boolean, default=False)
    queue_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    inactivity_timeout: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Playlist(Base):
    """User-created playlist scoped to a guild."""

    __tablename__ = "playlists"
    __table_args__ = (
        UniqueConstraint("guild_id", "owner_id", "name", name="uq_playlist_guild_owner_name"),
        Index("idx_playlists_guild", "guild_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    share_code: Mapped[str | None] = mapped_column(String(8), unique=True, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tracks: Mapped[list[PlaylistTrack]] = relationship(
        back_populates="playlist", cascade="all, delete-orphan", order_by="PlaylistTrack.position"
    )


class PlaylistTrack(Base):
    """A track within a playlist."""

    __tablename__ = "playlist_tracks"
    __table_args__ = (
        UniqueConstraint("playlist_id", "position", name="uq_pt_playlist_position"),
        Index("idx_pt_playlist", "playlist_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    dislikes: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    playlist: Mapped[Playlist] = relationship(back_populates="tracks")
    votes: Mapped[list[PlaylistVote]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class PlaylistVote(Base):
    """Per-user vote on a playlist track (like/dislike)."""

    __tablename__ = "playlist_votes"
    __table_args__ = (
        UniqueConstraint("playlist_track_id", "user_id", name="uq_vote_track_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_track_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("playlist_tracks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vote: Mapped[int] = mapped_column(Integer, nullable=False)  # +1 or -1

    track: Mapped[PlaylistTrack] = relationship(back_populates="votes")


class FXPreset(Base):
    """Custom FX preset created by a guild member."""

    __tablename__ = "fx_presets"
    __table_args__ = (
        UniqueConstraint("guild_id", "name", name="uq_fx_guild_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    filter_string: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class History(Base):
    """Track play history per guild."""

    __tablename__ = "history"
    __table_args__ = (
        Index("idx_history_guild", "guild_id"),
        Index("idx_history_guild_played", "guild_id", "played_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    track_title: Mapped[str] = mapped_column(String(300), nullable=False)
    track_url: Mapped[str] = mapped_column(String(500), nullable=False)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Stats(Base):
    """Cached guild statistics."""

    __tablename__ = "stats"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    total_plays: Mapped[int] = mapped_column(Integer, default=0)
    total_seconds_played: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Permission(Base):
    """Per-guild command permission overrides."""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("guild_id", "command_name", "role_id", name="uq_perm_guild_cmd_role"),
        Index("idx_perms_guild", "guild_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    command_name: Mapped[str] = mapped_column(String(50), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
