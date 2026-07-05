"""Tests for custodian.inference.router.NemoClawRouter."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custodian.inference.router import DEFAULT_ENDPOINTS, NVIDIA_HOSTED, NemoClawRouter


def _ok_response(content: str = "hello") -> MagicMock:
    body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _url_error() -> urllib.error.URLError:
    return urllib.error.URLError("connection refused")


class TestNemoClawRouter:
    def test_first_endpoint_succeeds(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_urlopen(req, timeout):
            calls.append(req.full_url)
            return _ok_response("first wins")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        router = NemoClawRouter(endpoints=["http://ep1:8000/v1", "http://ep2:8000/v1"])
        result = router.complete("sys", "user")
        assert result == "first wins"
        assert len(calls) == 1
        assert "ep1" in calls[0]

    def test_falls_back_to_second_on_url_error(self, monkeypatch: pytest.MonkeyPatch):
        attempt = [0]

        def fake_urlopen(req, timeout):
            attempt[0] += 1
            if attempt[0] == 1:
                raise _url_error()
            return _ok_response("second wins")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        router = NemoClawRouter(endpoints=["http://ep1:8000/v1", "http://ep2:8000/v1"])
        result = router.complete("sys", "user")
        assert result == "second wins"
        assert attempt[0] == 2

    def test_falls_back_to_third(self, monkeypatch: pytest.MonkeyPatch):
        attempt = [0]

        def fake_urlopen(req, timeout):
            attempt[0] += 1
            if attempt[0] < 3:
                raise _url_error()
            return _ok_response("third wins")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        router = NemoClawRouter(endpoints=["http://e1/v1", "http://e2/v1", "http://e3/v1"])
        result = router.complete("sys", "user")
        assert result == "third wins"
        assert attempt[0] == 3

    def test_all_fail_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(_url_error()))
        router = NemoClawRouter(endpoints=["http://e1/v1", "http://e2/v1"])
        with pytest.raises(RuntimeError, match="all 2 cloud endpoints failed"):
            router.complete("sys", "user")

    def test_live_flag_true_on_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _ok_response())
        router = NemoClawRouter(endpoints=["http://ep1:8000/v1"])
        router.complete("sys", "user")
        assert router.live is True

    def test_live_flag_false_before_call(self):
        router = NemoClawRouter()
        assert router.live is False

    def test_name_includes_endpoint_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: _ok_response())
        router = NemoClawRouter(endpoints=["http://dgx-spark-01:8000/v1/chat/completions"])
        router.complete("sys", "user")
        assert "dgx-spark-01" in router.name

    def test_nvidia_key_added_to_hosted_endpoint(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        key_file = tmp_path / "nvidia.env"
        key_file.write_text("NVIDIA_API_KEY=test-key-abc123\n")

        seen_headers: dict = {}

        def fake_urlopen(req, timeout):
            seen_headers.update(dict(req.headers))
            return _ok_response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        # Clear env var so it doesn't shadow the key file under test
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        endpoint = f"https://{NVIDIA_HOSTED}/v1/chat/completions"
        router = NemoClawRouter(endpoints=[endpoint], nvidia_api_key_file=key_file)
        router.complete("sys", "user")
        assert "Authorization" in seen_headers
        assert "test-key-abc123" in seen_headers["Authorization"]

    def test_local_endpoint_skips_auth_header(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        key_file = tmp_path / "nvidia.env"
        key_file.write_text("NVIDIA_API_KEY=test-key-abc123\n")

        seen_headers: dict = {}

        def fake_urlopen(req, timeout):
            seen_headers.update(dict(req.headers))
            return _ok_response()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        router = NemoClawRouter(
            endpoints=["http://10.0.0.199:8000/v1/chat/completions"],
            nvidia_api_key_file=key_file,
        )
        router.complete("sys", "user")
        assert "Authorization" not in seen_headers

    def test_default_endpoints_are_two(self):
        assert len(DEFAULT_ENDPOINTS) >= 2

    def test_conforms_to_llm_client_protocol(self):
        router = NemoClawRouter()
        assert isinstance(router.name, str)
        assert isinstance(router.live, bool)
        assert callable(router.complete)
