"""Music quiz minigame text-only guess-the-song."""

from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord.ext.commands import Context

    from bot import MusicBot


class MusicQuiz:
    """Text-based music quiz using guild play history."""

    def __init__(self, ctx: Context, bot: MusicBot, rounds: int = 5, timeout: float = 30.0) -> None:
        self.ctx = ctx
        self.bot = bot
        self.rounds = rounds
        self.timeout = timeout
        self.scores: dict[int, int] = {}  # user_id -> score
        self.running = False

    async def start(self) -> None:
        """Start the quiz."""
        from core.repositories import HistoryRepo

        entries = await HistoryRepo.get_recent(self.ctx.guild.id, limit=50)
        if len(entries) < 5:
            await self.ctx.send("Not enough play history for a quiz (need at least 5 tracks).")
            return

        # Deduplicate by title
        seen = set()
        unique_entries = []
        for e in entries:
            if e.track_title not in seen:
                seen.add(e.track_title)
                unique_entries.append(e)

        if len(unique_entries) < 5:
            await self.ctx.send("Not enough unique tracks in history for a quiz.")
            return

        random.shuffle(unique_entries)
        selected = unique_entries[: self.rounds]

        self.running = True
        await self.ctx.send(
            embed=discord.Embed(
                title="Music Quiz Started!",
                description=f"**{self.rounds} rounds** — {self.timeout}s per round\nGuess the song title!",
                color=discord.Color.gold(),
            )
        )

        for i, entry in enumerate(selected, 1):
            if not self.running:
                break
            await self._run_round(i, entry)
            if i < len(selected) and self.running:
                await asyncio.sleep(2)

        await self._show_results()
        self.running = False

    async def _run_round(self, round_num: int, entry) -> None:
        """Run a single quiz round."""
        title = entry.track_title
        hint = self._make_hint(title)

        embed = discord.Embed(
            title=f"Round {round_num}/{self.rounds}",
            description=f"**Hint:** `{hint}`\nYou have {self.timeout:.0f} seconds!",
            color=discord.Color.blue(),
        )
        await self.ctx.send(embed=embed)

        def check(m):
            if m.channel != self.ctx.channel or m.author.bot:
                return False
            try:
                from rapidfuzz import fuzz

                return fuzz.partial_ratio(m.content.lower(), title.lower()) >= 70
            except ImportError:
                return m.content.lower().strip() in title.lower()

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=self.timeout)
            self.scores[msg.author.id] = self.scores.get(msg.author.id, 0) + 1
            await self.ctx.send(
                f"Correct! {msg.author.mention} got it! The answer was: **{title}**"
            )
        except TimeoutError:
            await self.ctx.send(f"Time's up! The answer was: **{title}**")

    @staticmethod
    def _make_hint(title: str) -> str:
        """Create a hint showing first letter of each word, rest as underscores."""
        words = title.split()
        hint_words = []
        for word in words:
            if not word:
                continue
            # Keep non-alphanumeric chars, mask the rest
            hint = ""
            first_alpha = True
            for ch in word:
                if ch.isalnum():
                    if first_alpha:
                        hint += ch
                        first_alpha = False
                    else:
                        hint += "_"
                else:
                    hint += ch
            hint_words.append(hint)
        return " ".join(hint_words)

    async def _show_results(self) -> None:
        """Show final leaderboard."""
        if not self.scores:
            await self.ctx.send(
                embed=discord.Embed(
                    title="Quiz Over!",
                    description="Nobody got any answers right!",
                    color=discord.Color.red(),
                )
            )
            return

        sorted_scores = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        lines = []
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        for i, (user_id, score) in enumerate(sorted_scores):
            medal = medals[i] if i < len(medals) else f"#{i + 1}"
            member = self.ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            lines.append(f"{medal} **{name}** — {score} point{'s' if score != 1 else ''}")

        await self.ctx.send(
            embed=discord.Embed(
                title="Quiz Results",
                description="\n".join(lines),
                color=discord.Color.gold(),
            )
        )

    def stop(self) -> None:
        """Stop the quiz."""
        self.running = False
