"""answer: Top 5와 근거 장면, 추천 이유. 이유는 verify의 reason을 쓴다(LLM 호출을 한 번 줄인다)."""

from app.agent.movies import movie_info
from app.agent.nodes.common import timed
from app.agent.state import EvidenceScene, ResultItem, SearchState
from app.search.thumbs import thumb_url

TOP_RESULTS = 5


@timed("answer")
def answer(state: SearchState) -> SearchState:
    verified = {v.movie_id: v for v in state.get("verified", [])}
    items = []
    for c in state.get("movie_candidates", [])[:TOP_RESULTS]:
        info = movie_info(c.movie_id)
        v = verified.get(c.movie_id)
        items.append(
            ResultItem(
                movie_id=c.movie_id,
                title_ko=info.title_ko if info else None,
                year=info.year if info else None,
                poster_url=info.poster_url if info else None,
                score=v.score if v else 0.0,
                reason=v.reason if v else "",
                evidence=[
                    EvidenceScene(
                        scene_id=h.scene_id,
                        thumb_url=thumb_url(h.scene_id),
                        caption_ko=h.caption_ko,
                    )
                    for h in c.evidence
                ],
            )
        )
    return {"result": items}
