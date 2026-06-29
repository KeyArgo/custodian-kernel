"""Tests for custodian.packs.registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.packs.base import PolicyPack
from custodian.packs.registry import available, get_pack


class TestAvailable:
    def test_available_returns_expected_pack_names(self):
        assert available() == ["refunds", "purchasing", "cloud"]


class TestGetPack:
    @pytest.mark.parametrize("name", ["refunds", "purchasing", "cloud"])
    def test_get_pack_returns_matching_name(self, name: str):
        assert get_pack(name).name == name

    @pytest.mark.parametrize("name", ["refunds", "purchasing", "cloud"])
    def test_get_pack_returns_policy_pack_factory(self, name: str):
        assert isinstance(get_pack(name).factory(), PolicyPack)

    @pytest.mark.parametrize("name", ["refunds", "purchasing", "cloud"])
    def test_get_pack_corpus_dir_exists(self, name: str):
        assert get_pack(name).corpus_dir.exists()

    @pytest.mark.parametrize("name", ["refunds", "purchasing", "cloud"])
    def test_get_pack_kernel_policy_exists(self, name: str):
        assert get_pack(name).kernel_policy.exists()

    @pytest.mark.parametrize("name", ["refunds", "purchasing", "cloud"])
    def test_get_pack_blurb_is_non_empty(self, name: str):
        assert get_pack(name).blurb

    def test_unknown_pack_raises_key_error(self):
        with pytest.raises(KeyError, match="unknown pack 'missing'"):
            get_pack("missing")

