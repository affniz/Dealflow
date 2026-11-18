"""What each model call cost, from token counts.

Prices are USD per million tokens, Anthropic first-party API rates as of PRICES_AS_OF. Check
https://www.anthropic.com/pricing when updating. Cache writes cost 1.25x the input rate for the
5-minute cache and 2x for the 1-hour cache.
"""

from dataclasses import dataclass
from decimal import Decimal

PRICES_AS_OF = "2026-11"
MTOK = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read: Decimal
    # some models charge more once a prompt passes a size threshold
    long_prompt_tokens: int | None = None
    long_input: Decimal | None = None
    long_output: Decimal | None = None


def _p(i: str, o: str, cr: str, **long: object) -> Price:
    return Price(Decimal(i), Decimal(o), Decimal(cr), **long)  # type: ignore[arg-type]


PRICES: dict[str, Price] = {
    "claude-fable-5-2": _p("8", "40", "0.20"),
    "claude-opus-5-5": _p("4", "20", "0.20"),
    "claude-opus-5": _p("5", "25", "0.50"),
    "claude-opus-4-8": _p("5", "25", "0.50"),
    "claude-sonnet-5-5": _p("2", "10", "0.10"),
    "claude-sonnet-5": _p("2", "10", "0.20"),
    "claude-sonnet-4-6": _p("3", "15", "0.30"),
    "claude-haiku-5-5": _p(
        "0.10",
        "0.50",
        "0.01",
        long_prompt_tokens=100_000,
        long_input=Decimal("0.50"),
        long_output=Decimal("2.50"),
    ),
}


def price_for(model: str) -> Price | None:
    """Exact id, or the longest known id the served model name starts with."""
    if model in PRICES:
        return PRICES[model]
    matches = [m for m in PRICES if model.startswith(m)]
    return PRICES[max(matches, key=len)] if matches else None


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
) -> Decimal | None:
    """None when the model isn't in the price table (the call is still recorded)."""
    price = price_for(model)
    if price is None:
        return None
    prompt = input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens
    rate_in, rate_out = price.input, price.output
    if price.long_prompt_tokens is not None and prompt > price.long_prompt_tokens:
        rate_in, rate_out = price.long_input or rate_in, price.long_output or rate_out
    total = (
        input_tokens * rate_in
        + output_tokens * rate_out
        + cache_read_tokens * price.cache_read
        + cache_write_5m_tokens * rate_in * Decimal("1.25")
        + cache_write_1h_tokens * rate_in * 2
    ) / MTOK
    return total.quantize(Decimal("0.000001"))
