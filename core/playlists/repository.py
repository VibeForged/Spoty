"""Thin SQLAlchemy repositories for playlist persistence."""

from __future__ import annotations

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Playlist, PlaylistItem, PlaylistItemVote


class PlaylistRepository:
    """Playlist row operations. Business rules live in PlaylistService."""

    @staticmethod
    async def create(
        session: AsyncSession,
        guild_id: int,
        owner_id: int,
        name: str,
        name_key: str,
        *,
        visibility: str = "private",
    ) -> Playlist:
        playlist = Playlist(
            guild_id=guild_id,
            owner_id=owner_id,
            name=name,
            name_key=name_key,
            visibility=visibility,
            track_count=0,
        )
        session.add(playlist)
        await session.flush()
        return playlist

    @staticmethod
    async def get_owned_by_name(
        session: AsyncSession, guild_id: int, owner_id: int, name_key: str
    ) -> Playlist | None:
        result = await session.execute(
            select(Playlist).where(
                Playlist.guild_id == guild_id,
                Playlist.owner_id == owner_id,
                Playlist.name_key == name_key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_share_code(session: AsyncSession, share_code: str) -> Playlist | None:
        result = await session.execute(select(Playlist).where(Playlist.share_code == share_code))
        return result.scalar_one_or_none()

    @staticmethod
    async def share_code_exists(session: AsyncSession, share_code: str) -> bool:
        result = await session.execute(select(Playlist.id).where(Playlist.share_code == share_code))
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_for_user(session: AsyncSession, guild_id: int, owner_id: int) -> list[Playlist]:
        result = await session.execute(
            select(Playlist)
            .where(Playlist.guild_id == guild_id, Playlist.owner_id == owner_id)
            .order_by(Playlist.name_key)
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete(session: AsyncSession, playlist_id: int) -> None:
        await session.execute(delete(Playlist).where(Playlist.id == playlist_id))

    @staticmethod
    async def rename(session: AsyncSession, playlist_id: int, name: str, name_key: str) -> None:
        await session.execute(
            update(Playlist)
            .where(Playlist.id == playlist_id)
            .values(name=name, name_key=name_key, updated_at=func.now())
        )

    @staticmethod
    async def set_share_code(session: AsyncSession, playlist_id: int, share_code: str) -> None:
        await session.execute(
            update(Playlist)
            .where(Playlist.id == playlist_id)
            .values(share_code=share_code, updated_at=func.now())
        )
        await session.flush()

    @staticmethod
    async def increment_track_count(
        session: AsyncSession, playlist_id: int, amount: int
    ) -> None:
        await session.execute(
            update(Playlist)
            .where(Playlist.id == playlist_id)
            .values(track_count=Playlist.track_count + amount, updated_at=func.now())
        )


class PlaylistItemRepository:
    """Playlist item row operations."""

    @staticmethod
    async def max_position(session: AsyncSession, playlist_id: int) -> int:
        result = await session.execute(
            select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == playlist_id)
        )
        return result.scalar_one_or_none() or 0

    @staticmethod
    async def add_item(
        session: AsyncSession,
        playlist_id: int,
        position: int,
        title: str,
        url: str,
        duration: int | None,
        added_by: int,
        *,
        source: str,
        external_id: str | None = None,
        thumbnail: str | None = None,
    ) -> PlaylistItem:
        item = PlaylistItem(
            playlist_id=playlist_id,
            position=position,
            title=title,
            url=url,
            source=source,
            external_id=external_id,
            duration=duration,
            thumbnail=thumbnail,
            added_by=added_by,
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def list_items(
        session: AsyncSession,
        playlist_id: int,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[PlaylistItem]:
        stmt = (
            select(PlaylistItem)
            .where(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position)
            .offset(offset)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_at_position(
        session: AsyncSession, playlist_id: int, position: int
    ) -> PlaylistItem | None:
        result = await session.execute(
            select(PlaylistItem).where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.position == position,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def remove_at_position(session: AsyncSession, playlist_id: int, position: int) -> bool:
        result = await session.execute(
            delete(PlaylistItem).where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.position == position,
            )
        )
        if result.rowcount <= 0:
            return False

        await session.flush()
        await session.execute(
            update(PlaylistItem)
            .where(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.position > position,
            )
            .values(position=PlaylistItem.position - 1)
        )
        return True

    @staticmethod
    async def list_ids(session: AsyncSession, playlist_id: int) -> list[int]:
        result = await session.execute(
            select(PlaylistItem.id)
            .where(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position)
        )
        return list(result.scalars().all())

    @staticmethod
    async def reorder(session: AsyncSession, playlist_id: int, item_ids: list[int]) -> None:
        if not item_ids:
            return

        # Two bulk CASE updates instead of 2N per-row updates. Pass 1 moves rows to
        # negative temp positions to avoid colliding with the (playlist_id, position)
        # unique constraint; pass 2 sets the final 1-indexed positions.
        temp_positions = case(
            {item_id: -(index + 1) for index, item_id in enumerate(item_ids)},
            value=PlaylistItem.id,
        )
        final_positions = case(
            {item_id: index + 1 for index, item_id in enumerate(item_ids)},
            value=PlaylistItem.id,
        )
        where = (PlaylistItem.playlist_id == playlist_id, PlaylistItem.id.in_(item_ids))

        await session.execute(update(PlaylistItem).where(*where).values(position=temp_positions))
        await session.flush()
        await session.execute(update(PlaylistItem).where(*where).values(position=final_positions))

    @staticmethod
    async def total_duration(session: AsyncSession, playlist_id: int) -> int:
        result = await session.execute(
            select(func.coalesce(func.sum(PlaylistItem.duration), 0)).where(
                PlaylistItem.playlist_id == playlist_id
            )
        )
        return int(result.scalar_one() or 0)


class PlaylistVoteRepository:
    """Playlist vote row operations."""

    @staticmethod
    async def upsert_vote(
        session: AsyncSession, playlist_item_id: int, user_id: int, vote: int
    ) -> None:
        result = await session.execute(
            select(PlaylistItemVote).where(
                PlaylistItemVote.playlist_item_id == playlist_item_id,
                PlaylistItemVote.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.vote = vote
        else:
            session.add(
                PlaylistItemVote(
                    playlist_item_id=playlist_item_id,
                    user_id=user_id,
                    vote=vote,
                )
            )
        await session.flush()

    @staticmethod
    async def get_vote_counts(
        session: AsyncSession, item_ids: list[int]
    ) -> dict[int, tuple[int, int]]:
        if not item_ids:
            return {}

        result = await session.execute(
            select(
                PlaylistItemVote.playlist_item_id,
                PlaylistItemVote.vote,
                func.count(),
            )
            .where(PlaylistItemVote.playlist_item_id.in_(item_ids))
            .group_by(PlaylistItemVote.playlist_item_id, PlaylistItemVote.vote)
        )

        counts: dict[int, list[int]] = {item_id: [0, 0] for item_id in item_ids}
        for item_id, vote, count in result.all():
            if vote == 1:
                counts[item_id][0] = count
            elif vote == -1:
                counts[item_id][1] = count
        return {item_id: (likes, dislikes) for item_id, (likes, dislikes) in counts.items()}
