"""근거 장면 썸네일(R2) 주소.

s08이 올리는 키와 backend가 만드는 URL은 반드시 같은 `thumb_key`를 쓴다.
URL은 scene_id로 바로 만들므로 배포 DB의 scenes.r2_key를 읽지 않는다.
"""

from app.core.config import get_settings

THUMB_SIZE = 512  # 긴 변 픽셀 (SPEC §6 s08)


def thumb_key(scene_id: str) -> str:
    return f"thumbs/{scene_id}.jpg"


def thumb_url(scene_id: str) -> str | None:
    """R2_PUBLIC_URL이 없으면 None(화면은 캡션만 보인다)."""
    base = get_settings().r2_public_url.rstrip("/")
    return f"{base}/{thumb_key(scene_id)}" if base else None
