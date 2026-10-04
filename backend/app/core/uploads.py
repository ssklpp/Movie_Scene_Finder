"""질의 이미지 임시 저장. Phase 5에서 R2로 바꾼다.

image_key는 업로드 폴더 안의 파일 이름이다(예: "3f2a….jpg").
"""

import uuid
from pathlib import Path

from app.core.config import REPO_ROOT

UPLOAD_DIR = REPO_ROOT / "backend" / "data" / "uploads"
MIME_BY_SUFFIX = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def save_upload(data: bytes, suffix: str, upload_dir: Path = UPLOAD_DIR) -> str:
    if suffix not in MIME_BY_SUFFIX:
        raise ValueError(f"unsupported image type: {suffix}")
    upload_dir.mkdir(parents=True, exist_ok=True)
    key = f"{uuid.uuid4().hex}{suffix}"
    (upload_dir / key).write_bytes(data)
    return key


def load_upload(key: str, upload_dir: Path = UPLOAD_DIR) -> tuple[bytes, str]:
    """(바이트, MIME). 키에 경로 구분자가 있으면 거부한다."""
    path = upload_dir / key
    if Path(key).name != key or path.suffix not in MIME_BY_SUFFIX:
        raise ValueError(f"invalid image key: {key}")
    return path.read_bytes(), MIME_BY_SUFFIX[path.suffix]
