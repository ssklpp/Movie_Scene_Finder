"""BM25 sparse 벡터 (SPEC §7.2). 인덱싱(s07)과 질의(backend)가 반드시 이 모듈을 함께 쓴다.

한쪽의 토큰화나 가중치만 바꾸면 검색이 조용히 망가진다. 바꾸면 s07을 다시 돌려 다시 적재한다.

- 토큰화: Kiwi + 사용자 사전(`pipeline/data/user_dict.txt`). 남길 품사 NNG, NNP, XR, VV, VA, SL, SN.
  동사·형용사는 Kiwi가 어간으로 돌려준다. 영어(SL)는 소문자로 맞춘다.
- term id: mmh3.hash(token, signed=False)
- 문서 값: tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl)), k1=1.2, b=0.75
- 질의 값: 등장한 토큰마다 1.0. IDF는 Qdrant의 sparse modifier=IDF가 계산한다.
- avgdl: s07이 컬렉션별로 계산해 `pipeline/data/bm25_stats.json`에 쓰고 backend가 읽는다.
"""

import json
import logging
import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import mmh3
from kiwipiepy import Kiwi

from app.core.config import REPO_ROOT

logger = logging.getLogger(__name__)

USER_DICT_PATH = REPO_ROOT / "pipeline" / "data" / "user_dict.txt"
BM25_STATS_PATH = REPO_ROOT / "pipeline" / "data" / "bm25_stats.json"
KEEP_TAGS = frozenset({"NNG", "NNP", "XR", "VV", "VA", "SL", "SN"})
K1 = 1.2
B = 0.75

_kiwi_lock = threading.Lock()


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


@lru_cache
def get_kiwi(user_dict_path: Path = USER_DICT_PATH) -> Any:
    kiwi = Kiwi()
    if user_dict_path.exists():
        added = kiwi.load_user_dictionary(str(user_dict_path))
        logger.info("kiwi user dict: %d words from %s", added, user_dict_path)
    else:
        # 인덱싱 때 사전을 썼다면 질의도 같은 사전을 써야 토큰이 맞는다.
        logger.warning("kiwi user dict not found: %s", user_dict_path)
    return kiwi


def keep_tag(tag: str) -> bool:
    """Kiwi는 활용 종류를 접미사로 붙인다(VV-R, VA-I). 앞부분만 본다."""
    return tag.split("-", 1)[0] in KEEP_TAGS


def tokenize(text: str, kiwi: Any = None) -> list[str]:
    kiwi = kiwi or get_kiwi()
    with _kiwi_lock:
        tokens = kiwi.tokenize(text)
    return [t.form.lower() if t.tag == "SL" else t.form for t in tokens if keep_tag(t.tag)]


def term_id(token: str) -> int:
    return int(mmh3.hash(token, signed=False))


def doc_vector(tokens: Sequence[str], avgdl: float, k1: float = K1, b: float = B) -> SparseVector:
    """문서 쪽 BM25 가중치. term id가 겹치면(해시 충돌) tf를 합친다."""
    if not tokens:
        return SparseVector([], [])
    tf = Counter(term_id(t) for t in tokens)
    norm = k1 * (1 - b + b * len(tokens) / avgdl)
    ids = sorted(tf)
    return SparseVector(ids, [tf[i] * (k1 + 1) / (tf[i] + norm) for i in ids])


def query_vector(tokens: Sequence[str]) -> SparseVector:
    ids = sorted({term_id(t) for t in tokens})
    return SparseVector(ids, [1.0] * len(ids))


def average_doc_length(token_lists: Sequence[Sequence[str]]) -> float:
    return sum(len(t) for t in token_lists) / max(len(token_lists), 1)


def save_bm25_stats(stats: dict[str, dict[str, float]], path: Path = BM25_STATS_PATH) -> None:
    """{"scenes": {"avgdl": ..., "n_docs": ...}, "movies": {...}}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def load_avgdl(collection: str, path: Path = BM25_STATS_PATH) -> float:
    stats = json.loads(path.read_text(encoding="utf-8"))
    return float(stats[collection]["avgdl"])
