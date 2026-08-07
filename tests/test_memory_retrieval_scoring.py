"""Semantic ranking actually participates in hybrid retrieval.

The regression this pins: `_long_term_candidates` and `_tool_candidates` read
`row["_score"]`, but LanceDB attaches `_distance`. Every candidate therefore
scored 0.0 on the semantic term and ranking was decided by the lexical,
recency and importance signals alone — silently, since nothing raised.
"""

from __future__ import annotations

from yumi.core.features.memory.models import MemoryCandidate
from yumi.core.features.memory.retrieval import HybridRetriever, semantic_score


def test_semantic_score_reads_distance_not_score():
    assert semantic_score({"_distance": 0.0}) == 1.0
    assert semantic_score({"_distance": 1.0}) == 0.5
    assert semantic_score({"_distance": 3.0}) == 0.25


def test_semantic_score_falls_back_to_zero_without_a_distance():
    # Lexical-fallback rows carry no distance; keyword_score is their evidence.
    assert semantic_score({}) == 0.0
    assert semantic_score({"_score": 0.9}) == 0.0
    assert semantic_score({"_distance": None}) == 0.0
    assert semantic_score({"_distance": "not a number"}) == 0.0
    assert semantic_score({"_distance": float("nan")}) == 0.0
    assert semantic_score({"_distance": -1.0}) == 0.0


def test_semantic_score_is_monotonic_in_distance():
    scores = [semantic_score({"_distance": d}) for d in (0.0, 0.5, 1.0, 2.0, 10.0)]
    assert scores == sorted(scores, reverse=True)


class _StubMemory:
    """Just enough surface for `rank`, which only needs the clock."""

    def _current_timestamp_num(self) -> int:
        return 0


def _candidate(cid: str, score: float) -> MemoryCandidate:
    # Same content everywhere so keyword, recency and importance are constant
    # and the ordering can only come from the semantic term.
    return MemoryCandidate(
        id=cid,
        kind="fact",
        content=f"unrelated filler {cid}",
        source="long_term",
        session_id="s",
        timestamp="",
        timestamp_num=0,
        score=score,
        importance=0.0,
        metadata={},
    )


def test_semantic_similarity_changes_the_ranking():
    retriever = HybridRetriever(_StubMemory())
    ranked = retriever.rank("query", [_candidate("far", 0.1), _candidate("near", 0.9)])
    assert [c.id for c in ranked] == ["near", "far"]
    assert ranked[0].score > ranked[1].score


class _RowMemory(_StubMemory):
    """Returns one LanceDB-shaped row, the way `_search_structured_table` does."""

    long_term_table_name = "long_term"
    tool_observation_table_name = "tool_observations"

    def __init__(self, row: dict):
        self._row = row

    def _search_structured_table(self, table_name, query, *, limit, content_field):
        return [self._row] if table_name == self.long_term_table_name else []


def test_a_vector_hit_reaches_the_candidate_with_a_real_score():
    """The bug site: rows arrive with `_distance`, and the old code read `_score`."""
    memory = _RowMemory(
        {
            "id": "m1",
            "kind": "fact",
            "content": "Vincent prefers concise answers.",
            "session_id": "s",
            "updated_at_num": 0,
            "importance": 0.0,
            "confidence": 0.0,
            "_distance": 0.25,
        }
    )
    candidates = HybridRetriever(memory)._long_term_candidates("concise", limit=4)
    assert len(candidates) == 1
    assert candidates[0].score == 0.8  # 1 / (1 + 0.25); was 0.0 while reading `_score`
