"""Tests for custodian.packs.narration."""
from __future__ import annotations

import pytest

from custodian.packs.narration import TOUR, tour_intro_for_model


class TestTourStructure:
    def test_tour_has_exactly_five_tiers(self):
        assert len(TOUR) == 5

    def test_tier_ids_are_unique(self):
        assert len({tier["id"] for tier in TOUR}) == 5

    def test_tier_numbers_are_one_through_five_in_order(self):
        assert [tier["tier"] for tier in TOUR] == [1, 2, 3, 4, 5]

    @pytest.mark.parametrize("index", range(5))
    def test_each_tier_has_required_keys(self, index: int):
        tier = TOUR[index]
        assert set(tier) >= {"id", "tier", "headline", "one_liner", "show_case", "why_it_matters", "depth"}

    @pytest.mark.parametrize(
        ("tier_index", "expected_id"),
        [
            (0, "hook"),
            (1, "guarantee"),
        ],
    )
    def test_specific_tiers_have_expected_ids(self, tier_index: int, expected_id: str):
        assert TOUR[tier_index]["id"] == expected_id

    def test_fifth_tier_depth_is_weeds(self):
        assert TOUR[4]["depth"] == "weeds"

    @pytest.mark.parametrize("index", range(5))
    def test_each_tier_headline_is_non_empty(self, index: int):
        assert TOUR[index]["headline"]

    @pytest.mark.parametrize("index", range(5))
    def test_each_tier_one_liner_is_non_empty(self, index: int):
        assert TOUR[index]["one_liner"]

    @pytest.mark.parametrize("index", range(5))
    def test_each_tier_why_it_matters_is_non_empty(self, index: int):
        assert TOUR[index]["why_it_matters"]

    @pytest.mark.parametrize("index", range(5))
    def test_each_tier_show_case_is_non_empty(self, index: int):
        assert TOUR[index]["show_case"]


class TestTourIntroForModel:
    def test_returns_a_string(self):
        assert isinstance(tour_intro_for_model(), str)

    @pytest.mark.parametrize("index", range(5))
    def test_contains_all_five_headlines(self, index: int):
        assert TOUR[index]["headline"] in tour_intro_for_model()

    def test_contains_tier_reference(self):
        intro = tour_intro_for_model().lower()
        assert "tier 1" in intro or "1." in intro

    def test_does_not_start_with_architecture(self):
        assert not tour_intro_for_model().lower().startswith("architecture")

