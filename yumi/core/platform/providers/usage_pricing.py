"""Recorded token estimates, using a versioned public price snapshot.

No inference of historical prices or prices for compatible proxy endpoints.
Amounts use integer nano-USD so small embedding/cache costs do not round away.
"""

from datetime import datetime, timezone
from urllib.parse import urlparse

DEEPSEEK_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"
PRICE_VERSION = "deepseek-2026-09-08"


def price_usage(payload: dict, *, provider: str, base_url: str, started_at: float) -> dict:
    out = {**payload, "provider": provider, "request_started_at": started_at}
    if provider != "deepseek" or urlparse(base_url).hostname != "api.deepseek.com":
        return out
    rates = {
        "deepseek-v4-pro": (1320, 44, 3960),
        "deepseek-v4-flash": (440, 14, 1320),
        "deepseek-v4-flash-vision-exp": (440, 14, 1320),
    }.get(payload.get("model"))
    if rates is None:
        return out
    moment = datetime.fromtimestamp(started_at, timezone.utc)
    peak = moment.weekday() < 5 and (1 <= moment.hour < 4 or 6 <= moment.hour < 10)
    input_rate, cache_rate, output_rate = rates if peak else tuple(r // 2 for r in rates)
    prompt = max(0, int(payload.get("prompt_tokens") or 0))
    output = max(0, int(payload.get("completion_tokens") or 0))
    cached = payload.get("cached_prompt_tokens")
    valid = isinstance(cached, int) and 0 <= cached <= prompt
    cost = output * output_rate
    savings = None
    if valid:
        assert isinstance(cached, int)
        cost += (prompt - cached) * input_rate + cached * cache_rate
        savings = cached * (input_rate - cache_rate)
    out["pricing"] = {
        "version": PRICE_VERSION,
        "source": DEEPSEEK_SOURCE,
        "currency": "USD",
        "period": "peak" if peak else "off_peak",
        "input_nano_usd_per_token": input_rate,
        "cached_nano_usd_per_token": cache_rate,
        "output_nano_usd_per_token": output_rate,
        "cost_nano_usd": cost,
        "cache_savings_nano_usd": savings,
        "covered_tokens": output + (prompt if valid else 0),
    }
    return out
