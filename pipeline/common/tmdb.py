from typing import Any

import httpx

from pipeline.common.http import get, get_json

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
        self._image_client = httpx.Client(base_url=IMAGE_BASE_URL, timeout=timeout_s)

    def discover(self, page: int, **filters: Any) -> dict[str, Any]:
        params = {"language": "ko-KR", "page": page, "include_adult": "false", **filters}
        result: dict[str, Any] = get_json(self._client, "/discover/movie", params)
        return result

    def movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        params = {"language": "ko-KR", "append_to_response": "translations"}
        result: dict[str, Any] = get_json(self._client, f"/movie/{tmdb_id}", params)
        return result

    def movie_credits(self, tmdb_id: int) -> dict[str, Any]:
        """출연·제작진. ko-KR로 요청하면 배우·감독 이름이 한글로 온다(배역 이름은 대개 영어)."""
        result: dict[str, Any] = get_json(
            self._client, f"/movie/{tmdb_id}/credits", {"language": "ko-KR"}
        )
        return result

    def movie_images(self, tmdb_id: int) -> dict[str, Any]:
        """언어 구분 없이 모든 이미지. 각 항목의 `iso_639_1`이 None이면 글자 없는 이미지다."""
        result: dict[str, Any] = get_json(self._client, f"/movie/{tmdb_id}/images")
        return result

    def download_image(self, file_path: str, size: str = "w1280") -> bytes:
        return get(self._image_client, f"/{size}{file_path}").content

    def close(self) -> None:
        self._client.close()
        self._image_client.close()
