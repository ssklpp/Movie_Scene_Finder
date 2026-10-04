import pytest

from app.core.config import Settings
from app.search import thumbs


def test_thumb_url_joins_public_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(r2_public_url="https://pub-abc.r2.dev/")
    monkeypatch.setattr(thumbs, "get_settings", lambda: settings)
    assert thumbs.thumb_url("948_backdrop_5") == "https://pub-abc.r2.dev/thumbs/948_backdrop_5.jpg"


def test_thumb_url_is_none_without_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(r2_public_url="")
    monkeypatch.setattr(thumbs, "get_settings", lambda: settings)
    assert thumbs.thumb_url("948_backdrop_5") is None
