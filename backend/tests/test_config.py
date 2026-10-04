import pytest

from app.core.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql+psycopg://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    ],
)
def test_database_url_uses_psycopg_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given).database_url == expected


def test_cors_origins_from_json_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000", "https://msf.vercel.app"]')
    assert Settings().cors_origins == ["http://localhost:3000", "https://msf.vercel.app"]
