from typing import Any

import httpx

from pipeline.common.http import get_json

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p"


class TmdbClient:
    def __init__(self, read_token: str, timeout_s: float = 30.0) -> None:
        if not read_token:
            raise ValueError("TMDB_READ_TOKEN is empty; set it in .env")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {read_token}"},
            timeout=timeout_s,
        )

    def discover(self, page: int, **filters: Any) -> dict[str, Any]:
        params = {"language": "ko-KR", "page": page, "include_adult": "false", **filters}
        result: dict[str, Any] = get_json(self._client, "/discover/movie", params)
        return result

    def movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        params = {"language": "ko-KR", "append_to_response": "translations"}
        result: dict[str, Any] = get_json(self._client, f"/movie/{tmdb_id}", params)
        return result

    def close(self) -> None:
        self._client.close()
