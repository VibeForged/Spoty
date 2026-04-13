"""Tests for the permission system."""

from __future__ import annotations

from core.permissions import Tier, check_tier


class TestPermissions:
    def test_tier_ordering(self):
        assert Tier.EVERYONE < Tier.DJ
        assert Tier.DJ < Tier.ADMIN
        assert Tier.ADMIN < Tier.OWNER

    def test_check_tier_same_level(self):
        assert check_tier(Tier.DJ, Tier.DJ) is True

    def test_check_tier_higher(self):
        assert check_tier(Tier.ADMIN, Tier.DJ) is True
        assert check_tier(Tier.OWNER, Tier.EVERYONE) is True

    def test_check_tier_lower(self):
        assert check_tier(Tier.EVERYONE, Tier.DJ) is False
        assert check_tier(Tier.DJ, Tier.ADMIN) is False

    def test_owner_bypasses_all(self):
        assert check_tier(Tier.OWNER, Tier.ADMIN) is True
        assert check_tier(Tier.OWNER, Tier.DJ) is True
        assert check_tier(Tier.OWNER, Tier.EVERYONE) is True
