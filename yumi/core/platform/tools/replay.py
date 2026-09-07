"""Pair tool results by identity, including conservative legacy-history recovery."""

from __future__ import annotations

from uuid import uuid4


def normalize_tool_history(messages: list[dict], *, strict: bool = False) -> list[dict]:
    """Return complete, ordered tool spans without guessing ambiguous results.

    New turns require IDs. Older rows may be matched by a unique function name;
    ambiguous legacy results become explicit unknown outcomes, never successes.
    """
    out: list[dict] = []
    i = 0
    while i < len(messages):
        message = messages[i]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            if message.get("role") == "tool":
                if strict:
                    raise ValueError("Orphan tool result in the current turn")
            else:
                out.append(dict(message))
            i += 1
            continue
        calls = []
        for call in message["tool_calls"]:
            if strict and not call.get("id"):
                raise ValueError("Missing tool call ID in the current turn")
            calls.append({**call, "id": call.get("id") or "call_" + uuid4().hex})
        pending = {call["id"]: call for call in calls}
        if len(pending) != len(calls):
            raise ValueError("Duplicate tool call ID")
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            j += 1
        results = messages[i + 1 : j]
        paired: dict[str, dict] = {}
        for result in results:
            call_id = str(result.get("tool_call_id") or "")
            if not call_id:
                if strict:
                    raise ValueError("Missing tool result ID in the current turn")
                continue
            if call_id not in pending or call_id in paired:
                raise ValueError("Tool result ID does not match a unique pending call")
            paired[call_id] = dict(result)
        # Match only unique names among all remaining calls, never by position.
        for result in results:
            if result.get("tool_call_id"):
                continue
            candidates = [
                call
                for cid, call in pending.items()
                if cid not in paired and call.get("function", {}).get("name") == result.get("name")
            ]
            same_name_results = [
                r for r in results if not r.get("tool_call_id") and r.get("name") == result.get("name")
            ]
            if len(candidates) == 1 and len(same_name_results) == 1:
                call_id = candidates[0]["id"]
                paired[call_id] = {**result, "tool_call_id": call_id}
        if strict and len(paired) != len(calls):
            raise ValueError("Incomplete tool results in the current turn")
        out.append({**message, "tool_calls": calls})
        for call in calls:
            cid = call["id"]
            out.append(
                paired.get(cid)
                or {
                    "role": "tool",
                    "tool_call_id": cid,
                    "name": call.get("function", {}).get("name") or "tool",
                    "content": "Historical result unavailable: the saved call identity is ambiguous. "
                    "The outcome is unknown. Do not infer success or repeat an action without checking its state.",
                }
            )
        i = j
    return out
