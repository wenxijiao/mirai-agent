"""Cache and price accounting without treating missing telemetry as zero."""

import json


def capture_usage(chunk: dict) -> dict:
    keys = (
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "cache_write_prompt_tokens",
        "request_started_at",
        "pricing",
    )
    return {key: chunk[key] for key in keys if key in chunk}


def summarize_usage(rows) -> dict:
    totals = dict(
        cached_input_tokens=0,
        uncached_input_tokens=0,
        cache_write_input_tokens=0,
        unknown_input_tokens=0,
        priced_tokens=0,
        unpriced_tokens=0,
    )
    cost = savings = prompt_total = 0
    savings_known = False
    sources = set()
    for raw in rows:
        row = dict(raw)
        prompt, output = int(row["prompt_tokens"]), int(row["completion_tokens"])
        prompt_total += prompt
        try:
            parts = json.loads(row.get("usage_details_json") or "[]")
            valid = isinstance(parts, list) and all(isinstance(p, dict) for p in parts)
            valid = valid and sum(p.get("prompt_tokens", 0) or 0 for p in parts) == prompt
            valid = valid and sum(p.get("completion_tokens", 0) or 0 for p in parts) == output
        except (ValueError, TypeError):
            valid = False
        if not valid:
            parts = [{"prompt_tokens": prompt, "completion_tokens": output}]
        for part in parts:
            pt, ct = int(part.get("prompt_tokens") or 0), int(part.get("completion_tokens") or 0)
            cached, written = part.get("cached_prompt_tokens"), part.get("cache_write_prompt_tokens", 0)
            if (
                isinstance(cached, int)
                and isinstance(written, int)
                and 0 <= cached <= pt
                and 0 <= written <= pt - cached
            ):
                totals["cached_input_tokens"] += cached
                totals["cache_write_input_tokens"] += written
                totals["uncached_input_tokens"] += pt - cached - written
            else:
                totals["unknown_input_tokens"] += pt
            pricing = part.get("pricing") or {}
            covered = max(0, min(pt + ct, int(pricing.get("covered_tokens") or 0)))
            totals["priced_tokens"] += covered
            totals["unpriced_tokens"] += pt + ct - covered
            if covered:
                cost += max(0, int(pricing.get("cost_nano_usd") or 0))
                recorded_savings = pricing.get("cache_savings_nano_usd")
                if isinstance(recorded_savings, int) and recorded_savings >= 0:
                    savings += recorded_savings
                    savings_known = True
                sources.add((str(pricing.get("version") or ""), str(pricing.get("source") or "")))
    known = prompt_total - totals["unknown_input_tokens"]
    return {
        **totals,
        "cache_hit_percent": round(100 * totals["cached_input_tokens"] / known, 1) if known else None,
        "cache_coverage_percent": round(100 * known / prompt_total, 1) if prompt_total else None,
        "estimated_cost_usd": cost / 1_000_000_000 if totals["priced_tokens"] else None,
        "cache_savings_usd": savings / 1_000_000_000 if savings_known else None,
        "currency": "USD",
        "price_sources": [{"version": version, "url": url} for version, url in sorted(sources)],
    }


def present_usage(row) -> dict:
    result = dict(row)
    result["cache"] = summarize_usage([result])
    result.pop("usage_details_json", None)
    return result
