import logging

logger = logging.getLogger(__name__)

_warned_models: set[str] = set()


def usd_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    prices_per_1m: dict[str, tuple[float, float]],
) -> float:
    """토큰 수와 `MODEL_PRICES_USD_PER_1M` 단가로 USD 비용을 계산한다.

    단가가 없으면(예: 로컬 VLM) 0으로 계산하고, 모델마다 한 번만 경고한다.
    """
    price = prices_per_1m.get(model)
    if price is None:
        if model not in _warned_models:
            _warned_models.add(model)
            logger.warning("no price configured for model %s; cost recorded as 0", model)
        return 0.0
    price_in, price_out = price
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
