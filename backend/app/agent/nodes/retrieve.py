"""retrieve(§7.3)와 aggregate(§7.4) 노드."""

from app.agent.nodes.common import timed
from app.agent.state import Rewritten, SearchState
from app.search import hybrid
from app.search.aggregate import aggregate as aggregate_movies


def retrieval_text(rewritten: Rewritten | None, state: SearchState) -> str:
    if rewritten is None:
        return state.get("query_text") or ""
    return " ".join([rewritten.scene_ko, *rewritten.keywords_ko]).strip()


@timed("retrieve")
def retrieve(state: SearchState) -> SearchState:
    result = hybrid.retrieve(
        retrieval_text(state.get("rewritten"), state), hard_filters=state.get("hard_filters")
    )
    return {
        "scene_hits": result.scene_hits,
        "plot_hits": result.plot_hits,
        "cost_usd": result.embed_stats.cost_usd if result.embed_stats else 0.0,
    }


@timed("aggregate")
def aggregate(state: SearchState) -> SearchState:
    rewritten = state.get("rewritten")
    soft: dict[str, str] = (
        {str(k): v for k, v in rewritten.soft_filters.items()} if rewritten else {}
    )
    candidates = aggregate_movies(state.get("scene_hits", []), state.get("plot_hits", []), soft)
    return {"movie_candidates": candidates}
